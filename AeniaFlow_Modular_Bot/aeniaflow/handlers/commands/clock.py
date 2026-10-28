from aeniaflow.core.responses import respond
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from aiogram import Bot
from aiogram.types import Message
from aeniaflow.core.runtime import db
from aeniaflow.core.helpers import esc


async def handle(message: Message, args: str, bot: Bot):
    if not message.from_user:
        return
    tz = args.strip()
    if tz:
        try:
            ZoneInfo(tz)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Неизвестный часовой пояс. Пример: Europe/Riga") from None
        db.set_timezone(message.from_user.id, tz)
    row = db.get_user(message.from_user.id)
    tz = row["timezone"] if row else "UTC"
    await respond(message, f'🕒 {esc(tz)}: <b>{datetime.now(ZoneInfo(tz)).strftime("%Y-%m-%d %H:%M:%S")}</b>')
