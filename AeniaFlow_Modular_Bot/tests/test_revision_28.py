import time
import pytest
from aiogram.types import User, ChatMemberLeft
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter, TelegramNetworkError
from aeniaflow.core import access, delivery, policy
from aeniaflow.core.runtime import command_seen
from aeniaflow.handlers.system import admin_users
from aeniaflow.handlers.commands import message_series
from test_private_revision_22 import connect, incoming
from test_revision_21 import requests, texts

OWNER = 8478693660


def visible(client):
    return "\n".join(texts(client))


def callback_data(client, prefix):
    for req in reversed(client.session.requests):
        markup = getattr(req, "reply_markup", None)
        if markup:
            for row in markup.inline_keyboard:
                for b in row:
                    if (b.callback_data or "").startswith(prefix):
                        return b.callback_data
    raise AssertionError("Button not found: " + prefix)


async def unpaid(client, monkeypatch):
    original = client.session.make_request

    async def session(bot, method, timeout=None):
        if method.__api_method__ == "getChatMember":
            client.session.requests.append(method)
            return ChatMemberLeft(user=User(id=method.user_id, is_bot=False, first_name="User"))
        return await original(bot, method, timeout)

    monkeypatch.setattr(client.session, "make_request", session)


@pytest.mark.parametrize(
    "command", ["/start", ".menu", ".calc 2+2", ".note add A | B", ".find фото", ".status", ".ping"]
)
async def test_free_users_are_gated_at_start_and_every_tool(client, monkeypatch, command):
    await unpaid(client, monkeypatch)
    await client.send(command)
    assert "Подпишитесь для работы" in visible(client)
    assert any(
        getattr(b, "url", None) == "https://t.me/AeniaFlow"
        for req in client.session.requests
        if getattr(req, "reply_markup", None)
        for row in req.reply_markup.inline_keyboard
        for b in row
    )


async def test_plus_bypasses_channel_even_when_telegram_cannot_check(client, repository, monkeypatch):
    repository.upsert_user(User(id=42, is_bot=False, first_name="User"))
    repository.grant_plus(OWNER, 42, 7)
    await unpaid(client, monkeypatch)
    await client.send("/start")
    await client.send(".calc 2+2")
    assert not requests(client, "getChatMember")
    assert any(r.text == "🧮 <code>4</code>" for r in requests(client, "sendMessage"))


@pytest.mark.parametrize("owner", [42, OWNER])
async def test_maintenance_blocks_commands_and_stale_buttons_even_admin(client, repository, owner):
    await client.send("/start", user_id=owner)
    repository.set_runtime_option("maintenance", "1")
    await client.send(".calc 2+2", user_id=owner)
    await client.callback("use:coin", user_id=owner)
    assert "Бот на обслуживании" in visible(client)
    assert not any(r.text == "🧮 <code>4</code>" for r in requests(client, "sendMessage"))
    if owner == OWNER:
        await client.send(".AdminMenu", user_id=OWNER)
        assert "Управление AeniaFlow" in visible(client)
        await client.callback("admin:maintenance:off", user_id=OWNER)
        assert not policy.maintenance()


async def test_user_directory_grant_revoke_and_ban_are_confirmed(client, repository):
    await client.send("/start")
    await client.send(".users", user_id=OWNER)
    await client.callback("admin:person:42", user_id=OWNER)
    await client.callback("admin:prepare:grant:42:30", user_id=OWNER)
    assert not access.has_plus(42)
    token = callback_data(client, "admin:confirm:")
    await client.callback(token, user_id=99)
    assert not access.has_plus(42)
    await client.callback(token, user_id=OWNER)
    assert access.has_plus(42)
    expiry = repository.premium_until(42)
    await client.callback(token, user_id=OWNER)
    assert repository.premium_until(42) == expiry
    await client.callback("admin:prepare:revoke:42:0", user_id=OWNER)
    await client.callback(callback_data(client, "admin:confirm:"), user_id=OWNER)
    assert not access.has_plus(42)
    await client.send(".banuser 42 test", user_id=OWNER)
    await client.callback(callback_data(client, "admin:confirm:"), user_id=OWNER)
    await client.send(".calc 2+2")
    assert policy.banned(42) and "заблокирован" in visible(client)
    await client.callback("admin:prepare:unban:42:0", user_id=OWNER)
    await client.callback(callback_data(client, "admin:confirm:"), user_id=OWNER)
    assert not policy.banned(42)


async def test_old_confirmation_rechecks_target_admin_role(client, repository):
    await client.send("/start")
    await client.send(".banuser 42", user_id=OWNER)
    token = callback_data(client, "admin:confirm:")
    repository.change_admin(OWNER, 42, True)
    await client.callback(token, user_id=OWNER)
    assert not policy.banned(42)


async def test_admin_search_supports_cyrillic_and_literal_percent(client, repository):
    repository.upsert_user(User(id=42, is_bot=False, first_name="ИРИНА", username="someone"))
    await client.send(".users ирина", user_id=OWNER)
    assert callback_data(client, "admin:person:42")
    await client.send(".users %", user_id=OWNER)
    assert "Найдено: 0" in texts(client)[-1]


async def test_broadcast_audiences_bans_optout_and_business_contacts(client, repository, monkeypatch):
    for user in (42, 43, 44, 45):
        await client.send("/start", user_id=user)
    repository.upsert_user(User(id=46, is_bot=False, first_name="Business only"))
    repository.grant_plus(OWNER, 43, 7)
    repository.ban_user(OWNER, 44, True)
    repository.conn.execute("UPDATE users SET mail_enabled=0 WHERE user_id=45")
    assert admin_users.recipients("free") == [42]
    assert admin_users.recipients("plus") == [43]
    monkeypatch.setattr(delivery, "INTERVAL", 0)
    job = repository.new_broadcast(OWNER, "free", "NEWS")
    assert repository.queue_broadcast(OWNER, job, admin_users.recipients("free"))
    assert not repository.queue_broadcast(OWNER, job, [43])
    client.session.requests.clear()
    await delivery.broadcasts_due(client.bot)
    assert [(r.chat_id, r.text, r.business_connection_id) for r in requests(client, "sendMessage")] == [
        (42, "NEWS", None)
    ]
    assert requests(client, "sendMessage")[0].allow_paid_broadcast is False
    await delivery.broadcasts_due(client.bot)
    assert len(requests(client, "sendMessage")) == 1


async def test_broadcast_draft_requires_author_confirmation(client, repository):
    await client.send("/start")
    await client.callback("admin:castaud:free", user_id=OWNER)
    await client.send("Hello subscribers", user_id=OWNER)
    job = repository.conn.execute("SELECT * FROM broadcasts").fetchone()
    assert job["state"] == "draft"
    assert not any(r.text == "Hello subscribers" for r in requests(client, "sendMessage"))
    repository.change_admin(OWNER, 99, True)
    await client.callback(f"admin:castsend:{job['id']}", user_id=99)
    assert repository.broadcast(job["id"])["state"] == "draft"
    await client.callback(f"admin:castsend:{job['id']}", user_id=OWNER)
    assert repository.broadcast(job["id"])["state"] == "queued"


async def test_broadcast_maintenance_retry_and_unknown_result(client, repository, monkeypatch):
    await client.send("/start")
    job = repository.new_broadcast(OWNER, "all", "NEWS")
    repository.queue_broadcast(OWNER, job, [42])
    repository.set_runtime_option("maintenance", "1")
    await delivery.broadcasts_due(client.bot)
    assert repository.broadcast_counts(job) == {"pending": 1}
    repository.set_runtime_option("maintenance", "0")
    original = client.session.make_request

    async def throttled(bot, method, timeout=None):
        if method.__api_method__ == "sendMessage":
            raise TelegramRetryAfter(method=method, message="slow", retry_after=10)
        return await original(bot, method, timeout)

    monkeypatch.setattr(client.session, "make_request", throttled)
    await delivery.broadcasts_due(client.bot, now=1000)
    assert repository.broadcast(job)["next_at"] == 1011

    async def unknown(bot, method, timeout=None):
        if method.__api_method__ == "sendMessage":
            raise TelegramNetworkError(method=method, message="timeout")
        return await original(bot, method, timeout)

    monkeypatch.setattr(client.session, "make_request", unknown)
    monkeypatch.setattr(delivery, "INTERVAL", 0)
    await delivery.broadcasts_due(client.bot, now=1011)
    assert repository.broadcast_counts(job) == {"uncertain": 1}


async def test_ban_and_maintenance_stop_business_autoactions(client, repository):
    await connect(client)
    await client.feed(business_message=incoming(client, ".mute", sender=42))
    client.session.requests.clear()
    repository.set_runtime_option("maintenance", "1")
    await client.feed(business_message=incoming(client))
    assert not client.session.requests
    repository.set_runtime_option("maintenance", "0")
    repository.ban_user(OWNER, 42, True)
    await client.feed(business_message=incoming(client))
    assert not client.session.requests


async def test_chat_plus_commands_and_delivery(client, repository):
    await connect(client)
    repository.grant_plus(OWNER, 42, 30)
    await client.feed(business_message=incoming(client, ".later 10s scheduled", sender=42))
    row = repository.conn.execute("SELECT * FROM scheduled_messages").fetchone()
    assert row and row["state"] == "pending"
    await delivery.scheduled_due(client.bot, now=row["due_at"])
    sent = [r for r in requests(client, "sendMessage") if r.text == "scheduled"]
    assert len(sent) == 1 and sent[0].business_connection_id == "business"
    await delivery.scheduled_due(client.bot, now=row["due_at"])
    assert len([r for r in requests(client, "sendMessage") if r.text == "scheduled"]) == 1
    command_seen.clear()
    await client.feed(business_message=incoming(client, ".ruleadd ЦЕНА | price response", sender=42))
    await client.feed(business_message=incoming(client, "Какая цена?"))
    assert requests(client, "sendMessage")[-1].text == "price response"
    command_seen.clear()
    await client.feed(business_message=incoming(client, ".chatstats", sender=42))
    assert "Входящих:" in texts(client)[-1]


async def test_plus_form_selection_in_bot_dm_is_owner_scoped(client, repository):
    await connect(client)
    repository.grant_plus(OWNER, 42, 7)
    await client.feed(business_message=incoming(client))
    row = repository.dialogs(42)[0]
    await client.callback(f"chattool:later:{row['id']}")
    await client.send("10s chosen chat")
    job = repository.conn.execute("SELECT * FROM scheduled_messages").fetchone()
    assert job["dialog_id"] == row["id"]
    await client.callback(f"outbox:cancel:{job['id']}", user_id=99)
    assert repository.conn.execute("SELECT state FROM scheduled_messages").fetchone()[0] == "pending"
    await client.callback(f"outbox:cancel:{job['id']}")
    assert repository.conn.execute("SELECT state FROM scheduled_messages").fetchone()[0] == "cancelled"


async def test_menu_command_replaces_old_but_buttons_edit_current(client):
    await client.send(".menu")
    first = requests(client, "sendPhoto")[-1].chat_id
    await client.send(".menu")
    assert len(requests(client, "sendPhoto")) == 2 and requests(client, "deleteMessage")
    await client.callback("list:free:0", illustrated=True)
    assert requests(client, "editMessageMedia") and len(requests(client, "sendPhoto")) == 2
    assert first == 42


async def test_function_result_has_no_menu_or_success_log(client):
    await client.send(".menu")
    client.session.requests.clear()
    await client.send(".calc 2+2")
    assert len(requests(client, "sendMessage")) == 1
    assert requests(client, "sendMessage")[0].text == "🧮 <code>4</code>"
    assert requests(client, "sendMessage")[0].reply_markup is None
    assert not requests(client, "editMessageMedia") and not requests(client, "sendPhoto")


async def test_invalid_menu_message_id_creates_new_card(client, monkeypatch):
    await client.send(".menu")
    original = client.session.make_request

    async def invalid(bot, method, timeout=None):
        if method.__api_method__ == "editMessageMedia":
            raise TelegramBadRequest(method=method, message="Bad Request: MESSAGE_ID_INVALID")
        return await original(bot, method, timeout)

    monkeypatch.setattr(client.session, "make_request", invalid)
    await client.callback("list:free:0", illustrated=True)
    assert len(requests(client, "sendPhoto")) == 2
    assert "Не удалось выполнить запрос Telegram" not in visible(client)


@pytest.mark.parametrize("sender_bot", [123456, 999888])
async def test_mute_deletes_incoming_business_bot_messages(client, repository, sender_bot):
    await connect(client)
    await client.feed(business_message=incoming(client, ".mute", sender=42))
    raw = incoming(client, "/incoming bot content")
    raw["sender_business_bot"] = {"id": sender_bot, "is_bot": True, "first_name": "BusinessBot"}
    await client.feed(business_message=raw)
    assert requests(client, "deleteBusinessMessages")[-1].message_ids == [raw["message_id"]]


@pytest.mark.parametrize(
    "actor,target,label",
    [(42, 8285233133, "Администратор"), (42, OWNER, "Владелец"), (8285233133, OWNER, "Владелец")],
)
async def test_mute_hierarchy_blocks_lower_rank(client, repository, actor, target, label):
    await connect(client, owner=actor)
    await client.feed(business_message=incoming(client, ".mute", sender=actor, chat=target))
    assert not repository.dialogs(actor)[0]["muted"]
    assert label in visible(client) and "защищён" in visible(client)
    assert not requests(client, "deleteBusinessMessages")


async def test_send_new_limits_and_no_summary(client, monkeypatch):
    assert message_series.INTERVAL == 0.5 and message_series.COOLDOWN == 5
    assert len(message_series.parse_messages("50 hello")) == 50
    with pytest.raises(ValueError):
        message_series.parse_messages("51 hello")
    monkeypatch.setattr(message_series, "INTERVAL", 0)
    await client.send(".send 50 hello")
    assert len([r for r in requests(client, "sendMessage") if r.text == "hello"]) == 50
    assert not requests(client, "sendPhoto")


async def test_antimute_sends_exactly_one_message_and_deletes_input(client, repository):
    await connect(client)
    repository.grant_plus(OWNER, 42, 7)
    raw = incoming(client, ".antimute one message", sender=42)
    await client.feed(business_message=raw)
    output = requests(client, "sendMessage")
    assert (
        len(output) == 1
        and output[0].text == "one message"
        and output[0].business_connection_id == "business"
    )
    assert len(requests(client, "deleteBusinessMessages")) == 1
    assert requests(client, "deleteBusinessMessages")[0].message_ids == [raw["message_id"]]


async def test_long_plain_results_keep_unicode_without_menu(client):
    from aiogram.types import Message
    from aeniaflow.core.ui import answer_text

    message = Message.model_validate(client.message(text=".gpt")).as_(client.bot)
    body = "<данные>" + "😀я" * 1700 + "конец"
    await answer_text(message, body)
    sent = requests(client, "sendMessage")
    assert len(sent) == 2 and "".join(r.text for r in sent) == body
    assert all(r.reply_markup is None and r.parse_mode is None for r in sent)
    assert all(len(r.text.encode("utf-16-le")) // 2 <= 4096 for r in sent)


async def test_admin_pages_and_diagnostics_still_work_in_maintenance(client, repository):
    for user in range(1000, 1045):
        repository.change_admin(OWNER, user, True)
    repository.set_runtime_option("maintenance", "1")
    await client.callback("admin:view:admins", user_id=OWNER, illustrated=True)
    await client.callback("panelpage:1", user_id=OWNER, illustrated=True)
    assert "2 /" in texts(client)[-1] and "Бот на обслуживании" not in texts(client)[-1]
    await client.callback("admin:diagnostics:open", user_id=OWNER)
    assert "Бот на обслуживании" not in texts(client)[-1]
    assert requests(client, "sendMessage")


async def test_revoked_plus_blocks_old_autoread_button_and_cancels_queue(client, repository):
    await connect(client)
    await client.feed(business_message=incoming(client))
    row = repository.dialogs(42)[0]
    repository.grant_plus(OWNER, 42, 7)
    job = repository.queue_message(42, row["id"], "later", int(time.time()))
    repository.revoke_plus(OWNER, 42)
    await client.callback(f'chatset:autoread:{row["id"]}:on')
    assert not repository.dialog(42, row["id"])["autoread"]
    assert (
        repository.conn.execute("SELECT state FROM scheduled_messages WHERE id=?", (job,)).fetchone()[0]
        == "cancelled"
    )
    before = len(requests(client, "sendMessage"))
    await delivery.scheduled_due(client.bot)
    assert len(requests(client, "sendMessage")) == before


async def test_deleted_business_menu_is_forgotten_and_recreated(client, repository):
    from aeniaflow.core.ui import panels
    import json

    await connect(client)
    await client.feed(business_message=incoming(client, ".menu", sender=42))
    saved = repository.load_panel(client.bot.id, "business", 77)
    mid = json.loads(saved["message"])["message_id"]
    await client.feed(
        deleted_business_messages={
            "business_connection_id": "business",
            "chat": {"id": 77, "type": "private"},
            "message_ids": [mid],
        }
    )
    assert not repository.load_panel(client.bot.id, "business", 77)
    assert not panels.get((client.bot.id, "business", 77))
    await client.feed(business_message=incoming(client, ".profile", sender=42))
    assert len(requests(client, "sendPhoto")) == 2
    assert not requests(client, "editMessageMedia")


async def test_schedule_uncertain_result_is_not_repeated_after_restart(client, repository, monkeypatch):
    await connect(client)
    await client.feed(business_message=incoming(client))
    repository.grant_plus(OWNER, 42, 7)
    row = repository.dialogs(42)[0]
    job = repository.queue_message(42, row["id"], "once", int(time.time()))
    original = client.session.make_request
    calls = []

    async def lost(bot, method, timeout=None):
        if method.__api_method__ == "sendMessage":
            calls.append(method)
            raise TelegramNetworkError(method=method, message="lost response")
        return await original(bot, method, timeout)

    monkeypatch.setattr(client.session, "make_request", lost)
    await delivery.scheduled_due(client.bot)
    delivery.recover_interrupted()
    await delivery.scheduled_due(client.bot)
    assert len(calls) == 1 and calls[0].chat_id == 77 and calls[0].business_connection_id == "business"
    assert (
        repository.conn.execute("SELECT state FROM scheduled_messages WHERE id=?", (job,)).fetchone()[0]
        == "uncertain"
    )


async def test_readable_connection_guide_is_used_with_actual_bot_username(client):
    from pathlib import Path

    await client.send(".connect")
    req = requests(client, "sendPhoto")[-1]
    assert Path(req.photo.path).name == "connect.png"
    assert "@AeniaFlowTestBot" in req.caption
    assert "24 часа" in req.caption


def test_schema_seven_upgrade_preserves_existing_records_and_creates_backup(tmp_path):
    from aeniaflow.core.database import Database

    path = tmp_path / "legacy.sqlite3"
    old = Database(str(path))
    old.upsert_user(User(id=42, is_bot=False, first_name="Existing"))
    old.save_note(42, "Saved", "Keep this")
    order = old.create_order(42, "month", 50, 30, now=1000)
    old.fulfill_order(old.payload(order["order_id"]), 42, "XTR", 50, "retained", now=1001)
    until = old.premium_until(42)
    for table in (
        "referrals",
        "referral_rewards",
        "referral_payouts",
        "plus_grants",
        "admin_actions",
        "broadcast_recipients",
        "broadcasts",
        "scheduled_messages",
        "reply_rules",
    ):
        old.conn.execute(f"DROP TABLE {table}")
    for table, names in {
        "users": ("banned", "referral_locked", "ban_reason", "last_seen", "dm_started", "mail_enabled"),
        "payments": ("access_revoked",),
        "private_dialogs": ("tag", "autoread", "incoming_count", "outgoing_count"),
    }.items():
        for name in names:
            old.conn.execute(f"ALTER TABLE {table} DROP COLUMN {name}")
    old.conn.execute("PRAGMA user_version=7")
    old.close()
    new = Database(str(path))
    assert new.conn.execute("PRAGMA user_version").fetchone()[0] == 8
    assert new.premium_until(42) == until and new.payment("retained")
    assert new.notes(42)[0]["body"] == "Keep this"
    assert new.get_user(42)["referral_locked"]
    assert list(tmp_path.glob("legacy.sqlite3.pre-v8-*.bak"))
    new.close()
