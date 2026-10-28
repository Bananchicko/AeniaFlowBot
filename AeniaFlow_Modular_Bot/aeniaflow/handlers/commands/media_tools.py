from __future__ import annotations
import asyncio
import io
from pathlib import Path
from PIL import Image, ImageOps
from aiogram.types import BufferedInputFile, FSInputFile
from aeniaflow.core.helpers import download_file, run_ffmpeg
from aeniaflow.core.inputs import media_source, media_file


def _transform(path, operation, value):
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
        image.thumbnail((2048, 2048))
        if operation == "resize":
            width = int(value)
            if not 64 <= width <= 2048:
                raise ValueError("Ширина: от 64 до 2048 пикселей.")
            height = max(1, round(image.height * width / image.width))
            if height > 4096:
                raise ValueError("Изображение слишком вытянутое для такой ширины.")
            image = image.resize((width, height), Image.Resampling.LANCZOS)
        elif operation == "rotate":
            angle = int(value or "90")
            if angle not in {90, 180, 270}:
                raise ValueError("Поворот: 90, 180 или 270 градусов.")
            image = image.rotate(-angle, expand=True)
        elif operation == "mirror":
            image = ImageOps.mirror(image)
        out = io.BytesIO()
        image.save(out, "JPEG", quality=92)
        return out.getvalue()


async def transform(message, args, bot, operation):
    reply = media_source(message, "photo")
    photo = media_file(reply, "photo")
    if not photo:
        raise ValueError(f"Отправьте фото и команду .{operation}.")
    src = await download_file(bot, photo.file_id, ".jpg")
    try:
        data = await asyncio.to_thread(_transform, src, operation, args.strip())
        await message.answer_document(BufferedInputFile(data, filename=f"aeniaflow-{operation}.jpg"))
    finally:
        Path(src).unlink(missing_ok=True)


async def resize(message, args, bot):
    await transform(message, args, bot, "resize")


async def rotate(message, args, bot):
    await transform(message, args, bot, "rotate")


async def mirror(message, args, bot):
    await transform(message, args, bot, "mirror")


async def convert(message, bot, mode, rate=1.0):
    kind = "video" if mode in {"videonote", "audio", "gif"} else "av"
    reply = media_source(message, kind)
    media = media_file(reply, kind)
    if not media:
        raise ValueError("Отправьте аудио, голосовое или видео вместе с командой или следующим сообщением.")
    is_video = bool(media_file(reply, "video"))
    if mode in {"videonote", "audio", "gif"} and not is_video:
        raise ValueError("Для этой команды нужно видео.")
    src = await download_file(
        bot, media.file_id, ".mp4" if is_video else ".ogg" if getattr(reply, "voice", None) else ".mp3"
    )
    dst = None
    try:
        base = [
            "-protocol_whitelist",
            "file,pipe",
            "-format_whitelist",
            "mov,mp3,ogg,wav,flac,aac,matroska,webm,gif,avi",
            "-i",
            src,
        ]
        if mode == "speed" and is_video:
            dst = src + ".out.mp4"
            command = base + [
                "-t",
                "120",
                "-map",
                "0:v:0",
                "-map",
                "0:a?",
                "-vf",
                f"setpts={1/rate}*PTS,scale=trunc(iw/2)*2:trunc(ih/2)*2",
                "-af",
                f"atempo={rate}",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-movflags",
                "+faststart",
                dst,
            ]
        elif mode in {"speed", "audio"}:
            dst = src + ".out.mp3"
            command = base + [
                "-t",
                "180",
                "-vn",
                "-af",
                f"atempo={rate}",
                "-c:a",
                "libmp3lame",
                "-b:a",
                "128k",
                dst,
            ]
        elif mode == "voice":
            dst = src + ".out.ogg"
            # Normalize sample rate before changing pitch: input need not be 44.1 kHz.
            command = base + [
                "-t",
                "180",
                "-vn",
                "-af",
                f"aresample=48000,asetrate=48000*{rate},aresample=48000",
                "-ac",
                "1",
                "-c:a",
                "libopus",
                "-b:a",
                "64k",
                dst,
            ]
        elif mode == "videonote":
            dst = src + ".note.mp4"
            command = base + [
                "-t",
                "60",
                "-map",
                "0:v:0",
                "-map",
                "0:a?",
                "-vf",
                r"crop=min(iw\,ih):min(iw\,ih),scale=480:480,fps=30",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-movflags",
                "+faststart",
                dst,
            ]
        else:
            dst = src + ".gif"
            command = base + ["-t", "8", "-vf", "fps=12,scale=480:-1:flags=lanczos", "-an", dst]
        ok, _error = await asyncio.to_thread(run_ffmpeg, command)
        if not ok:
            raise ValueError(
                "Не удалось обработать файл. Проверьте формат и наличие обработки видео через .status."
            )
        if Path(dst).stat().st_size > 49 * 1024 * 1024:
            raise ValueError("Результат слишком большой для отправки. Возьмите более короткий файл.")
        if mode == "videonote":
            await message.answer_video_note(FSInputFile(dst))
        elif mode == "voice":
            await message.answer_voice(FSInputFile(dst))
        elif mode == "gif":
            await message.answer_animation(FSInputFile(dst))
        elif mode == "speed" and is_video:
            await message.answer_video(
                FSInputFile(dst), caption=f"Скорость ×{rate:g}; до 120 секунд результата."
            )
        else:
            await message.answer_audio(FSInputFile(dst), caption="Аудио · до 180 секунд результата.")
    finally:
        Path(src).unlink(missing_ok=True)
        if dst:
            Path(dst).unlink(missing_ok=True)


async def audio(message, args, bot):
    await convert(message, bot, "audio")
