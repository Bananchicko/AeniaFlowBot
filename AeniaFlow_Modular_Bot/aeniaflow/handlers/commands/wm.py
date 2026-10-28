import asyncio
from pathlib import Path
from aiogram.types import BufferedInputFile
from aeniaflow.core.inputs import media_source, media_file
from aeniaflow.core.helpers import download_file
from aeniaflow.core.runtime import db
from aeniaflow.core.watermark import parse_options, render_watermark


async def handle(message, args, bot):
    photo = media_file(media_source(message, "photo"), "photo")
    if not photo:
        raise ValueError("Отправьте фото до или после команды .wm. Настройки: .watermark")
    options = parse_options(args, db.get_user(message.from_user.id))
    source = await download_file(bot, photo.file_id, ".img")
    try:
        result = await asyncio.to_thread(render_watermark, source, options)
        await message.answer_document(
            BufferedInputFile(result, filename="watermark.png"),
            caption=f"Готово · знаков: {options.count}. "
            + (
                "Одна подпись."
                if options.count == 1
                else "Ближе к центру." if options.scatter == "center" else "По всему фото."
            )
            + " PNG сохраняет качество изображения.\nНастройки: .watermark",
        )
    finally:
        Path(source).unlink(missing_ok=True)
