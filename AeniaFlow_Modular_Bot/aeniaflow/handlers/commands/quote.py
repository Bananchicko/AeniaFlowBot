from aeniaflow.core.responses import respond
from aiogram import Bot
from aiogram.types import Message
from aeniaflow.core.helpers import esc, message_text


async def handle(message: Message, args: str, bot: Bot):
    text = args.strip() or message_text(message)
    if not text:
        raise ValueError("Напишите .quote Текст цитаты")
    await respond(message, f"<blockquote>{esc(text[:2500])}</blockquote>")
