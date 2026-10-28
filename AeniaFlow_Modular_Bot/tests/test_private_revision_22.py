import json
import shutil
import subprocess
import time
import wave
from pathlib import Path
from dataclasses import replace
from unittest.mock import AsyncMock
import pytest
from aiogram.types import Chat, User
from aiogram.exceptions import TelegramBadRequest
from aeniaflow.core.database import Database
from aeniaflow.core.runtime import command_seen
from aeniaflow.core import access
from aeniaflow.handlers.commands import msay
from aeniaflow.handlers.system.business import business_message_update
from test_revision_21 import requests, texts


def connection(owner=42, name="business", delete=True, reply=True, enabled=True):
    return {
        "id": name,
        "user": {"id": owner, "is_bot": False, "first_name": "Owner"},
        "user_chat_id": owner,
        "date": int(time.time()),
        "is_enabled": enabled,
        "rights": {"can_reply": reply, "can_delete_all_messages": delete, "can_delete_sent_messages": True},
    }


async def connect(client, owner=42, name="business", **rights):
    raw = connection(owner, name, **rights)
    client.session.connections[name] = raw
    await client.feed(business_connection=raw)


def incoming(client, text="hello", sender=77, chat=77, name="business", verified_human=False, **extra):
    # Do not seed the production database implicitly before receiving an update.
    if verified_human:
        from aeniaflow.core.runtime import db

        db.remember_peer(User(id=chat, is_bot=False, first_name="Peer"))
    return client.message(
        user_id=sender,
        chat_id=chat,
        text=text,
        business_connection_id=name,
        chat={"id": chat, "type": "private", "first_name": "Ирина"},
        **extra,
    )


async def test_current_peer_mute_unmute_without_reply_or_id(client, repository):
    await connect(client)
    await client.feed(business_message=incoming(client, ".mute", sender=42))
    row = repository.dialogs(42)[0]
    assert row["chat_id"] == 77 and row["muted"] == 1
    original = incoming(client)
    await client.feed(business_message=original)
    deletion = requests(client, "deleteBusinessMessages")[-1]
    assert deletion.business_connection_id == "business"
    assert deletion.message_ids == [original["message_id"]]
    # A command from the peer cannot unmute themself.
    await client.feed(business_message=incoming(client, ".unmute"))
    assert repository.dialog(42, row["id"])["muted"] == row["muted"]
    command_seen.clear()
    await client.feed(business_message=incoming(client, ".unmute", sender=42))
    assert repository.dialog(42, row["id"])["muted"] == 0
    count = len(requests(client, "deleteBusinessMessages"))
    await client.feed(business_message=incoming(client))
    assert len(requests(client, "deleteBusinessMessages")) == count
    assert not requests(client, "restrictChatMember")


async def test_mute_is_isolated_by_owner_connection_and_peer(client, repository):
    await connect(client)
    await connect(client, owner=99, name="other")
    await client.feed(business_message=incoming(client, ".mute", sender=42))
    deletions = len(requests(client, "deleteBusinessMessages"))
    await client.feed(business_message=incoming(client, sender=78, chat=78))
    await client.feed(business_message=incoming(client, name="other"))
    assert len(requests(client, "deleteBusinessMessages")) == deletions
    row = repository.dialogs(42)[0]
    muted = next(r for r in repository.dialogs(42) if r["chat_id"] == 77)
    await client.callback(f"dialog:unmute:{muted['id']}", user_id=99)
    assert repository.dialog(42, muted["id"])["muted"] == 1
    assert row["owner_id"] == 42


async def test_mute_blocks_autoreply_and_inline_bot_messages(client, repository):
    await connect(client)
    repository.save_autoreply(42, enabled=True)
    await client.feed(business_message=incoming(client, ".mute", sender=42))
    before = len(requests(client, "sendMessage"))
    await client.feed(
        business_message=incoming(client, via_bot={"id": 555, "is_bot": True, "first_name": "Inline"})
    )
    assert requests(client, "deleteBusinessMessages")
    assert len(requests(client, "sendMessage")) == before


@pytest.mark.parametrize("enabled,delete", [(False, True), (True, False)])
async def test_mute_checks_actual_rights_before_enabling(client, repository, enabled, delete):
    await connect(client)
    client.session.connections["business"] = connection(enabled=enabled, delete=delete)
    await client.feed(business_message=incoming(client, ".mute", sender=42))
    assert repository.dialogs(42)[0]["muted"] == 0
    assert "включён" not in " ".join(texts(client))


async def test_turning_off_stops_deleting_and_resumes_autoreply(client, repository):
    await connect(client)
    await client.feed(business_message=incoming(client))
    row = repository.dialogs(42)[0]
    repository.set_private_mute(42, row["id"], False)
    repository.save_autoreply(42, enabled=True, reply_text="Привет")
    await client.feed(business_message=incoming(client))
    assert not requests(client, "deleteBusinessMessages")
    assert requests(client, "sendMessage")[-1].text == "Привет"


async def test_rights_revoked_shows_error_and_notifies_owner_once(client, repository):
    await connect(client)
    await client.feed(business_message=incoming(client, ".mute", sender=42))
    await connect(client, delete=False)
    deletions = len(requests(client, "deleteBusinessMessages"))
    count = len(requests(client, "sendMessage"))
    await client.feed(business_message=incoming(client))
    await client.feed(business_message=incoming(client))
    assert len(requests(client, "deleteBusinessMessages")) == deletions
    notices = requests(client, "sendMessage")[count:]
    assert len(notices) == 1 and notices[0].chat_id == 42
    assert notices[0].business_connection_id is None
    row = repository.dialogs(42)[0]
    assert row["mute_error"]
    await connect(client)
    await client.feed(business_message=incoming(client))
    assert requests(client, "deleteBusinessMessages")
    assert not repository.dialog(42, row["id"])["mute_error"]


async def test_mute_works_with_delete_right_but_without_reply_right(client, repository):
    await connect(client)
    await client.feed(business_message=incoming(client))
    row = repository.dialogs(42)[0]
    repository.set_private_mute(42, row["id"], True)
    await connect(client, reply=False)
    await client.feed(business_message=incoming(client))
    assert requests(client, "deleteBusinessMessages")


async def test_telegram_delete_error_does_not_pretend_success(client, repository):
    from aiogram.methods import DeleteBusinessMessages
    from aiogram.types import Message

    await connect(client)
    await client.feed(business_message=incoming(client, ".mute", sender=42))
    bot = AsyncMock()
    from types import SimpleNamespace

    bot.get_chat_member.return_value = SimpleNamespace(status="member")
    bot.delete_business_messages.side_effect = TelegramBadRequest(
        method=DeleteBusinessMessages(business_connection_id="business", message_ids=[1]),
        message="not allowed",
    )
    await business_message_update(Message.model_validate(incoming(client)), bot)
    assert "отклонил" in repository.dialogs(42)[0]["mute_error"]
    bot.send_message.assert_awaited_once()
    assert bot.send_message.await_args.args[0] == 42


async def test_dialog_buttons_choose_peer_and_mute_without_typed_id(client, repository):
    await connect(client)
    await client.feed(business_message=incoming(client))
    row = repository.dialogs(42)[0]
    await client.callback("menu:chats", illustrated=True)
    panel = requests(client, "editMessageMedia")[-1]
    buttons = [b for line in panel.reply_markup.inline_keyboard for b in line]
    assert any(b.text == "Ирина" for b in buttons)
    await client.callback(f"dialog:open:{row['id']}", illustrated=True)
    await client.callback(f"dialog:mute:{row['id']}", illustrated=True)
    assert repository.dialog(42, row["id"])["muted"] == 1
    await client.callback(f"dialog:unmute:{row['id']}", illustrated=True)
    assert repository.dialog(42, row["id"])["muted"] == 0


async def test_groups_are_ignored_and_not_registered_as_users(client, repository):
    for text in (".mute", ".calc 2+2", "/start"):
        await client.send(text, chat_id=-1001)
    assert not client.session.requests
    assert repository.get_user(42) is None
    await client.callback("menu:chats", chat_id=-1001)
    assert [r.__api_method__ for r in client.session.requests] == ["answerCallbackQuery"]


async def test_afk_replies_in_private_business_chat(client, repository):
    await connect(client)
    await client.send(".afk На встрече")
    await client.feed(business_message=incoming(client))
    response = requests(client, "sendMessage")[-1]
    assert "На встрече" in response.text and response.business_connection_id == "business"
    await client.send(".afk off")
    assert not repository.get_user(42)["afk_reason"]


async def test_panic_only_deletes_current_known_private_history(client, repository, monkeypatch):
    monkeypatch.setattr(access, "settings", replace(access.settings, admin_ids=frozenset({42})))
    await connect(client)
    unrelated = incoming(client, sender=78, chat=78)
    await client.feed(business_message=unrelated)
    seen = incoming(client)
    await client.feed(business_message=seen)
    await client.feed(business_message=incoming(client, ".panic 2", sender=42))
    deletion = requests(client, "deleteBusinessMessages")[-1]
    assert len(deletion.message_ids) == 2
    assert seen["message_id"] in deletion.message_ids
    assert unrelated["message_id"] not in deletion.message_ids


def test_private_migration_preserves_paid_access_and_restart_state(tmp_path):
    path = tmp_path / "upgrade.sqlite3"
    old = Database(str(path))
    old.upsert_user(User(id=42, first_name="Owner", is_bot=False))
    order = old.create_order(42, "month", 50, 30)
    old.fulfill_order(old.payload(order["order_id"]), 42, "XTR", 50, "charge")
    expiry = old.premium_until(42)
    # Reproduce the version-2 table shape, with a real paid entitlement.
    old.conn.execute("DROP TABLE private_messages")
    old.conn.execute("DROP TABLE private_dialogs")
    for column in ("can_delete_all_messages", "can_delete_sent_messages", "user_chat_id"):
        old.conn.execute(f"ALTER TABLE business_connections DROP COLUMN {column}")
    for column in ("watermark_style", "watermark_position", "watermark_opacity"):
        old.conn.execute(f"ALTER TABLE users DROP COLUMN {column}")
    old.conn.execute("PRAGMA user_version=2")
    old.close()
    current = Database(str(path))
    assert current.conn.execute("PRAGMA user_version").fetchone()[0] == 8
    assert current.premium_until(42) == expiry
    assert len(list(tmp_path.glob("*.pre-v3-*.bak"))) == 1
    row = current.remember_dialog(42, "business", Chat(id=77, type="private", first_name="Ирина"), 5)
    current.set_private_mute(42, row["id"], True)
    current.close()
    reopened = Database(str(path))
    assert reopened.dialog(42, row["id"])["muted"] == 1
    assert reopened.premium_until(42) == expiry
    assert len(list(tmp_path.glob("*.pre-v3-*.bak"))) == 1
    assert reopened.export_user(42)["private_dialogs"]
    reopened.clear_personal_data(42)
    assert not reopened.dialogs(42)
    assert reopened.conn.execute("SELECT COUNT(*) FROM private_messages").fetchone()[0] == 0
    assert reopened.premium_until(42) == expiry
    reopened.close()


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg unavailable")
@pytest.mark.parametrize("business", [False, True])
async def test_msay_sends_real_ogg_opus_voice_through_dispatcher(client, monkeypatch, tmp_path, business):
    import gtts

    paths = []

    class Speech:
        def __init__(self, text, lang, timeout):
            assert text == "Привет!" and lang == "ru"

        def save(self, path):
            paths.append(Path(path))
            # Valid local audio substitutes only the external TTS call.
            with wave.open(path, "wb") as out:
                out.setparams((1, 2, 24000, 24000, "NONE", "not compressed"))
                out.writeframes(b"\0\0" * 24000)

    monkeypatch.setattr(gtts, "gTTS", Speech)
    original = client.session.make_request
    captured = tmp_path / "voice.ogg"

    async def record(bot, method, timeout=None):
        if method.__api_method__ == "sendVoice":
            captured.write_bytes(Path(method.voice.path).read_bytes())
        return await original(bot, method, timeout)

    monkeypatch.setattr(client.session, "make_request", record)
    if business:
        await connect(client)
        await client.feed(business_message=incoming(client, ".msay Привет!", sender=42))
    else:
        await client.send(".msay Привет!")
    voice = requests(client, "sendVoice")
    assert len(voice) == 1
    assert voice[0].business_connection_id == ("business" if business else None)
    assert voice[0].chat_id == (77 if business else 42)
    assert not any(requests(client, name) for name in ("sendAudio", "sendVideo", "sendDocument"))
    assert captured.read_bytes().startswith(b"OggS")
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(captured)],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert json.loads(probe.stdout)["streams"][0]["codec_name"] == "opus"
    assert all(not path.parent.exists() for path in paths)


async def test_msay_missing_ffmpeg_reports_setup_without_fake_media(client, monkeypatch):
    monkeypatch.setattr(msay, "ffmpeg_binary", lambda: None)
    await client.send(".msay Привет")
    assert "FFmpeg" in texts(client)[-1]
    assert not requests(client, "sendVoice") and not requests(client, "sendAudio")


async def test_msay_failed_synthesis_cleans_up_and_reports_error(client, monkeypatch):
    import gtts

    paths = []

    class Broken:
        def __init__(self, *args, **kwargs):
            pass

        def save(self, path):
            paths.append(Path(path))
            Path(path).write_bytes(b"incomplete")
            raise OSError("network unavailable")

    monkeypatch.setattr(gtts, "gTTS", Broken)
    monkeypatch.setattr(msay, "ffmpeg_binary", lambda: "/fake/ffmpeg")
    await client.send(".msay Привет")
    assert "Сервис озвучки недоступен" in texts(client)[-1]
    assert all(not p.parent.exists() for p in paths)
    assert not requests(client, "sendVoice")


async def test_illustrated_media_button_never_processes_banner(client, monkeypatch):
    from aeniaflow.handlers.commands import blur

    monkeypatch.setattr(access, "settings", replace(access.settings, admin_ids=frozenset({42})))
    download = AsyncMock()
    monkeypatch.setattr(blur, "download_file", download)
    await client.callback("use:blur", illustrated=True)
    download.assert_not_awaited()
    assert "Отправьте фото" in texts(client)[-1]


async def test_three_real_banners_and_native_styles(client):
    await client.send("/start")
    home = requests(client, "sendPhoto")[-1]
    assert Path(home.photo.path).name == "home.png"
    assert any(b.style == "primary" for line in home.reply_markup.inline_keyboard for b in line)
    await client.callback("menu:chats", illustrated=True)
    assert Path(requests(client, "editMessageMedia")[-1].media.media.path).name == "dialogs.png"
    await client.callback("menu:premium", illustrated=True)
    assert Path(requests(client, "editMessageMedia")[-1].media.media.path).name == "plus.png"
    assert all(
        "групп" not in b.text.lower()
        for r in client.session.requests
        if getattr(r, "reply_markup", None)
        for line in r.reply_markup.inline_keyboard
        for b in line
    )


async def test_existing_business_connection_recovers_on_fresh_install(client, repository):
    client.session.connections["business"] = connection()
    await client.feed(business_message=incoming(client, ".calc 6*7", sender=42))
    assert repository.connection_owner("business")["owner_id"] == 42
    result = requests(client, "sendMessage")[-1]
    assert "42" in result.text and result.business_connection_id == "business"


async def test_long_autoreply_uses_text_and_returns_to_illustrated_menu(client, repository):
    await connect(client)
    repository.save_autoreply(42, reply_text="Я" * 1000)
    await client.callback("menu:autoreply", illustrated=True)
    stored = json.loads(repository.load_panel(client.bot.id, None, 42)["pages"])
    assert stored["text"].count("Я") == 1000
    assert not requests(client, "sendMessage") and not requests(client, "deleteMessage")
    await client.callback("panelpage:1", illustrated=True)
    await client.callback("menu:home", illustrated=True)
    assert requests(client, "editMessageMedia")


async def test_rejected_voice_upload_cleans_temporary_files(client, monkeypatch):
    import gtts
    from aiogram.methods import SendVoice

    paths = []

    class Speech:
        def __init__(self, *args, **kwargs):
            pass

        def save(self, path):
            paths.append(Path(path))
            Path(path).write_bytes(b"input")

    monkeypatch.setattr(gtts, "gTTS", Speech)
    monkeypatch.setattr(msay, "ffmpeg_binary", lambda: "/fake/ffmpeg")

    def convert(args):
        Path(args[-1]).write_bytes(b"OggS-fake")
        return True, ""

    monkeypatch.setattr(msay, "run_ffmpeg", convert)
    original = client.session.make_request

    async def reject(bot, method, timeout=None):
        if isinstance(method, SendVoice):
            raise TelegramBadRequest(method=method, message="VOICE_MESSAGES_FORBIDDEN")
        return await original(bot, method, timeout)

    monkeypatch.setattr(client.session, "make_request", reject)
    await client.send(".msay Привет")
    assert "запретил голосовые" in texts(client)[-1]
    assert all(not p.parent.exists() for p in paths)
    assert not requests(client, "sendAudio")
