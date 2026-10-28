from aiogram import Bot
from aiogram.types import Message
from aeniaflow.core.inputs import media_source


async def handle(message: Message, args: str, bot: Bot):
    source = media_source(message)
    if not source:
        raise ValueError("Отправьте .save, затем файл.")
    if source.has_protected_content:
        raise ValueError("Для этого сообщения включена защита от копирования.")
    for field in ("photo", "video", "animation", "audio", "voice", "video_note", "document", "sticker"):
        media = getattr(source, field, None)
        if media:
            item = media[-1] if field == "photo" else media
            await getattr(message, "answer_" + field)(item.file_id)
            return
