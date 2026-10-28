from aeniaflow.core.responses import respond
import random
from aiogram import Bot
from aiogram.types import Message
from aeniaflow.core.helpers import message_text, esc


async def handle(message: Message, args: str, bot: Bot):
    text = (args or message_text(message)).strip()
    if not text:
        await respond(message, "Укажите текст: <code>.dumb текст</code>")
        return
    out = "".join(
        c.upper() if c.isalpha() and random.random() < 0.5 else c.lower() if c.isalpha() else c
        for c in text[:3500]
    )
    await respond(message, esc(out))
