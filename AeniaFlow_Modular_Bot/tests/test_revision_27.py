"""Regression journeys for owner access, administration, reusable UI and human-only DMs."""

import json

import pytest
from aiogram.types import User
from aeniaflow.core import access, ai_service, ffmpeg
from aeniaflow.core.database import Database
from aeniaflow.core.ui import panels
from aeniaflow.core.inputs import pending_inputs
from aeniaflow.catalog import FEATURES
from aeniaflow.handlers.commands import COMMANDS, message_series
from test_private_revision_22 import connect, incoming
from test_revision_21 import requests, texts
from test_revision_25 import sample_media, offline_services  # noqa: F401

OWNER = 8478693660


def visible(client):
    return "\n".join(texts(client))


def buttons(client):
    candidates = [r for r in client.session.requests if getattr(r, "reply_markup", None)]
    return [b for row in candidates[-1].reply_markup.inline_keyboard for b in row] if candidates else []


@pytest.mark.parametrize("identifier", [8478693660, 8285233133])
async def test_shipped_owner_and_previous_admin_have_free_plus(client, identifier):
    assert access.is_owner(identifier) and access.has_plus(identifier)
    await client.send(".premium", user_id=identifier)
    assert "без срока и без оплаты" in visible(client)
    await client.callback("pay:month", user_id=identifier)
    assert not requests(client, "sendInvoice")


@pytest.mark.parametrize(
    "command",
    [
        ".AdminMenu",
        ".admin",
        ".adminadd 55",
        ".adminremove 8285233133",
        ".aikey sk-" + "q" * 30,
        ".aimodel fake",
        ".adminpause",
    ],
)
async def test_non_admin_commands_are_silent_and_cannot_mutate(client, repository, command):
    await client.send(command)
    assert not client.session.requests
    assert repository.admin_override(55) is None
    assert repository.runtime_option("openai_api_key") == ""
    assert repository.runtime_option("maintenance") == ""


async def test_admin_add_remove_and_key_are_durable_and_secret(client, repository, tmp_path):
    await client.send(".AdminMenu", user_id=OWNER)
    await client.callback("admin:input:adminadd", user_id=OWNER, mid=100, illustrated=True)
    await client.send("99", user_id=OWNER)
    assert access.is_owner(99) and access.has_plus(99)
    await client.send(".AdminMenu", user_id=99)
    await client.callback("admin:input:aikey", user_id=99, mid=101, illustrated=True)
    secret = "sk-proj-" + "x" * 48
    await client.send(secret, user_id=99)
    assert repository.runtime_option("openai_api_key") == secret
    assert secret not in visible(client)
    assert requests(client, "deleteMessage")
    assert secret not in "\n".join(str(tuple(r)) for r in repository.conn.execute("SELECT * FROM audit"))
    assert secret not in json.dumps(repository.export_user(99))
    await client.send(".aimodel gpt-4.1-mini", user_id=99)
    assert ai_service.api_key() == secret and ai_service.model_name() == "gpt-4.1-mini"
    from aeniaflow.core.telegram_errors import redact

    assert secret not in redact("error " + secret)
    path = repository.conn.execute("PRAGMA database_list").fetchone()[2]
    reopened = Database(path)
    assert reopened.admin_override(99) and reopened.runtime_option("openai_api_key") == secret
    reopened.close()
    await client.send(".adminremove 99", user_id=OWNER)
    assert not access.is_owner(99) and not access.has_plus(99)
    before = len(client.session.requests)
    await client.send(".AdminMenu", user_id=99)
    assert len(client.session.requests) == before
    await client.send(".adminremove 8478693660", user_id=OWNER)
    assert access.is_owner(OWNER)


async def test_forged_admin_callback_and_revoked_pending_input_cannot_change_key(client, repository):
    await client.callback("admin:input:aikey")
    assert not pending_inputs
    repository.change_admin(OWNER, 99, True)
    await client.callback("admin:input:aikey", user_id=99)
    repository.change_admin(OWNER, 99, False)
    await client.send("sk-" + "z" * 40, user_id=99)
    assert repository.runtime_option("openai_api_key") == ""


async def test_admin_controls_never_open_in_business_dialog(client):
    await connect(client, owner=OWNER)
    await client.feed(business_message=incoming(client, ".AdminMenu", sender=OWNER))
    assert not requests(client, "sendPhoto") and not requests(client, "sendMessage")
    await client.callback("admin:input:aikey", user_id=OWNER, chat_id=77, business="business")
    assert not pending_inputs


@pytest.mark.parametrize("command", ["/start", "/help", "/paysupport", "/calc 2+2"])
async def test_slash_commands_are_ignored_in_business_even_human_chat(client, command):
    await connect(client)
    client.session.requests.clear()
    await client.feed(business_message=incoming(client, command, sender=42))
    assert not client.session.requests


async def test_known_bot_peers_do_not_receive_commands_or_autoanswers(client, repository):
    await connect(client)
    repository.save_autoreply(42, enabled=True)
    repository.remember_peer(User(id=888, is_bot=True, first_name="Peer"))
    before = len(client.session.requests)
    await client.feed(business_message=incoming(client, ".menu", sender=42, chat=888, verified_human=False))
    await client.feed(
        business_message=incoming(client, ".send 3 Hi", sender=42, chat=888, verified_human=False)
    )
    assert len(client.session.requests) == before
    raw = incoming(client, "hello", sender=888, chat=888, verified_human=False)
    raw["from"]["is_bot"] = True
    await client.feed(business_message=raw)
    assert len(client.session.requests) == before


async def test_human_incoming_verifies_peer_then_dot_commands_work(client, repository):
    await connect(client)
    assert repository.peer_type(77) is None
    await client.feed(business_message=incoming(client, "hello", verified_human=False))
    assert repository.peer_type(77) is False
    await client.feed(business_message=incoming(client, ".calc 6*7", sender=42, verified_human=False))
    assert "42" in visible(client)


async def test_connected_home_has_no_setup_prompt_and_missing_reply_right_is_not_disconnected(client):
    await connect(client, reply=False)
    await client.send("/start")
    assert not any(b.callback_data == "menu:connect" for b in buttons(client))
    assert "Сначала подключите" not in visible(client)
    await client.callback("menu:connect", mid=100, illustrated=True)
    assert "Личные чаты подключены" in visible(client)
    assert "/mybots" not in texts(client)[-1]


@pytest.mark.parametrize("business", [False, True])
async def test_start_sends_new_card_and_back_edits_latest_even_after_memory_restart(client, business):
    if business:
        await connect(client)

    async def command(text):
        if business:
            await client.feed(business_message=incoming(client, text, sender=42))
        else:
            await client.send(text)

    await command(".start" if business else "/start")
    original = requests(client, "sendPhoto")[0].chat_id
    panels.clear()
    await command(".start" if business else "/start")
    await command(".calc 6*7")
    assert "42" in texts(client)[-1]
    await client.callback(
        "menu:home",
        mid=100,
        chat_id=77 if business else 42,
        business="business" if business else None,
        illustrated=True,
    )
    assert len(requests(client, "sendPhoto")) == 2
    edits = requests(client, "editMessageMedia")
    assert len(edits) == 1 and all(e.message_id == 101 and e.chat_id == original for e in edits)
    assert [r.text for r in requests(client, "sendMessage")] == ["🧮 <code>42</code>"]


async def test_function_buttons_have_names_and_mute_command_is_in_opened_card(client):
    await client.send(".free")
    assert "Мут" in [b.text for b in buttons(client)]
    assert "Размут" in [b.text for b in buttons(client)]
    assert not any(".mute" in b.text or ".unmute" in b.text for b in buttons(client))
    await client.callback("run:mute:free:0", mid=100, illustrated=True)
    assert "<code>.mute</code>" in texts(client)[-1]
    assert any(b.callback_data == "muterun:mute" for b in buttons(client))


@pytest.mark.parametrize("business", [False, True])
async def test_series_count_picker_is_finite_and_never_shows_stop(client, monkeypatch, business):
    monkeypatch.setattr(message_series, "INTERVAL", 0)
    if business:
        await connect(client)
    await client.callback(
        "use:send",
        chat_id=77 if business else 42,
        business="business" if business else None,
        illustrated=True,
    )
    assert any(b.callback_data == "sendcount:5" for b in buttons(client))
    await client.callback(
        "sendcount:5",
        chat_id=77 if business else 42,
        business="business" if business else None,
        illustrated=True,
    )
    if business:
        await client.feed(business_message=incoming(client, "<Привет>", sender=42))
    else:
        await client.send("<Привет>")
    sent = requests(client, "sendMessage")
    assert [r.text for r in sent] == ["<Привет>"] * 5
    assert all(r.parse_mode is None and r.chat_id == (77 if business else 42) for r in sent)
    assert not message_series.active and not pending_inputs
    assert ".stop" not in visible(client)
    assert "stop" not in COMMANDS and "stop" not in FEATURES
    assert texts(client)[-1] == "<Привет>"


async def test_series_cooldown_and_validation_do_not_send_more(client, monkeypatch):
    monkeypatch.setattr(message_series, "INTERVAL", 0)
    await client.send(".send 2 Hi")
    await client.send(".send 2 Again")
    await client.send(".send 100 Bad")
    assert [r.text for r in requests(client, "sendMessage")][:2] == ["Hi", "Hi"]
    assert not any(r.text in {"Again", "Bad"} for r in requests(client, "sendMessage"))
    assert "5 секунд" in visible(client)


async def test_saved_replies_are_owner_scoped_and_do_not_expose_other_owners(client, repository):
    await client.send(".replyadd привет | <Привет>")
    await client.send(".reply привет")
    assert requests(client, "sendMessage")[-1].text == "<Привет>"
    await client.send(".reply привет", user_id=99)
    assert repository.saved_reply(99, "привет") is None
    await client.send(".replydel привет")
    assert repository.saved_reply(42, "привет") is None


async def test_chat_note_personal_reply_pause_and_resume(client, repository):
    await connect(client)
    await client.feed(business_message=incoming(client, "hello"))
    row = repository.dialogs(42)[0]
    await client.feed(business_message=incoming(client, ".chatnote Секретная пометка", sender=42))
    assert repository.dialog(42, row["id"])["note"] == "Секретная пометка"
    assert "Секретная пометка" not in visible(client)
    await client.feed(business_message=incoming(client, ".chatauto Персональный ответ", sender=42))
    await client.feed(business_message=incoming(client, "question"))
    assert requests(client, "sendMessage")[-1].text == "Персональный ответ"
    await client.feed(business_message=incoming(client, ".pause", sender=42))
    assert repository.dialog(42, row["id"])["paused"]
    before = len(requests(client, "sendMessage"))
    await client.feed(business_message=incoming(client, "again"))
    assert len(requests(client, "sendMessage")) == before
    await client.feed(business_message=incoming(client, ".resume", sender=42))
    assert not repository.dialog(42, row["id"])["paused"]
    await client.callback(f'chattool:chatnote:{row["id"]}')
    await client.send("Обновлённая пометка")
    assert repository.dialog(42, row["id"])["note"] == "Обновлённая пометка"
    await client.callback(f'chattool:chatauto:{row["id"]}', user_id=99)
    await client.send("Взлом", user_id=99)
    assert repository.dialog(42, row["id"])["reply_text"] == "Персональный ответ"


async def test_read_business_message_has_owner_and_rights_checks(client, repository):
    await connect(client)
    client.session.connections["business"]["rights"]["can_read_messages"] = True
    peer = incoming(client, "hello")
    await client.feed(business_message=peer)
    await client.feed(business_message=incoming(client, ".read", sender=42))
    request = requests(client, "readBusinessMessage")[-1]
    assert request.message_id == peer["message_id"] and request.chat_id == 77


async def test_long_result_paginates_without_losing_text_or_new_menu(client, repository):
    from aeniaflow.core.ui import panel, panel_page
    from aiogram.types import Message

    message = Message.model_validate(client.message(text=".menu")).as_(client.bot)
    text = "Начало " + ("Привет 😀 " * 400) + "Конец"
    await panel(message, text)
    saved = repository.load_panel(client.bot.id, None, 42)
    assert json.loads(saved["pages"])["text"] == text
    for index in range(1, 8):
        await panel_page(message, index)
    assert len(requests(client, "sendPhoto")) == 1
    assert not requests(client, "sendMessage")
    assert "Конец" in texts(client)[-1]


@pytest.mark.parametrize(
    "code",
    ["gif", "meme", "resize", "rotate", "mirror", "speed", "voice", "circle", "clone", "words", "stop"],
)
def test_retired_tools_cannot_run(code):
    from aeniaflow.handlers.system.actions import ACTIONS

    assert code not in FEATURES and code not in COMMANDS and code not in ACTIONS


def test_automatic_ffmpeg_has_required_encoders_without_system_path(monkeypatch):
    monkeypatch.delenv("FFMPEG_PATH", raising=False)
    monkeypatch.setattr(ffmpeg.shutil, "which", lambda name: None)
    binary = ffmpeg.ffmpeg_binary()
    assert binary and "imageio_ffmpeg" in binary
    assert ffmpeg.probe_ffmpeg(binary)["ready"]


async def test_videonote_uses_real_bundled_ffmpeg(
    client, repository, offline_services, monkeypatch  # noqa: F811
):
    from test_revision_25 import attachment

    monkeypatch.delenv("FFMPEG_PATH", raising=False)
    monkeypatch.setattr(ffmpeg.shutil, "which", lambda name: None)
    raw = client.message(caption=".videonote", **attachment("videonote"))
    await client.feed(message=raw)
    assert len(requests(client, "sendVideoNote")) == 1
    assert not any("Не удалось" in text for text in texts(client))


async def test_old_admin_pages_are_blocked_after_access_revocation(client, repository):
    repository.change_admin(OWNER, 99, True)
    for identifier in range(1000, 1045):
        repository.change_admin(OWNER, identifier, True)
    await client.callback("admin:view:admins", user_id=99, illustrated=True)
    before = len(requests(client, "editMessageMedia"))
    repository.change_admin(OWNER, 99, False)
    await client.callback("panelpage:1", user_id=99, illustrated=True)
    assert len(requests(client, "editMessageMedia")) == before


async def test_immediate_business_button_accepts_sender_business_bot_on_menu(client):
    await connect(client)
    await client.feed(business_message=incoming(client, "hello", verified_human=False))
    raw = client.message(
        user_id=123456,
        chat_id=77,
        business_connection_id="business",
        photo=[{"file_id": "cover", "file_unique_id": "cover", "width": 100, "height": 100}],
    )
    raw["from"]["is_bot"] = True
    raw["sender_business_bot"] = {"id": 123456, "is_bot": True, "first_name": "AeniaFlow"}
    await client.feed(
        callback_query={
            "id": "business-menu",
            "from": {"id": 42, "is_bot": False, "first_name": "Owner"},
            "chat_instance": "case",
            "data": "use:coin",
            "message": raw,
        }
    )
    assert requests(client, "sendMessage")[-1].business_connection_id == "business"
    assert not requests(client, "sendPhoto")


async def test_typed_chatnote_off_keeps_selected_dialog(client, repository):
    await connect(client)
    await client.feed(business_message=incoming(client, "hello"))
    row = repository.dialogs(42)[0]
    repository.update_dialog(42, row["id"], "note", "Private")
    await client.callback(f'chattool:chatnote:{row["id"]}')
    await client.send(".chatnote off")
    assert repository.dialog(42, row["id"])["note"] == ""
