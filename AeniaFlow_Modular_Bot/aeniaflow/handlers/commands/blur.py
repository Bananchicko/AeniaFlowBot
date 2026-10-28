from aeniaflow.core.responses import respond
from aeniaflow.core.inputs import media_source, media_file
import html, io, os
from PIL import Image, ImageFilter
from aiogram import Bot
from aiogram.types import Message, BufferedInputFile
from aeniaflow.core.helpers import download_file


async def handle(message: Message, args: str, bot: Bot):
    reply = media_source(message, "photo")
    photo = media_file(reply, "photo")
    if not photo:
        raise ValueError("Отправьте фото и команду .blur, либо добавьте команду в подпись к фото.")
    src = None
    try:
        src = await download_file(bot, photo.file_id, ".jpg")
        with Image.open(src).convert("RGB") as img:
            img.thumbnail((1600, 1600))
            img = img.filter(ImageFilter.GaussianBlur(radius=max(3, img.width // 60)))
            out = io.BytesIO()
            img.save(out, format="JPEG", quality=90)
            out.seek(0)
            await message.answer_photo(
                BufferedInputFile(out.getvalue(), filename="blurred.jpg"), caption="Фото размыто"
            )
    except Exception as exc:
        await respond(message, f"Не удалось обработать фото: {html.escape(str(exc)[:200])}")
    finally:
        if src and os.path.exists(src):
            os.unlink(src)
