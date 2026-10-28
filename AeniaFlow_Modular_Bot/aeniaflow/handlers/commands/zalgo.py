from aeniaflow.core.responses import respond
import html
from aiogram import Bot
from aiogram.types import Message
from aeniaflow.core.helpers import make_zalgo


async def handle(message: Message, args: str, bot: Bot):
    if not args.strip():
        await respond(message, "Укажите текст: <code>.zalgo привет</code>")
        return
    await respond(message, html.escape(make_zalgo(args)))
