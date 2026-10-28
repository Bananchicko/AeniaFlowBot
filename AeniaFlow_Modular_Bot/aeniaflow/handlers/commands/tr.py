from aiogram import Bot
from aiogram.types import Message
from aeniaflow.core.helpers import ai_text, message_text
from aeniaflow.core.ui import answer_text


async def handle(message: Message, args: str, bot: Bot):
    lang, _, text = args.partition(" ")
    if not text and message.reply_to_message:
        text = message_text(message)
    if not lang or len(lang) > 30 or not text:
        raise ValueError("Формат: .tr en Привет, мир!")
    result = await ai_text(
        text, system=f"Переведи текст на язык {lang}. Верни только перевод без комментариев."
    )
    await answer_text(message, result)
