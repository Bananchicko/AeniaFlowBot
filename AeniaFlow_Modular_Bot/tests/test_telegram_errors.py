"""Regression tests for the common channel gate and diagnostics in both private contexts."""

from dataclasses import replace
import logging
from unittest.mock import AsyncMock

import pytest
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
)
from aiogram.methods import GetChatMember, SendMessage, SendVoice
from aiogram.types import ChatMemberLeft, User

from aeniaflow.core import access, telegram_errors
from aeniaflow.handlers.system import command_dispatcher, sections
from main import RedactCredentials
from test_private_revision_22 import connect, incoming
from test_revision_21 import requests, texts


@pytest.fixture
def channel(monkeypatch):
    configured = replace(sections.settings, news_channel="@ChannelTest", admin_ids=frozenset())
    for module in (sections, command_dispatcher, access):
        monkeypatch.setattr(module, "settings", configured)
    return configured


async def send_command(client, business, command):
    if business:
        await client.feed(business_message=incoming(client, command, sender=42))
    else:
        await client.send(command)


@pytest.mark.parametrize("business", [False, True])
@pytest.mark.parametrize("command", ["calc", "msay"])
@pytest.mark.parametrize("error", [TelegramBadRequest, TelegramForbiddenError])
async def test_channel_denial_is_identified_before_command(
    client, monkeypatch, channel, business, command, error
):
    if business:
        await connect(client)
    handler = AsyncMock()
    monkeypatch.setitem(command_dispatcher.COMMANDS, command, handler)
    original = client.session.make_request

    async def denied(bot, method, timeout=None):
        if method.__api_method__ == "getChatMember":
            client.session.requests.append(method)
            raise error(method=method, message="Bad Request: chat not found")
        return await original(bot, method, timeout)

    monkeypatch.setattr(client.session, "make_request", denied)
    await send_command(client, business, f".{command} тест")
    handler.assert_not_awaited()
    answer = requests(client, "sendMessage")[-1]
    assert "getChatMember" in answer.text and "chat not found" in answer.text
    assert "NEWS_CHANNEL" in answer.text and "администратором" in answer.text
    assert answer.chat_id == (77 if business else 42)
    assert answer.business_connection_id == ("business" if business else None)
    assert not requests(client, "sendVoice")


@pytest.mark.parametrize("business", [False, True])
async def test_membership_button_reports_same_error(client, monkeypatch, channel, business):
    if business:
        await connect(client)
    original = client.session.make_request

    async def denied(bot, method, timeout=None):
        if method.__api_method__ == "getChatMember":
            raise TelegramBadRequest(method=method, message="member list is inaccessible")
        return await original(bot, method, timeout)

    monkeypatch.setattr(client.session, "make_request", denied)
    await client.callback(
        "sub:check", chat_id=77 if business else 42, business="business" if business else None
    )
    answer = requests(client, "sendMessage")[-1]
    assert "getChatMember" in answer.text and "member list is inaccessible" in answer.text
    assert answer.business_connection_id == ("business" if business else None)
    alerts = requests(client, "answerCallbackQuery")
    assert any("getChatMember" in (a.text or "") for a in alerts)


async def test_nonmember_does_not_bypass_subscription_gate(client, monkeypatch, channel):
    handler = AsyncMock()
    monkeypatch.setitem(command_dispatcher.COMMANDS, "calc", handler)
    original = client.session.make_request

    async def left(bot, method, timeout=None):
        if method.__api_method__ == "getChatMember":
            return ChatMemberLeft(user=User(id=42, is_bot=False, first_name="User"))
        return await original(bot, method, timeout)

    monkeypatch.setattr(client.session, "make_request", left)
    await client.send(".calc 2+2")
    handler.assert_not_awaited()
    assert "Подпишитесь" in " ".join(texts(client))


async def test_admin_keeps_plus_and_bypasses_channel_check(client, monkeypatch, channel):
    monkeypatch.setattr(access, "settings", replace(channel, admin_ids=frozenset({42})))
    handler = AsyncMock()
    monkeypatch.setitem(command_dispatcher.COMMANDS, "calc", handler)
    await client.send(".calc 2+2")
    handler.assert_awaited_once()
    assert not requests(client, "getChatMember")
    assert access.has_plus(42)


@pytest.mark.parametrize("business", [False, True])
async def test_send_error_keeps_method_and_context(client, monkeypatch, business):
    if business:
        await connect(client)
    original = client.session.make_request
    failed = False

    async def reject_once(bot, method, timeout=None):
        nonlocal failed
        if method.__api_method__ == "sendMessage" and not failed:
            failed = True
            raise TelegramForbiddenError(method=method, message="Forbidden: BOT_ACCESS_FORBIDDEN")
        return await original(bot, method, timeout)

    monkeypatch.setattr(client.session, "make_request", reject_once)
    await send_command(client, business, ".calc 2+2")
    answer = requests(client, "sendMessage")[-1]
    assert "sendMessage" in answer.text and "BOT_ACCESS_FORBIDDEN" in answer.text
    assert answer.chat_id == (77 if business else 42)
    if business:
        assert "24 часа" in answer.text and "приостановлен" in answer.text


@pytest.mark.parametrize("owner_available", [True, False])
async def test_undeliverable_business_error_falls_back_only_to_owner(
    client, monkeypatch, owner_available, caplog
):
    await connect(client)
    original = client.session.make_request
    attempts = []

    async def denied(bot, method, timeout=None):
        if method.__api_method__ in {"sendMessage", "sendPhoto"}:
            attempts.append(method)
            if method.business_connection_id or not owner_available:
                raise TelegramForbiddenError(method=method, message="Forbidden: BOT_ACCESS_FORBIDDEN")
        return await original(bot, method, timeout)

    monkeypatch.setattr(client.session, "make_request", denied)
    await send_command(client, True, ".calc 2+2")
    assert [m.chat_id for m in attempts] == [77, 77, 42]
    assert attempts[-1].business_connection_id is None
    assert "sendMessage" in attempts[-1].text
    assert "Telegram request failed" in caplog.text


async def test_business_mute_rights_request_error_is_not_hidden(client, monkeypatch, repository):
    await connect(client)
    original = client.session.make_request

    async def denied(bot, method, timeout=None):
        if method.__api_method__ == "getBusinessConnection":
            raise TelegramBadRequest(method=method, message="BUSINESS_CONNECTION_INVALID")
        return await original(bot, method, timeout)

    monkeypatch.setattr(client.session, "make_request", denied)
    await send_command(client, True, ".mute")
    assert "getBusinessConnection" in texts(client)[-1]
    assert "BUSINESS_CONNECTION_INVALID" in texts(client)[-1]
    assert repository.dialogs(42)[0]["muted"] == 0


@pytest.mark.parametrize("error", [TelegramBadRequest, TelegramForbiddenError])
def test_voice_privacy_error_has_voice_specific_hint(error):
    exc = error(
        method=SendVoice(chat_id=77, voice="file", business_connection_id="business"),
        message="VOICE_MESSAGES_FORBIDDEN",
    )
    assert "запретил голосовые" in telegram_errors.error_text(exc)
    assert "sendVoice" in telegram_errors.error_text(exc)


@pytest.mark.parametrize("error", [TelegramNetworkError, TelegramRetryAfter])
def test_network_and_rate_limits_are_not_misreported_as_channel_permissions(error):
    kwargs = {"retry_after": 11} if error is TelegramRetryAfter else {}
    exc = error(method=GetChatMember(chat_id="@ChannelTest", user_id=42), message="unavailable", **kwargs)
    text = telegram_errors.error_text(exc)
    assert "администратором" not in text
    assert ("11 сек" if kwargs else "api.telegram.org") in text


def test_diagnostics_escape_html_redact_secrets_and_never_include_request_body(monkeypatch, caplog):
    configured = replace(
        telegram_errors.settings, bot_token="test-token-secret", openai_api_key="test-ai-secret"
    )
    monkeypatch.setattr(telegram_errors, "settings", configured)
    token_pattern = "123456:" + "Z" * 35
    key_pattern = "sk-proj-" + "Z" * 50
    exc = TelegramBadRequest(
        method=SendMessage(chat_id=42, text="PRIVATE REQUEST BODY"),
        message=f"<invalid> & {configured.bot_token} {configured.openai_api_key} {token_pattern} {key_pattern}",
    )
    text = telegram_errors.error_text(exc)
    telegram_errors.log_error(exc)
    assert "&lt;invalid&gt; &amp;" in text
    for value in (
        configured.bot_token,
        configured.openai_api_key,
        token_pattern,
        key_pattern,
        "PRIVATE REQUEST BODY",
    ):
        assert value not in text and value not in caplog.text
    assert "[REDACTED]" in text and "sendMessage" in caplog.text


def test_log_filter_redacts_exception_traceback(monkeypatch):
    monkeypatch.setattr(
        telegram_errors, "settings", replace(telegram_errors.settings, bot_token="unique-credential")
    )
    try:
        raise RuntimeError("upstream unique-credential")
    except RuntimeError:
        import sys

        record = logging.LogRecord(
            "test", logging.ERROR, "test", 1, "Failed unique-credential", (), sys.exc_info()
        )
    RedactCredentials().filter(record)
    rendered = logging.Formatter().format(record)
    assert "unique-credential" not in rendered
    assert "RuntimeError" in rendered and "[REDACTED]" in rendered
