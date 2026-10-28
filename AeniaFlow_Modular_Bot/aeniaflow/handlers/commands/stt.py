from aeniaflow.core.inputs import media_source, media_file
from pathlib import Path
from aiogram import Bot
from aiogram.types import Message
from aeniaflow.core.helpers import download_file
from aeniaflow.core.ai_service import transcribe, available, AIUnavailable
from aeniaflow.core.ui import answer_text


async def handle(message: Message, args: str, bot: Bot):
    reply = media_source(message, "audio")
    media = media_file(reply, "audio")
    if not media:
        raise ValueError("Отправьте .stt, затем голосовое или аудиофайл.")
    if not available():
        raise AIUnavailable("Распознавание речи пока не подключено владельцем бота.")
    path = await download_file(bot, media.file_id, ".ogg" if reply.voice else ".mp3")
    try:
        await answer_text(message, await transcribe(path))
    finally:
        Path(path).unlink(missing_ok=True)
