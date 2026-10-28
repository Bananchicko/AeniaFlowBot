from __future__ import annotations
from aeniaflow.core.responses import respond
import base64
import asyncio
import hashlib
import secrets
import uuid as uuid_module
from aiogram import Bot
from aiogram.types import Message, InputPollOption
from aeniaflow.catalog import FEATURES
from aeniaflow.core.helpers import esc, message_text
from aeniaflow.core.ui import answer_text
from aeniaflow.core.ffmpeg import ffmpeg_binary, probe_ffmpeg
from aeniaflow.core.navigation import run_callback, tool_name


async def find(message: Message, args: str, bot: Bot):
    query = args.casefold().strip()
    if not query:
        await respond(
            message, "Поиск: <code>.find фото</code>, <code>.find голос</code>, <code>.find заметки</code>."
        )
        return
    from aeniaflow.keyboards import kb

    matches = [
        (code, name)
        for code, (name, usage) in FEATURES.items()
        if query in f"{code} {name} {usage}".casefold()
    ][:20]
    buttons = [(tool_name(code), run_callback(code)) for code, _ in matches]
    await respond(
        message,
        f"<b>Результаты поиска</b>\n\n{esc(args[:80])}\n"
        + (
            "\n".join(f"<code>.{code}</code> — {esc(tool_name(code))}" for code, _ in matches)
            if matches
            else "Ничего не найдено. Попробуйте другое название."
        ),
        reply_markup=kb(
            [buttons[i : i + 2] for i in range(0, len(buttons), 2)]
            + [[("Новый поиск", "input:find"), ("Главное меню", "menu:home")]]
        ),
    )


async def status(message: Message, args: str, bot: Bot):
    from aeniaflow.core.ai_service import available

    ai = "ключ настроен" if available() else "не настроен или выключен"
    video = await asyncio.to_thread(probe_ffmpeg, ffmpeg_binary())
    await respond(
        message,
        f'<b>Состояние AeniaFlow</b>\nБот: работает\nИИ: {ai}\nОбработка видео: {"готова" if video["ready"] else "требует настройки"}\n{esc(video["detail"])}\nОплата: Telegram Stars\n\nЭто локальная проверка. Доступность Telegram и ИИ определяется при запросе.',
    )


async def choose(message: Message, args: str, bot: Bot):
    variants = [x.strip() for x in args.split("|") if x.strip()]
    if not 2 <= len(variants) <= 30:
        raise ValueError("Укажите от 2 до 30 вариантов: .choose чай | кофе | вода")
    await respond(message, "🎯 " + esc(secrets.choice(variants)[:1000]))


async def dice(message: Message, args: str, bot: Bot):
    emojis = {"dice": "🎲", "dart": "🎯", "basket": "🏀", "ball": "⚽", "bowling": "🎳", "slot": "🎰"}
    await message.answer_dice(emoji=emojis.get(args.strip(), "🎲"))


async def poll(message: Message, args: str, bot: Bot):
    values = [x.strip() for x in args.split("|")]
    if (
        not 3 <= len(values) <= 11
        or not 1 <= len(values[0]) <= 300
        or any(not 1 <= len(x) <= 100 for x in values[1:])
    ):
        raise ValueError("Формат: .poll Вопрос | Вариант 1 | Вариант 2 (2–10 вариантов).")
    await message.answer_poll(
        question=values[0], options=[InputPollOption(text=x) for x in values[1:]], is_anonymous=True
    )


async def textstats(message: Message, args: str, bot: Bot):
    text = args or message_text(message)
    await respond(
        message,
        f'Символов: {len(text)}\nБез пробелов: {len("".join(text.split()))}\nСлов: {len(text.split())}\nСтрок: {len(text.splitlines())}\nЧтение: ~{max(1, round(len(text.split())/180))} мин.',
    )


async def encode(message: Message, args: str, bot: Bot):
    text = args or message_text(message)
    if not text:
        raise ValueError("Укажите текст: .encode Привет")
    await answer_text(message, base64.b64encode(text.encode()).decode())


async def decode(message: Message, args: str, bot: Bot):
    try:
        text = base64.b64decode(args.strip(), validate=True).decode("utf-8")
    except (ValueError, UnicodeError) as exc:
        raise ValueError("Требуется корректная строка Base64 с текстом UTF-8.") from exc
    await answer_text(message, text or "(пустая строка)")


async def sha256(message: Message, args: str, bot: Bot):
    await respond(
        message, "<code>" + hashlib.sha256((args or message_text(message)).encode()).hexdigest() + "</code>"
    )


async def uuid(message: Message, args: str, bot: Bot):
    await respond(message, "<code>" + str(uuid_module.uuid4()) + "</code>")
