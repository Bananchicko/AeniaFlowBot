from aiogram import Bot
from aiogram.types import Message, BufferedInputFile
from aeniaflow.core.plain_photo import text_photo


async def handle(message: Message, args: str, bot: Bot):
    content = args.strip() or (
        message.reply_to_message.text if message.reply_to_message and message.reply_to_message.text else ""
    )
    if not content:
        raise ValueError("Напишите текст для фото. Пример: .print Привет!")
    poster = text_photo(content)
    await message.answer_photo(
        BufferedInputFile(poster.getvalue(), filename="text.png"),
    )
