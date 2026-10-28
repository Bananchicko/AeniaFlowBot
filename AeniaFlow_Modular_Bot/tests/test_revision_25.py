"""Exercise actual command handlers in both private contexts, replacing external services only."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
import importlib
import itertools
import json
import shutil
import subprocess
import time
import wave

import pytest
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.types import User, Message
from PIL import Image
from aeniaflow.catalog import FEATURES
from aeniaflow.core import access, ai_service
from aeniaflow.core.command_help import EXAMPLES
from aeniaflow.core.database import Database
from aeniaflow.core.inputs import MEDIA_COMMANDS
from aeniaflow.core.runtime import command_seen
from aeniaflow.core.scheduling import deliver_due
from aeniaflow.handlers.system.command_dispatcher import incoming_message
from test_private_revision_22 import connect, incoming
from test_revision_21 import requests, texts


@pytest.fixture(scope="session")
def sample_media(tmp_path_factory):
    folder = tmp_path_factory.mktemp("media-v25")
    image = folder / "photo.png"
    Image.new("RGB", (320, 180), "orange").save(image)
    audio = folder / "audio.wav"
    with wave.open(str(audio), "wb") as out:
        out.setparams((1, 2, 24000, 24000, "NONE", "not compressed"))
        out.writeframes(b"\0\0" * 24000)
    video = folder / "video.mp4"
    if not shutil.which("ffmpeg"):
        pytest.skip("FFmpeg required for media integration matrix")
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=160x120:d=1",
            "-i",
            str(audio),
            "-shortest",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(video),
        ],
        check=True,
        timeout=30,
    )
    return {"photo-fixture": image, "audio-fixture": audio, "video-fixture": video}


@pytest.fixture
def offline_services(monkeypatch, tmp_path, sample_media):
    import gtts

    monkeypatch.setattr(access, "settings", replace(access.settings, admin_ids=frozenset({42, 99})))
    monkeypatch.setattr(
        ai_service, "settings", replace(ai_service.settings, openai_api_key="offline-fixture")
    )
    client = AsyncMock()
    client.responses.create.return_value = SimpleNamespace(output_text="Тестовый ответ ИИ")
    client.audio.transcriptions.create.return_value = SimpleNamespace(text="Распознанный текст")
    manager = AsyncMock()
    manager.__aenter__.return_value = client
    monkeypatch.setattr(ai_service, "AsyncOpenAI", lambda **kwargs: manager)

    class Speech:
        def __init__(self, *args, **kwargs):
            pass

        def save(self, path):
            shutil.copyfile(sample_media["audio-fixture"], path)

    monkeypatch.setattr(gtts, "gTTS", Speech)
    from aeniaflow.handlers.commands import message_series

    monkeypatch.setattr(message_series, "INTERVAL", 0)
    counter = itertools.count()
    copied = []

    async def download(bot, file_id, suffix=".bin"):
        output = tmp_path / f"input-{next(counter)}{suffix}"
        shutil.copyfile(sample_media[file_id], output)
        copied.append(output)
        return str(output)

    for name in ("media_tools", "meme", "blur", "wm", "stt"):
        module = importlib.import_module("aeniaflow.handlers.commands." + name)
        monkeypatch.setattr(module, "download_file", download)
    return SimpleNamespace(ai=client, downloaded=copied)


def attachment(code):
    if code not in MEDIA_COMMANDS:
        return {}
    kind = MEDIA_COMMANDS[code]
    if kind in {"photo", "any"}:
        return {"photo": [{"file_id": "photo-fixture", "file_unique_id": "p", "width": 320, "height": 180}]}
    if kind == "audio" or code == "voice":
        return {"audio": {"file_id": "audio-fixture", "file_unique_id": "a", "duration": 1}}
    return {
        "video": {
            "file_id": "video-fixture",
            "file_unique_id": "v",
            "width": 160,
            "height": 120,
            "duration": 1,
        }
    }


EXPECTED_METHOD = {
    "ref": "sendPhoto",
    "x": "sendPhoto",
    "chatinfo": "sendPhoto",
    "send": "sendMessage",
    "reply": "sendMessage",
    "mute": "sendMessage",
    "unmute": "sendMessage",
    **{
        code: "sendPhoto"
        for code in (
            "chats",
            "mutelist",
            "watermark",
            "profile",
            "settings",
            "organizer",
            "payments",
            "print",
            "circle",
            "meme",
            "blur",
            "save",
        )
    },
    **{code: "sendDocument" for code in ("wm", "resize", "rotate", "mirror", "export")},
    "gif": "sendAnimation",
    "msay": "sendVoice",
    "voice": "sendVoice",
    "speed": "sendVideo",
    "audio": "sendAudio",
    "videonote": "sendVideoNote",
    "dice": "sendDice",
    "poll": "sendPoll",
}

CASES = [
    (code, business)
    for code in FEATURES
    for business in (False, True)
    if business or code not in {"mute", "unmute", "panic"}
]


@pytest.mark.parametrize("code,business", CASES, ids=[f"{c}-{'business' if b else 'bot'}" for c, b in CASES])
async def test_all_advertised_commands_execute_in_the_requested_private_context(
    client, repository, offline_services, code, business
):
    user = User(id=42, is_bot=False, first_name="Owner")
    repository.upsert_user(user)
    if business:
        await connect(client)
        await client.feed(business_message=incoming(client, "Сообщение собеседника"))
    repository.save_reply(42, "привет", "Привет!")
    if business:
        client.session.connections["business"]["rights"]["can_read_messages"] = True
    repository.save_note(42, "Идея", "Текст заметки")
    repository.add_task(42, "Задача")
    repository.add_reminder(42, 42, "Личное напоминание", int(time.time()) + 3600)
    chat_id = 77 if business else 42
    connection_id = "business" if business else None
    repository.save_game(
        "word", chat_id, 42, {"answer": "лампа", "turns": 0, "business_connection_id": connection_id}
    )
    if code == "unmute":
        repository.set_private_mute(42, repository.dialogs(42)[0]["id"], True)
    command = ".export CONFIRM" if business and code == "export" else EXAMPLES[code]
    if code == "words":
        command = ".words Привет"
    media = attachment(code)
    raw = incoming(client, command, sender=42) if business else client.message(text=command)
    if media:
        raw.pop("text")
        raw.update(media, caption=command)
    before = len(client.session.requests)
    await client.feed(**{"business_message" if business else "message": raw})
    from aeniaflow.handlers.commands.dialog_tools import DIALOG_COMMANDS

    method = (
        "sendPhoto" if not business and code in DIALOG_COMMANDS else EXPECTED_METHOD.get(code, "sendMessage")
    )
    if business and code == "ref":
        method = "sendMessage"
    sent = [r for r in client.session.requests[before:] if r.__api_method__ == method]
    target = [r for r in sent if r.chat_id == chat_id]
    assert target, (code, texts(client))
    assert all(getattr(r, "business_connection_id", None) == connection_id for r in target)
    all_text = "\n".join(texts(client))
    assert not any(
        fragment in all_text
        for fragment in (
            "Не удалось",
            "Команда не найдена",
            "Действие доступно владельцу",
            "Личные разделы и настройки открываются",
            "Формат:",
            "Нужно русское слово",
            "Напишите команду в личном диалоге",
            "входит в AeniaFlow+",
        )
    ), (code, all_text)
    assert all(not path.exists() for path in offline_services.downloaded)
    if code in {"timer", "remind"}:
        row = repository.reminders(42)[0]
        assert row["chat_id"] == chat_id and row["business_connection_id"] == connection_id
    if code in {"mute", "unmute"}:
        assert bool(repository.dialogs(42)[0]["muted"]) == (code == "mute")
    if code in {"gpt", "hint", "fix", "tr", "rewrite", "summarize", "explain"}:
        offline_services.ai.responses.create.assert_awaited_once()
    if code == "stt":
        offline_services.ai.audio.transcriptions.create.assert_awaited_once()


@pytest.mark.parametrize(
    "code", ["menu", "help", "free", "plus", "premium", "connect", "terms", "privacy", "paysupport"]
)
async def test_service_commands_open_inside_business(client, code):
    await connect(client)
    await client.feed(business_message=incoming(client, f".{code}", sender=42))
    sent = [
        r for r in client.session.requests if r.__api_method__ in {"sendPhoto", "sendMessage", "sendDocument"}
    ]
    assert sent and all(r.chat_id == 77 and r.business_connection_id == "business" for r in sent)
    body = " ".join(texts(client))
    if code not in {"terms", "privacy"}:
        assert "Команда:" in body


async def test_business_menu_input_keeps_actor_chat_and_back_page(client, repository):
    await connect(client)
    await client.callback("run:note:free:1", chat_id=77, business="business", illustrated=True)
    prompt = requests(client, "editMessageMedia")[-1]
    assert ".note add" in prompt.media.caption
    assert prompt.business_connection_id == "business" and prompt.chat_id == 77
    await client.feed(business_message=incoming(client, "Идея | Текст из ЛС", sender=42))
    assert repository.notes(42)[0]["body"] == "Текст из ЛС"
    assert not repository.notes(77)
    await client.callback("run:note:free:1", chat_id=77, business="business", illustrated=True)
    await client.callback("list:free:1", chat_id=77, business="business", illustrated=True)
    await client.feed(business_message=incoming(client, "Другое | Не сохранять", sender=42))
    assert len(repository.notes(42)) == 1


async def test_business_settings_notes_and_task_buttons_work_for_owner_only(client, repository):
    await connect(client)
    note = repository.save_note(42, "Заметка", "Личный текст")
    task = repository.add_task(42, "Проверить")
    for data in (
        "menu:profile",
        "menu:settings",
        "tz:Europe/Moscow",
        "wmset:opacity:40",
        "auto:on",
        f"note:open:42:{note}:0",
        f"task:done:42:{task}",
    ):
        await client.callback(data, chat_id=77, business="business", illustrated=True)
    assert repository.get_user(42)["timezone"] == "Europe/Moscow"
    assert repository.get_user(42)["watermark_opacity"] == 40
    assert repository.get_autoreply(42)["enabled"]
    assert repository.tasks(42)[0]["done"]
    before = len(client.session.requests)
    for data in (
        "menu:notes",
        "tz:UTC",
        "wmset:opacity:70",
        "auto:off",
        f"note:delete:42:{note}:0",
        f"task:undo:42:{task}",
        "nav:page",
    ):
        await client.callback(data, user_id=77, chat_id=77, business="business", illustrated=True)
    assert all(r.__api_method__ == "answerCallbackQuery" for r in client.session.requests[before:])
    assert repository.note(42, note) and repository.tasks(42)[0]["done"]
    assert repository.get_user(42)["timezone"] == "Europe/Moscow"


async def test_peer_and_forged_message_cannot_run_personal_business_commands(client, repository):
    await connect(client)
    for command in (
        ".note add Чужое | Текст",
        ".todo add Чужое",
        ".clock Europe/Moscow",
        ".delete_data CONFIRM",
        ".export CONFIRM",
    ):
        await client.feed(business_message=incoming(client, command))
        # Also exercise the inner dispatcher directly; it must not rely only on the outer router.
        forged = Message.model_validate(incoming(client, command)).as_(client.bot)
        await incoming_message(forged, client.bot)
    assert not repository.notes(77) and not repository.tasks(77)
    assert not requests(client, "sendDocument") and not requests(client, "sendMessage")


async def test_media_pending_isolated_between_owner_dialogs_and_bot(client, monkeypatch):
    from aeniaflow.handlers.commands import media_tools

    await connect(client)
    download = AsyncMock()
    monkeypatch.setattr(media_tools, "download_file", download)
    await client.callback("run:mirror:free:1", chat_id=77, business="business", illustrated=True)
    for raw, key in [
        (client.message(**attachment("mirror")), "message"),
        (incoming(client, None, sender=42, chat=88, **attachment("mirror")), "business_message"),
    ]:
        await client.feed(**{key: raw})
    download.assert_not_awaited()
    await client.callback("menu:home", chat_id=77, business="business", illustrated=True)
    await client.feed(business_message=incoming(client, None, sender=42, **attachment("mirror")))
    download.assert_not_awaited()


@pytest.mark.parametrize("command", [".timer 1s", ".remind 1s Проверить", ".remind every 1m Повтор"])
async def test_business_reminders_deliver_through_saved_connection(client, repository, command):
    await connect(client)
    await client.feed(business_message=incoming(client, command, sender=42))
    row = repository.reminders(42)[0]
    assert row["business_connection_id"] == "business" and row["chat_id"] == 77
    await deliver_due(client.bot, now=row["due_at"])
    sent = requests(client, "sendMessage")[-1]
    assert sent.chat_id == 77 and sent.business_connection_id == "business"
    assert sent.parse_mode is None and "Напоминание" in sent.text
    if row["interval_seconds"]:
        assert repository.reminders(42)[0]["due_at"] == row["due_at"] + 60


@pytest.mark.parametrize("failure", ["disconnect", "owner_changed", "telegram_rejected"])
async def test_unavailable_business_reminder_falls_back_only_to_its_owner(
    client, repository, monkeypatch, failure
):
    await connect(client)
    await client.feed(business_message=incoming(client, ".remind 1s Приватный текст", sender=42))
    row = repository.reminders(42)[0]
    if failure == "disconnect":
        await connect(client, enabled=False)
    elif failure == "owner_changed":
        await connect(client, owner=99)
    else:
        original = client.session.make_request

        async def reject(bot, method, timeout=None):
            if method.__api_method__ == "sendMessage" and method.business_connection_id:
                raise TelegramBadRequest(method=method, message="BUSINESS_PEER_INVALID")
            return await original(bot, method, timeout)

        monkeypatch.setattr(client.session, "make_request", reject)
    before = len(client.session.requests)
    await deliver_due(client.bot, now=row["due_at"])
    sent = [r for r in client.session.requests[before:] if r.__api_method__ == "sendMessage"]
    assert len(sent) == 1 and sent[0].chat_id == 42 and sent[0].business_connection_id is None
    assert "Не удалось доставить в исходный диалог" in sent[0].text
    assert not repository.reminders(42)


async def test_business_rate_limit_retries_original_route_without_duplicate_owner_message(
    client, repository, monkeypatch
):
    await connect(client)
    await client.feed(business_message=incoming(client, ".timer 1s", sender=42))
    row = repository.reminders(42)[0]
    original = client.session.make_request

    async def limited(bot, method, timeout=None):
        if method.__api_method__ == "sendMessage" and method.business_connection_id:
            raise TelegramRetryAfter(method=method, message="retry", retry_after=3)
        return await original(bot, method, timeout)

    monkeypatch.setattr(client.session, "make_request", limited)
    before = len(requests(client, "sendMessage"))
    await deliver_due(client.bot, now=row["due_at"])
    assert len(requests(client, "sendMessage")) == before
    current = repository.reminders(42)[0]
    assert current["business_connection_id"] == "business" and current["due_at"] == row["due_at"] + 4
    monkeypatch.setattr(client.session, "make_request", original)
    await deliver_due(client.bot, now=current["due_at"])
    assert requests(client, "sendMessage")[-1].business_connection_id == "business"


def test_v4_upgrade_and_restart_preserve_reminders_paid_access_and_business_target(tmp_path):
    path = tmp_path / "upgrade.sqlite3"
    old = Database(str(path))
    old.upsert_user(User(id=42, is_bot=False, first_name="Owner"))
    key = old.add_reminder(42, 42, "Existing", 1000)
    order = old.create_order(42, "month", 50, 30)
    old.fulfill_order(old.payload(order["order_id"]), 42, "XTR", 50, "paid")
    expiry = old.premium_until(42)
    old.conn.execute("ALTER TABLE reminders DROP COLUMN business_connection_id")
    old.conn.execute("PRAGMA user_version=4")
    old.close()
    repo = Database(str(path))
    assert repo.conn.execute("PRAGMA user_version").fetchone()[0] == 8
    assert repo.reminders(42)[0]["id"] == key and repo.reminders(42)[0]["business_connection_id"] is None
    assert repo.premium_until(42) == expiry and len(list(tmp_path.glob("*.pre-v5-*.bak"))) == 1
    repo.save_connection("business", 42, True, True)
    business_key = repo.add_reminder(42, 77, "Business", 1001, business_connection_id="business")
    with pytest.raises(ValueError):
        repo.add_reminder(99, 77, "Wrong owner", 1001, business_connection_id="business")
    repo.close()
    reopened = Database(str(path))
    stored = next(r for r in reopened.reminders(42) if r["id"] == business_key)
    assert stored["business_connection_id"] == "business" and stored["chat_id"] == 77
    assert reopened.premium_until(42) == expiry
    assert len(list(tmp_path.glob("*.pre-v5-*.bak"))) == 1
    reopened.close()


async def test_business_tic_tac_toe_is_playable_and_bound_to_connection(client, repository):
    await connect(client)
    await client.feed(business_message=incoming(client, ".x", sender=42))
    game = repository.game("ttt", 77, 42)
    await connect(client, name="other")
    await client.callback(f"ttt:{game['id']}:0", chat_id=77, business="other", mid=game["message_id"])
    assert repository.game("ttt", 77, 42)["board"][0] == "⬜"
    await client.callback(
        f"ttt:{game['id']}:0", user_id=77, chat_id=77, business="business", mid=game["message_id"]
    )
    assert repository.game("ttt", 77, 42)["board"][0] == "⬜"
    await client.callback(f"ttt:{game['id']}:0", chat_id=77, business="business", mid=game["message_id"])
    assert repository.game("ttt", 77, 42)["board"][0] == "❌"
    assert requests(client, "editMessageMedia")[-1].business_connection_id == "business"


async def test_business_export_requires_explicit_destination_confirmation(client, repository):
    await connect(client)
    repository.save_note(42, "Own", "Body")
    repository.save_note(99, "Other", "Secret")
    await client.feed(business_message=incoming(client, ".export", sender=42))
    assert not requests(client, "sendDocument")
    command_seen.clear()
    await client.feed(business_message=incoming(client, ".export CONFIRM", sender=42))
    document = requests(client, "sendDocument")[-1]
    assert document.chat_id == 77 and document.business_connection_id == "business"
    data = json.loads(document.document.data)
    assert [n["title"] for n in data["notes"]] == ["Own"]


async def test_business_plan_button_sends_stars_invoice_only_to_owner(client, repository):
    await connect(client)
    await client.callback("pay:day", chat_id=77, business="business")
    invoice = requests(client, "sendInvoice")[-1]
    assert invoice.chat_id == 42 and invoice.currency == "XTR" and invoice.provider_token == ""
    assert repository.order(invoice.payload[4:])["user_id"] == 42
    assert "Счёт в Stars отправлен владельцу" in requests(client, "sendMessage")[-1].text
    await client.callback("pay:day", user_id=77, chat_id=77, business="business")
    assert len(requests(client, "sendInvoice")) == 1


async def test_business_profile_can_manage_another_owned_dialog_without_accepting_peer_notice_elsewhere(
    client, repository
):
    await connect(client)
    await client.feed(business_message=incoming(client, ".mute", sender=42, chat=88))
    row = next(r for r in repository.dialogs(42) if r["chat_id"] == 88)
    await client.callback(f"mute:off:{row['id']}", chat_id=77, business="business")
    assert repository.dialog(42, row["id"])["muted"]
    await client.callback(f"dialog:open:{row['id']}", chat_id=77, business="business", illustrated=True)
    panel = requests(client, "editMessageMedia")[-1]
    unmute = next(b for r in panel.reply_markup.inline_keyboard for b in r if b.text == "Размутить")
    await client.callback(unmute.callback_data, chat_id=77, business="business", illustrated=True)
    assert not repository.dialog(42, row["id"])["muted"]
    assert any(
        r.chat_id == 88 and r.business_connection_id == "business"
        for r in requests(client, "editMessageText")
    )


async def test_wordle_does_not_accept_guesses_from_another_business_connection(
    client, repository, monkeypatch
):
    await connect(client)
    await connect(client, name="other")
    monkeypatch.setattr(access, "settings", replace(access.settings, admin_ids=frozenset({42})))
    repository.save_game(
        "word", 77, 42, {"answer": "лампа", "turns": 0, "business_connection_id": "business"}
    )
    await client.feed(business_message=incoming(client, ".guess лампа", sender=42, name="other"))
    assert repository.game("word", 77, 42)["turns"] == 0
    assert "Начните игру" in texts(client)[-1]
    command_seen.clear()
    await client.feed(business_message=incoming(client, ".guess лампа", sender=42))
    assert "Победа" in texts(client)[-1] and repository.game("word", 77, 42) is None


async def test_business_autoreply_commands_edit_enable_and_disable_configuration(client, repository):
    await connect(client)
    for command in (".autoreply text Отвечу позже", ".autoreply cooldown 90", ".autoreply on"):
        await client.feed(business_message=incoming(client, command, sender=42))
    config = repository.get_autoreply(42)
    assert config["reply_text"] == "Отвечу позже" and config["cooldown"] == 90 and config["enabled"]
    await client.feed(business_message=incoming(client, "Привет"))
    assert requests(client, "sendMessage")[-1].text == "Отвечу позже"
    await client.feed(business_message=incoming(client, ".autoreply off", sender=42))
    assert not repository.get_autoreply(42)["enabled"]


async def test_confirmed_data_deletion_works_in_business_and_preserves_plus(client, repository):
    await connect(client)
    repository.save_note(42, "Удалить", "Текст")
    order = repository.create_order(42, "month", 50, 30)
    repository.fulfill_order(repository.payload(order["order_id"]), 42, "XTR", 50, "retained")
    expiry = repository.premium_until(42)
    await client.feed(business_message=incoming(client, ".delete_data", sender=42))
    assert repository.notes(42)
    command_seen.clear()
    await client.feed(business_message=incoming(client, ".delete_data CONFIRM", sender=42))
    assert not repository.notes(42) and not repository.dialogs(42)
    assert repository.premium_until(42) == expiry and repository.payment("retained")
    sent = requests(client, "sendMessage")[-1]
    assert sent.chat_id == 77 and sent.business_connection_id == "business" and "удалены" in sent.text


@pytest.mark.parametrize("mode,total", [("free", 4), ("plus", 3)])
async def test_every_tool_page_shows_commands_without_extra_cards(client, mode, total):
    for page in range(total):
        await client.callback(f"list:{mode}:{page}", illustrated=True)
        result = requests(client, "editMessageMedia")[-1]
        for row in result.reply_markup.inline_keyboard:
            for button in row:
                if button.callback_data.startswith("run:"):
                    code = button.callback_data.split(":")[1]
                    assert f"<code>.{code}</code>" in result.media.caption
        assert len(result.media.caption) < 1600  # rendered caption stays below Telegram's own limit


async def test_watermark_prompt_shows_copyable_command_and_business_long_panel_cleans_correctly(
    client, repository, monkeypatch
):
    await connect(client)
    monkeypatch.setattr(access, "settings", replace(access.settings, admin_ids=frozenset({42})))
    await client.callback("run:wm:plus:1", illustrated=True, chat_id=77, business="business")
    assert "<code>.wm alcLua</code>" in requests(client, "editMessageMedia")[-1].media.caption
    repository.save_autoreply(42, reply_text="Я" * 1000)
    await client.callback("menu:autoreply", illustrated=True, chat_id=77, business="business", mid=300)
    stored = json.loads(repository.load_panel(client.bot.id, "business", 77)["pages"])
    assert stored["text"].count("Я") == 1000
    assert not requests(client, "sendMessage") and not requests(client, "deleteBusinessMessages")
    assert not requests(client, "deleteMessage")
