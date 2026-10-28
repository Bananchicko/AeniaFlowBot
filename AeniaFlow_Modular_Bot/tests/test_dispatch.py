from aeniaflow.core import access
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace
from aiogram.types import User
from aeniaflow.core.runtime import command_seen
from aeniaflow.handlers.system import sections, payments, admin
from aeniaflow.catalog import FEATURES, PREMIUM_CODES
from aeniaflow.handlers.commands import COMMANDS
from aeniaflow.handlers.system.command_dispatcher import SECTIONS


def messages(client):
    return [
        getattr(r, "text", None)
        or getattr(getattr(r, "media", None), "caption", None)
        or getattr(r, "caption", None)
        or ""
        for r in client.session.requests
        if r.__api_method__
        in {"sendMessage", "editMessageText", "sendPhoto", "editMessageMedia", "editMessageCaption"}
    ]


async def test_menu_callback_uses_human_not_bot_identity(client, repository):
    repository.upsert_user(User(id=42, is_bot=False, first_name="Alice"))
    repository.set_timezone(42, "Europe/Moscow")
    await client.callback("menu:profile")
    assert "<b>Alice</b>" in messages(client)[-1]
    await client.callback("menu:settings")
    assert "Europe/Moscow" in messages(client)[-1]
    assert "<code>42</code>" in messages(client)[-1]
    assert repository.get_user(123456) is None


async def test_channel_button_checks_clicking_user(client, monkeypatch):
    monkeypatch.setattr(sections, "settings", SimpleNamespace(news_channel="@AeniaFlow"))
    await client.callback("sub:check", user_id=42)
    assert client.session.member_ids == [42]
    assert "подтверждён" in messages(client)[-1]


async def test_autoreply_callback_uses_owner_and_is_plain_text(client, repository):
    repository.save_connection("connection", 42, True, True)
    repository.save_autoreply(42, reply_text="<b>My & message</b>")
    await client.callback("menu:autoreply")
    assert "&lt;b&gt;My &amp; message&lt;/b&gt;" in messages(client)[-1]
    await client.callback("auto:on")
    assert repository.get_autoreply(42)["enabled"] == 1
    assert repository.get_user(123456) is None


async def test_private_account_never_leaks_into_group(client, repository):
    repository.save_note(42, "Secret", "Body")
    await client.callback("menu:profile", chat_id=-1001)
    await client.send(".notes", chat_id=-1001)
    assert all("Secret" not in x and "Body" not in x for x in messages(client))
    assert all("личном" in x for x in messages(client))


async def test_other_user_cannot_complete_task_or_cancel_reminder(client, repository):
    task = repository.add_task(42, "Secret")
    reminder = repository.add_reminder(42, 42, "Secret", 123456)
    await client.callback(f"task:done:42:{task}", user_id=99)
    await client.callback(f"remind:cancel:42:{reminder}", user_id=99)
    assert repository.tasks(42)[0]["done"] == 0
    assert repository.reminders(42)[0]["status"] == "pending"


async def test_invoice_uses_only_stars_and_owner_bound_payload(client, repository, monkeypatch):
    monkeypatch.setattr(payments, "settings", SimpleNamespace(support_username="support"))
    await client.callback("pay:month")
    invoices = [r for r in client.session.requests if r.__api_method__ == "sendInvoice"]
    assert len(invoices) == 1
    invoice = invoices[0]
    assert invoice.currency == "XTR" and invoice.provider_token == ""
    assert len(invoice.prices) == 1 and invoice.prices[0].amount == 50
    assert repository.order(invoice.payload[4:])["user_id"] == 42
    await client.callback("pay:month", chat_id=-1001)
    assert len([r for r in client.session.requests if r.__api_method__ == "sendInvoice"]) == 1


async def test_real_router_successful_payment_then_duplicate(client, repository):
    order = repository.create_order(42, "month", 50, 30)
    paid = {
        "currency": "XTR",
        "total_amount": 50,
        "invoice_payload": repository.payload(order["order_id"]),
        "telegram_payment_charge_id": "telegram-charge",
        "provider_payment_charge_id": "",
    }
    raw = client.message(successful_payment=paid)
    await client.feed(message=raw)
    expiry = repository.premium_until(42)
    await client.feed(message=raw)
    assert repository.premium_until(42) == expiry > int(datetime.now(timezone.utc).timestamp())
    assert len(repository.payments_for(42)) == 1
    assert "уже учтён" in messages(client)[-1]
    refund = dict(paid)
    await client.feed(message=client.message(refunded_payment=refund))
    assert repository.payment("telegram-charge")["status"] == "refunded"


async def test_checkout_router_rejects_tampered_user(client, repository):
    order = repository.create_order(42, "month", 50, 30)
    await client.feed(
        pre_checkout_query={
            "id": "checkout",
            "from": {"id": 99, "is_bot": False, "first_name": "Other"},
            "currency": "XTR",
            "total_amount": 50,
            "invoice_payload": repository.payload(order["order_id"]),
        }
    )
    replies = [r for r in client.session.requests if r.__api_method__ == "answerPreCheckoutQuery"]
    assert len(replies) == 1 and not replies[0].ok


async def test_user_cannot_call_owner_tools(client, repository, monkeypatch):
    monkeypatch.setattr(access, "settings", replace(access.settings, admin_ids=frozenset({1})))
    await client.send(".refund anything")
    assert not any(r.__api_method__ == "refundStarPayment" for r in client.session.requests)
    assert not client.session.requests


async def test_simple_and_premium_commands_through_router(client):
    await client.send(".calc (12+5)*3")
    assert "51" in messages(client)[-1]
    command_seen.clear()
    await client.send(".gpt test")
    assert "AeniaFlow+" in messages(client)[-1]
    assert ".gpt" in FEATURES["gpt"][1]


async def test_unknown_command_and_other_bot_target(client):
    await client.send("/does_not_exist")
    count = len(messages(client))
    await client.send(".calc@SomeOtherBot 1+1")
    assert len(messages(client)) == count


def test_every_advertised_command_is_implemented():
    assert set(FEATURES) <= set(COMMANDS) | set(SECTIONS)
    assert PREMIUM_CODES <= set(COMMANDS)


async def test_stale_game_button_cannot_change_new_game(client, repository):
    await client.send(".x")
    old = repository.game("ttt", 42, 42)
    command_seen.clear()
    await client.send(".x")
    new = repository.game("ttt", 42, 42)
    await client.callback(f'ttt:{old["id"]}:0', mid=old["message_id"])
    assert repository.game("ttt", 42, 42) == new
    await client.callback(f'ttt:{new["id"]}:0', mid=new["message_id"])
    assert repository.game("ttt", 42, 42)["board"][0] == "❌"


async def test_owner_refund_requires_confirmation_and_is_idempotent(client, repository, monkeypatch):
    monkeypatch.setattr(access, "settings", replace(access.settings, admin_ids=frozenset({42})))
    order = repository.create_order(42, "month", 50, 30)
    repository.fulfill_order(repository.payload(order["order_id"]), 42, "XTR", 50, "refund-me")
    await client.send(".refund refund-me")
    assert not any(r.__api_method__ == "refundStarPayment" for r in client.session.requests)
    confirmation = [r for r in client.session.requests if r.__api_method__ == "sendPhoto"][-1]
    data = confirmation.reply_markup.inline_keyboard[0][0].callback_data
    await client.callback(data, user_id=99)
    assert not any(r.__api_method__ == "refundStarPayment" for r in client.session.requests)
    await client.callback(data)
    await client.callback(data)
    assert len([r for r in client.session.requests if r.__api_method__ == "refundStarPayment"]) == 1
    assert repository.payment("refund-me")["status"] == "refunded"


async def test_reconciliation_recovers_missing_purchase_and_refund(repository, monkeypatch):
    from unittest.mock import AsyncMock

    monkeypatch.setattr(access, "settings", replace(access.settings, admin_ids=frozenset({42})))
    order = repository.create_order(42, "month", 50, 30, now=1000)
    user = User(id=42, is_bot=False, first_name="Alice")
    purchase = SimpleNamespace(
        id="recovered",
        amount=50,
        date=datetime.fromtimestamp(1001, timezone.utc),
        source=SimpleNamespace(
            transaction_type="invoice_payment",
            invoice_payload=repository.payload(order["order_id"]),
            user=user,
        ),
        receiver=None,
    )
    refund = SimpleNamespace(
        id="recovered",
        amount=-50,
        date=datetime.fromtimestamp(1002, timezone.utc),
        source=None,
        receiver=SimpleNamespace(type="user", user=user),
    )
    monkeypatch.setattr(admin, "panel", AsyncMock())
    bot = AsyncMock()
    bot.get_star_transactions.return_value = SimpleNamespace(transactions=[refund, purchase])
    message = SimpleNamespace(from_user=user, chat=SimpleNamespace(type="private"), answer=AsyncMock())
    await admin.reconcile(message, "", bot)
    assert repository.payment("recovered")["status"] == "refunded"
    assert repository.premium_until(42) == 0
    await admin.reconcile(message, "", bot)
    assert len(repository.payments_for(42)) == 1


async def test_plan_screen_and_payment_history_pagination(client, repository):
    await client.callback("menu:premium")
    assert "ИИ:" in messages(client)[-1] and "Stars" in messages(client)[-1]
    for index in range(6):
        order = repository.create_order(42, "month", 50, 30, now=1000 + index)
        repository.fulfill_order(
            repository.payload(order["order_id"]), 42, "XTR", 50, f"page-charge-{index}", now=1000 + index
        )
    await client.send(".payments 2")
    assert "page-charge-0" in messages(client)[-1]
    assert "page-charge-5" not in messages(client)[-1]
