import re
from aiogram import Bot
from aiogram.types import Message
from aeniaflow.core.helpers import ai_text, message_text
from aeniaflow.core.ai_service import available
from aeniaflow.core.ui import answer_text


async def handle(message: Message, args: str, bot: Bot):
    text = args or message_text(message)
    if not text:
        raise ValueError("Укажите текст или ответьте на сообщение: .fix текст")
    if available():
        result = await ai_text(
            text,
            system="Исправь орфографию, пунктуацию и пробелы. Сохрани смысл и стиль. Верни только исправленный текст.",
        )
    else:
        result = re.sub(r"\s+([,.!?;:])", r"\1", text)
        result = re.sub(r"([,.!?])(?=\S)", r"\1 ", result)
        result += "\n\nЛокальная обработка пробелов; ИИ-коррекция пока не подключена."
    await answer_text(message, result)
