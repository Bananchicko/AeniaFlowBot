import asyncio
from aiogram import Bot
from aiogram.types import Message
from aeniaflow.core.helpers import message_text, esc


async def handle(message: Message, args: str, bot: Bot):
    source = (args or message_text(message)).strip()
    if not source:
        await message.answer("Укажите текст или ответьте на сообщение: <code>.words фраза</code>")
        return
    for word in source.split()[:10]:
        await message.answer(esc(word))
        await asyncio.sleep(1.1)
