from aeniaflow.core.responses import respond
from aiogram import Bot
from aiogram.types import Message
from aeniaflow.core.helpers import message_text, esc


async def handle(message: Message, args: str, bot: Bot):
    text = (args or message_text(message)).strip()
    table = str.maketrans(
        {
            "a": "4",
            "e": "3",
            "i": "1",
            "o": "0",
            "s": "5",
            "t": "7",
            "A": "4",
            "E": "3",
            "I": "1",
            "O": "0",
            "S": "5",
            "T": "7",
        }
    )
    await respond(message, esc(text.translate(table)[:3900]) or "Укажите текст.")
