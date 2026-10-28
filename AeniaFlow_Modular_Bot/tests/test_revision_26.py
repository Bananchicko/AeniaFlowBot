"""Real dispatcher journeys for single identity, stable menus and explicit admin access."""

from dataclasses import replace
from io import BytesIO
import os
import subprocess
import sys
from unittest.mock import AsyncMock

import pytest
from PIL import Image

from aeniaflow.core import access, ffmpeg
from aeniaflow.core.legal_pages import plain_legal, split_pages
from aeniaflow.core.navigation import BASIC_CODES, PAGE_SIZE
from aeniaflow.core.plain_photo import text_photo, layout
from aeniaflow.core.helpers import get_font
from aeniaflow.core.runtime import LEGAL
from aeniaflow.handlers.commands import message_series, COMMANDS
from test_private_revision_22 import connect, incoming
from test_revision_21 import requests, texts


@pytest.mark.parametrize("business_first", [False, True])
async def test_business_mirror_of_own_bot_dm_cannot_send_as_owner(client, business_first):
    await connect(client)
    normal = client.message(text=".menu")
    mirror = incoming(client, ".menu", sender=42, chat=client.bot.id)
    updates = [{"message": normal}, {"business_message": mirror}]
    for update in reversed(updates) if business_first else updates:
        await client.feed(**update)
    sent = requests(client, "sendPhoto")
    assert len(sent) == 1 and sent[0].chat_id == 42
    assert sent[0].business_connection_id is None


@pytest.mark.parametrize("business", [False, True])
async def test_duplicate_delivery_and_business_generated_echo_do_not_execute_again(client, business):
    if business:
        await connect(client)
    message = incoming(client, ".calc 2+2", sender=42) if business else client.message(text=".calc 2+2")
    event = "business_message" if business else "message"
    await client.feed(**{event: message})
    await client.feed(**{event: message})
    echo = dict(
        message,
        message_id=900,
        sender_business_bot={"id": client.bot.id, "is_bot": True, "first_name": "Bot"},
    )
    await client.feed(**{event: echo})
    assert len(requests(client, "sendMessage")) == 1
    assert requests(client, "sendMessage")[0].text == "🧮 <code>4</code>"


@pytest.mark.parametrize("business", [False, True])
async def test_typed_menu_replaces_card_and_other_sections_edit_it(client, business):
    if business:
        await connect(client)
    for command in (".menu", ".profile", ".terms", ".privacy", ".connect", ".menu"):
        if business:
            await client.feed(business_message=incoming(client, command, sender=42))
        else:
            await client.send(command)
    first = requests(client, "sendPhoto")
    edits = requests(client, "editMessageMedia")
    assert len(first) == 2 and len(edits) == 4
    assert {e.message_id for e in edits} == {100}
    assert all(e.business_connection_id == ("business" if business else None) for e in edits)
    assert not requests(client, "sendDocument") and not requests(client, "sendMessage")


async def test_panel_cache_does_not_mix_bot_dm_and_two_business_dialogs(client):
    await connect(client)
    await client.send(".menu")
    for peer in (77, 78):
        await client.feed(business_message=incoming(client, ".menu", sender=42, chat=peer))
    await client.send(".profile")
    for peer in (77, 78):
        await client.feed(business_message=incoming(client, ".profile", sender=42, chat=peer))
    assert [m.chat_id for m in requests(client, "sendPhoto")] == [42, 77, 78]
    assert [(m.chat_id, m.business_connection_id) for m in requests(client, "editMessageMedia")] == [
        (42, None),
        (77, "business"),
        (78, "business"),
    ]


@pytest.mark.parametrize("section,file", [("terms", "terms_of_service.md"), ("privacy", "privacy_policy.md")])
async def test_complete_legal_text_is_paginated_in_original_photo(client, section, file):
    source = plain_legal((LEGAL / file).read_text())
    pages = split_pages(source)
    assert " ".join(" ".join(pages).split()) == " ".join(source.split())
    await client.send(".menu")
    for page in range(len(pages)):
        await client.callback(f"legal:{section}:{page}", mid=100, illustrated=True)
    assert len(requests(client, "sendPhoto")) == 1
    assert len(requests(client, "editMessageMedia")) == len(pages)
    assert not requests(client, "sendDocument")
    from html import unescape
    import re

    for method in requests(client, "editMessageMedia"):
        rendered = unescape(re.sub(r"<[^>]+>", "", method.media.caption))
        assert len(rendered.encode("utf-16-le")) // 2 <= 1024


async def test_connection_instruction_is_visible_before_connection(client):
    await client.send("/start")
    home = requests(client, "sendPhoto")[-1]
    assert "BotFather" not in home.caption
    assert len([b for row in home.reply_markup.inline_keyboard for b in row]) == 3
    await client.callback("menu:connect", mid=100, illustrated=True)
    assert "BotFather" in texts(client)[-1] and "24 часа" in texts(client)[-1]
    await connect(client)
    await client.send(".menu")
    home = requests(client, "sendPhoto")[-1]
    assert len([b for row in home.reply_markup.inline_keyboard for b in row]) == 3


async def test_first_page_has_sixteen_tools_and_mute_series_commands(client):
    assert PAGE_SIZE == 16
    assert {"mute", "unmute", "send"} <= set(BASIC_CODES[:16])
    await client.callback("list:free:0", illustrated=True)
    panel = requests(client, "editMessageMedia")[-1]
    tools = [
        b for row in panel.reply_markup.inline_keyboard for b in row if b.callback_data.startswith("run:")
    ]
    assert len(tools) == 16
    assert all("." + code in panel.media.caption for code in ("mute", "unmute", "send"))


async def test_mute_button_in_business_does_not_delete_menu(client, repository):
    await connect(client)
    await client.callback("run:mute:free:0", chat_id=77, mid=500, illustrated=True, business="business")
    await client.callback("muterun:mute", chat_id=77, mid=500, illustrated=True, business="business")
    assert repository.dialogs(42)[0]["muted"] == 1
    assert all(500 not in m.message_ids for m in requests(client, "deleteBusinessMessages"))
    await client.callback("run:unmute:free:0", chat_id=77, mid=500, illustrated=True, business="business")
    await client.callback("muterun:unmute", chat_id=77, mid=500, illustrated=True, business="business")
    assert repository.dialogs(42)[0]["muted"] == 0


async def test_mute_command_in_bot_dm_opens_chat_selection(client):
    await connect(client)
    await client.feed(business_message=incoming(client))
    await client.send(".mute")
    assert "Ирина" in str(requests(client, "sendPhoto")[-1].reply_markup)
    await client.callback("run:mute:free:0", mid=100, illustrated=True)
    assert ".mute" in texts(client)[-1]
    await client.callback("muterun:mute", mid=100, illustrated=True)
    assert "Ирина" in str(requests(client, "editMessageMedia")[-1].reply_markup)
    assert not requests(client, "restrictChatMember")


@pytest.mark.parametrize("owner", [42, 99])
@pytest.mark.parametrize("business", [False, True])
async def test_both_admins_get_plus_from_buttons_and_commands(client, monkeypatch, owner, business):
    monkeypatch.setattr(access, "settings", replace(access.settings, admin_ids=frozenset({42, 99})))
    handler = AsyncMock()
    monkeypatch.setitem(COMMANDS, "gpt", handler)
    if business:
        await connect(client, owner=owner)
        await client.feed(business_message=incoming(client, ".gpt Тест", sender=owner))
    else:
        await client.send(".gpt Тест", user_id=owner)
    handler.assert_awaited_once()
    await client.callback(
        "run:gpt:plus:0",
        user_id=owner,
        chat_id=77 if business else owner,
        business="business" if business else None,
        illustrated=True,
    )
    assert "Напишите свой вопрос" in texts(client)[-1]
    assert not requests(client, "sendInvoice")


@pytest.mark.parametrize("host", ["", "  "])
def test_blank_host_admin_ids_preserves_both_file_admins(tmp_path, host):
    path = tmp_path / "settings.env"
    path.write_text("ADMIN_IDS=42,99\n")
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from aeniaflow.core.access import has_plus; assert has_plus(42) and has_plus(99); print('OK')",
        ],
        env={**os.environ, "AENIA_ENV_FILE": str(path), "ADMIN_IDS": host},
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0 and result.stdout.strip() == "OK"
    assert path.read_text() == "ADMIN_IDS=42,99\n"


async def test_print_is_clean_photo_and_empty_command_waits_for_text(client):
    await client.send(".print")
    assert not any(hasattr(r.photo, "data") for r in requests(client, "sendPhoto"))
    await client.send("Привет, мир!\nБез рамок и подписей.")
    photo = next(r for r in requests(client, "sendPhoto") if hasattr(r.photo, "data"))
    assert not photo.caption and photo.reply_markup is None
    image = Image.open(BytesIO(photo.photo.data))
    assert image.width == 1280 and image.getpixel((0, 0)) == image.getpixel((50, 50))


def test_print_wraps_long_words_and_rejects_unrenderable_input():
    word = "Оченьдлинноеслово" * 20
    font = get_font(58)
    lines = layout(word, font, 1104)
    assert "".join(lines) == word and all(font.getlength(line) <= 1104 for line in lines)
    assert Image.open(text_photo(word)).height <= 1800
    with pytest.raises(ValueError):
        text_photo("a" * 2001)
    with pytest.raises(ValueError):
        text_photo("а\n" * 100)


@pytest.mark.parametrize("business", [False, True])
@pytest.mark.parametrize(
    "args,expected", [("3 <Привет>", ["<Привет>"] * 3), ("Первое | Второе", ["Первое", "Второе"])]
)
async def test_series_sends_exact_messages_only_in_current_chat(
    client, monkeypatch, business, args, expected
):
    monkeypatch.setattr(message_series, "INTERVAL", 0)
    if business:
        await connect(client)
        await client.feed(business_message=incoming(client, ".send " + args, sender=42))
    else:
        await client.send(".send " + args)
    sent = requests(client, "sendMessage")
    assert [m.text for m in sent] == expected
    assert all(
        m.chat_id == (77 if business else 42)
        and m.business_connection_id == ("business" if business else None)
        for m in sent
    )
    assert not message_series.active


@pytest.mark.parametrize("business", [False, True])
async def test_series_finishes_without_stop_command(client, monkeypatch, business):
    monkeypatch.setattr(message_series, "INTERVAL", 0)
    if business:
        await connect(client)
        await client.feed(business_message=incoming(client, ".send 10 Привет", sender=42))
    else:
        await client.send(".send 10 Привет")
    assert [m.text for m in requests(client, "sendMessage")].count("Привет") == 10
    assert not message_series.active and "stop" not in COMMANDS


@pytest.mark.parametrize("value", ["0 text", "51 text", "3", "one || two", "x" * 1001])
def test_invalid_series_does_not_silently_truncate(value):
    with pytest.raises(ValueError):
        message_series.parse_messages(value)


def test_ffmpeg_custom_path_and_local_binary_precede_system(tmp_path, monkeypatch):
    monkeypatch.setattr(ffmpeg, "BASE_DIR", tmp_path)
    monkeypatch.setattr(ffmpeg.shutil, "which", lambda name: "/usr/bin/ffmpeg")
    monkeypatch.delenv("FFMPEG_PATH", raising=False)
    assert ffmpeg.ffmpeg_binary() == "/usr/bin/ffmpeg"
    (tmp_path / "bin").mkdir()
    local = tmp_path / "bin" / "ffmpeg"
    local.write_text("local executable placeholder")
    local.chmod(0o700)
    assert ffmpeg.ffmpeg_binary() == str(local)
    monkeypatch.setenv("FFMPEG_PATH", "missing-source.tar.xz")
    assert ffmpeg.ffmpeg_binary() is None
    monkeypatch.setenv("FFMPEG_PATH", "bin/ffmpeg")
    assert ffmpeg.ffmpeg_binary() == str(local)
