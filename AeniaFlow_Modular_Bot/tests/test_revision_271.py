"""Use raw Telegram updates: no hidden peer-cache seeding before owner commands."""

import pytest
from aiogram.exceptions import TelegramBadRequest
from aeniaflow.core.runtime import command_seen
from aiogram.types import User
from test_private_revision_22 import connect, connection, incoming
from test_revision_21 import requests, texts


@pytest.mark.parametrize("cached_connection", [True, False])
async def test_first_owner_command_works_without_new_incoming(client, repository, cached_connection):
    if cached_connection:
        await connect(client)
    else:
        client.session.connections["business"] = connection()
    assert repository.peer_type(77) is None
    await client.feed(business_message=incoming(client, ".calc 2+2", sender=42, verified_human=False))
    output = requests(client, "sendMessage")
    assert len(output) == 1
    assert "4" in output[0].text
    assert output[0].chat_id == 77 and output[0].business_connection_id == "business"
    # An owner command cannot establish Telegram's is_bot fact about its recipient.
    assert repository.peer_type(77) is None


@pytest.mark.parametrize(
    "rights,expected", [({"reply": False}, "отвечать"), ({"enabled": False}, "отключено")]
)
async def test_blocked_owner_command_explains_reason_in_owner_bot_dm(client, rights, expected):
    await connect(client, **rights)
    await client.feed(business_message=incoming(client, ".calc 2+2", sender=42, verified_human=False))
    output = requests(client, "sendMessage")
    assert len(output) == 1
    assert expected in output[0].text.lower()
    assert output[0].chat_id == 42 and output[0].business_connection_id is None
    assert not requests(client, "sendPhoto")


async def test_ping_in_bot_dm_does_not_depend_on_photo_or_business_connection(client):
    await client.send(".ping")
    output = requests(client, "sendMessage")
    assert len(output) == 1 and "2.8" in output[0].text
    assert not requests(client, "sendPhoto") and not requests(client, "getBusinessConnection")


@pytest.mark.parametrize("business", [False, True])
async def test_expired_cached_cover_is_reuploaded_instead_of_breaking_every_menu(
    client, monkeypatch, business
):
    if business:
        await connect(client)

    async def send(command):
        if business:
            await client.feed(business_message=incoming(client, command, sender=42))
        else:
            await client.send(command)

    await send(".menu")
    original = client.session.make_request

    async def expired(bot, method, timeout=None):
        if method.__api_method__ == "editMessageMedia" and isinstance(method.media.media, str):
            raise TelegramBadRequest(
                method=method, message="Bad Request: wrong file identifier/HTTP URL specified"
            )
        return await original(bot, method, timeout)

    monkeypatch.setattr(client.session, "make_request", expired)
    command_seen.clear()
    await send(".profile")
    assert requests(client, "editMessageMedia")
    assert "Профиль" in texts(client)[-1]
    assert not requests(client, "sendMessage")


async def test_mute_can_be_first_owner_command_in_existing_dialog(client, repository):
    await connect(client)
    await client.feed(business_message=incoming(client, ".mute", sender=42))
    dialog = repository.dialogs(42)[0]
    assert dialog["muted"] and dialog["chat_id"] == 77
    notices = requests(client, "sendMessage")
    assert {m.chat_id for m in notices} == {42, 77}
    assert requests(client, "deleteBusinessMessages")
    assert repository.peer_type(77) is None
    raw = incoming(client, "hello")
    await client.feed(business_message=raw)
    assert requests(client, "deleteBusinessMessages")[-1].message_ids == [raw["message_id"]]


async def test_no_autoanswer_to_owners_ordinary_text_in_unseen_chat(client, repository):
    await connect(client)
    repository.save_autoreply(42, enabled=True)
    await client.feed(business_message=incoming(client, "Hello", sender=42))
    assert not client.session.requests


@pytest.mark.parametrize(
    "kind", ["bot_user", "bot_username", "generated", "slash", "other_person", "group", "own_bot"]
)
async def test_unseen_peer_fix_does_not_execute_unwanted_commands(client, repository, kind):
    await connect(client)
    raw = incoming(client, ".calc 2+2", sender=42)
    if kind == "bot_user":
        repository.remember_peer(User(id=77, is_bot=True, first_name="Bot"))
    elif kind == "bot_username":
        raw["chat"]["username"] = "SomeOtherBot"
    elif kind == "generated":
        raw["sender_business_bot"] = {"id": 123456, "is_bot": True, "first_name": "Bot"}
    elif kind == "slash":
        raw["text"] = "/start"
    elif kind == "other_person":
        raw["from"]["id"] = 77
    elif kind == "group":
        raw["chat"].update(id=-10077, type="supergroup")
    elif kind == "own_bot":
        raw["chat"]["id"] = 123456
    await client.feed(business_message=raw)
    assert not client.session.requests


async def test_bot_identity_learned_later_blocks_following_commands(client, repository):
    await connect(client)
    raw = incoming(client, "hello")
    raw["from"]["is_bot"] = True
    await client.feed(business_message=raw)
    await client.feed(business_message=incoming(client, ".calc 2+2", sender=42))
    assert repository.peer_type(77) is True
    assert not client.session.requests


async def test_known_human_with_bot_suffix_is_not_blocked(client):
    await connect(client)
    await client.feed(business_message=incoming(client))
    raw = incoming(client, ".calc 2+2", sender=42)
    raw["chat"]["username"] = "HumanBot"
    await client.feed(business_message=raw)
    assert requests(client, "sendMessage")[-1].business_connection_id == "business"


async def test_blocked_commands_notify_only_owner_and_do_not_spam(client):
    await connect(client, reply=False)
    await client.feed(business_message=incoming(client, ".calc 2+2", sender=42))
    await client.feed(business_message=incoming(client, ".calc 3+3", sender=42))
    await client.feed(business_message=incoming(client, "Ordinary message", sender=42))
    await client.feed(business_message=incoming(client, ".calc 2+2"))
    output = requests(client, "sendMessage")
    assert len(output) == 1 and output[0].chat_id == 42
    await connect(client)
    await client.feed(business_message=incoming(client, ".calc 2+2", sender=42))
    assert requests(client, "sendMessage")[-1].business_connection_id == "business"


async def test_paused_dialog_explains_how_to_resume(client, repository):
    await connect(client)
    await client.feed(business_message=incoming(client, "hi", sender=42))
    repository.update_dialog(42, repository.dialogs(42)[0]["id"], "paused", 1)
    await client.feed(business_message=incoming(client, ".calc 2+2", sender=42))
    output = requests(client, "sendMessage")
    assert len(output) == 1 and ".resume" in output[0].text
    assert output[0].chat_id == 42 and output[0].business_connection_id is None
    await client.feed(business_message=incoming(client, ".resume", sender=42))
    assert not repository.dialogs(42)[0]["paused"]


async def test_start_works_when_assets_were_not_copied_to_host(client, monkeypatch, tmp_path):
    from aeniaflow.core import ui

    monkeypatch.setattr(ui, "BASE_DIR", tmp_path)
    await client.send("/start")
    assert not requests(client, "sendPhoto")
    output = requests(client, "sendMessage")
    assert len(output) == 1 and "AeniaFlow" in output[0].text
    assert output[0].reply_markup
    await client.send(".calc 2+2")
    assert requests(client, "sendMessage")[-1].text == "🧮 <code>4</code>"
    await client.callback("menu:profile")
    assert requests(client, "editMessageText")


async def test_business_buttons_work_without_peer_cache(client):
    await connect(client)
    await client.callback("use:coin", chat_id=77, business="business", illustrated=True)
    assert requests(client, "sendMessage")[-1].business_connection_id == "business"


async def test_ping_works_in_existing_business_dialog(client):
    await connect(client)
    await client.feed(business_message=incoming(client, ".ping", sender=42))
    output = requests(client, "sendMessage")
    assert len(output) == 1 and "2.8" in output[0].text
    assert output[0].chat_id == 77 and output[0].business_connection_id == "business"
