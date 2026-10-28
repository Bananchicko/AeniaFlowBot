from aeniaflow.core.responses import respond

"""Text-to-speech delivered as a Telegram voice note, never as a music file."""

import asyncio
import logging
import tempfile
from pathlib import Path
from aiogram import Bot
from aiogram.types import Message, FSInputFile
from aeniaflow.core.helpers import run_ffmpeg
from aeniaflow.core.ffmpeg import ffmpeg_binary

log = logging.getLogger(__name__)


async def handle(message: Message, args: str, bot: Bot):
    text = args.strip()
    if not text:
        await respond(message, "Напишите текст: <code>.msay Привет!</code>")
        return
    if len(text) > 500:
        raise ValueError("Для одного голосового — до 500 символов. Разделите текст на части.")
    if not ffmpeg_binary():
        raise ValueError(
            "Для голосовых нужен готовый FFmpeg с libopus: установите его на хостинге или укажите FFMPEG_PATH. Архив исходников .tar.xz не является программой. Инструкция: FFMPEG_SETUP.md."
        )
    from gtts import gTTS

    with tempfile.TemporaryDirectory(prefix="aeniaflow-voice-") as directory:
        source, target = Path(directory) / "speech.mp3", Path(directory) / "voice.ogg"
        try:
            await asyncio.to_thread(lambda: gTTS(text, lang="ru", timeout=(5, 20)).save(str(source)))
        except Exception as exc:
            log.warning("Speech synthesis failed: %s", type(exc).__name__)
            raise ValueError("Сервис озвучки недоступен. Попробуйте позже.") from exc
        ok, _ = await asyncio.to_thread(
            run_ffmpeg,
            [
                "-i",
                str(source),
                "-vn",
                "-ac",
                "1",
                "-ar",
                "48000",
                "-c:a",
                "libopus",
                "-b:a",
                "48k",
                "-application",
                "voip",
                "-f",
                "ogg",
                str(target),
            ],
        )
        if not ok or not target.exists() or target.stat().st_size == 0:
            raise ValueError("Не удалось собрать голосовое. Проверьте FFmpeg с поддержкой libopus.")
        await message.answer_voice(FSInputFile(target, filename="voice.ogg"))
