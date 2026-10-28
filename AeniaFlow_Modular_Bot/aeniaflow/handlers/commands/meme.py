from aeniaflow.core.responses import respond
from aeniaflow.core.inputs import media_source, media_file
import html, os
from PIL import Image, ImageDraw
from aiogram import Bot
from aiogram.types import Message, BufferedInputFile
from aeniaflow.core.helpers import download_file, get_font, wrap_lines


async def handle(message: Message, args: str, bot: Bot):
    reply = media_source(message, "photo")
    photo = media_file(reply, "photo")
    if not photo:
        raise ValueError("Отправьте фото и команду .meme, либо добавьте команду в подпись к фото.")
    src = None
    try:
        top, bottom = (args.split("|", 1) + [""])[:2]
        src = await download_file(bot, photo.file_id, ".jpg")
        with Image.open(src).convert("RGB") as img:
            draw = ImageDraw.Draw(img)
            font = get_font(max(18, img.width // 16), True)
            for text, where in ((top.strip()[:100], "top"), (bottom.strip()[:100], "bottom")):
                if not text:
                    continue
                lines = wrap_lines(text.upper(), font, img.width - 30, draw)[:3]
                line_h = getattr(font, "size", 18) + 6
                for i, line in enumerate(lines):
                    width = draw.textbbox((0, 0), line, font=font, stroke_width=3)[2]
                    x = max(4, (img.width - width) // 2)
                    y = 10 + i * line_h if where == "top" else img.height - 10 - (len(lines) - i) * line_h
                    draw.text((x, y), line, font=font, fill="white", stroke_width=3, stroke_fill="black")
            out = __import__("io").BytesIO()
            img.save(out, format="JPEG", quality=90)
            out.seek(0)
            await message.answer_photo(BufferedInputFile(out.getvalue(), filename="aeniaflow-meme.jpg"))
    except Exception as exc:
        await respond(message, f"Не удалось создать мем: {html.escape(str(exc)[:200])}")
    finally:
        if src and os.path.exists(src):
            os.unlink(src)
