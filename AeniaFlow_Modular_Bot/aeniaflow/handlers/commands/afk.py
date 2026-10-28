from aeniaflow.core.responses import respond
from aiogram import Bot
from aiogram.types import Message
from aeniaflow.core.runtime import db
from aeniaflow.core.helpers import esc


async def handle(message: Message, args: str, bot: Bot):
    if not message.from_user:
        return
    row = db.get_user(message.from_user.id)
    if args.strip().lower() == "off" or row and row["afk_reason"] and not args.strip():
        db.set_afk(message.from_user.id, None)
        await respond(message, "AFK-режим выключен.")
    else:
        reason = args.strip()[:150] or "вернусь позже"
        db.set_afk(message.from_user.id, reason)
        await respond(message, f"🌙 AFK-режим включён: {esc(reason)}")
