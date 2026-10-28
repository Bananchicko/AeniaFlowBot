from __future__ import annotations
import html, io, random, re, subprocess, tempfile
from pathlib import Path
from typing import Any
from PIL import Image, ImageDraw, ImageFont
import warnings

Image.MAX_IMAGE_PIXELS = 20_000_000
warnings.filterwarnings("error", category=Image.DecompressionBombWarning)
from aiogram import Bot
from aiogram.types import Message
from config import settings, BASE_DIR


def esc(s: Any) -> str:
    return html.escape(str(s or ""))


def message_text(message: Message) -> str:
    if message.reply_to_message:
        src = message.reply_to_message.text or message.reply_to_message.caption or ""
        if src:
            return src
    text = message.text or message.caption or ""
    return re.sub(r"^\.[^\s]+(?:@\w+)?\s*", "", text, count=1).strip()


def get_font(size: int, bold: bool = False, italic: bool = False):
    names = [
        BASE_DIR
        / "assets"
        / "fonts"
        / ("DejaVuSansMono-Oblique.ttf" if italic else "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"),
        (
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
            if bold
            else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
        ),
        (
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"
            if bold
            else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"
        ),
    ]
    for name in names:
        if Path(name).exists():
            return ImageFont.truetype(name, size=size)
    return ImageFont.load_default()


def wrap_lines(text: str, font, max_width: int, draw: ImageDraw.ImageDraw) -> list[str]:
    result = []
    for paragraph in text.splitlines() or [text]:
        words = paragraph.split()
        if not words:
            result.append("")
            continue
        current = words[0]
        for word in words[1:]:
            candidate = current + " " + word
            if draw.textbbox((0, 0), candidate, font=font)[2] <= max_width:
                current = candidate
            else:
                result.append(current)
                current = word
        result.append(current)
    return result


def text_poster(text: str, title: str = "AeniaFlow") -> io.BytesIO:
    img = Image.new("RGB", (1000, 700), (8, 19, 45))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((22, 22, 978, 678), radius=32, outline=(43, 206, 229), width=5)
    draw.text((55, 45), title, fill=(78, 232, 225), font=get_font(34, True))
    for i, line in enumerate(wrap_lines(text.strip()[:1500] or " ", get_font(36), 870, draw)[:12]):
        draw.text((60, 125 + i * 44), line, fill=(238, 245, 255), font=get_font(36))
    out = io.BytesIO()
    img.save(out, format="PNG")
    out.seek(0)
    return out


def circular_text_image(text: str) -> io.BytesIO:
    import math

    text = re.sub(r"\s+", " ", text.strip())[:90] or "AeniaFlow"
    size = 800
    img = Image.new("RGBA", (size, size), (7, 16, 40, 255))
    d = ImageDraw.Draw(img)
    d.ellipse((80, 80, 720, 720), outline=(37, 213, 233, 255), width=6)
    font = get_font(24, True)
    radius = 275
    chars = list(text)
    if len(chars) == 1:
        chars *= 2
    for i, char in enumerate(chars):
        angle = -90 + i * 360 / len(chars)
        tile = Image.new("RGBA", (70, 70), (0, 0, 0, 0))
        ImageDraw.Draw(tile).text((25, 20), char, font=font, fill=(115, 244, 238, 255))
        rot = tile.rotate(-angle - 90, resample=Image.Resampling.BICUBIC, expand=False)
        x = size / 2 + radius * math.cos(math.radians(angle)) - 35
        y = size / 2 + radius * math.sin(math.radians(angle)) - 35
        img.alpha_composite(rot, (int(x), int(y)))
    out = io.BytesIO()
    img.save(out, format="PNG")
    out.seek(0)
    return out


def make_zalgo(text: str) -> str:
    marks = ["̴", "̵", "̶", "̷", "̸", "͛", "͜", "͝", "͞", "͟", "̇", "̈", "̊", "͂", "̓"]
    return "".join(c + "".join(random.choice(marks) for _ in range(random.randint(1, 3))) for c in text[:350])


def run_ffmpeg(args: list[str], timeout: int = 90) -> tuple[bool, str]:
    from aeniaflow.core.ffmpeg import ffmpeg_binary

    executable = ffmpeg_binary()
    if not executable:
        return False, "FFmpeg не найден. Укажите FFMPEG_PATH или положите готовый ffmpeg в bin/."
    try:
        result = subprocess.run(
            [
                executable,
                "-nostdin",
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-threads",
                "2",
                "-filter_threads",
                "1",
                *args,
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.returncode == 0, (result.stderr or "")[-1200:]
    except FileNotFoundError:
        return False, "FFmpeg не найден. Установите ffmpeg."
    except OSError:
        return False, "FFmpeg не запускается. Проверьте права запуска и архитектуру программы через .status."
    except subprocess.TimeoutExpired:
        return False, "Обработка заняла слишком много времени и остановлена."


async def download_file(bot: Bot, file_id: str, suffix: str = ".bin") -> str:
    file = await bot.get_file(file_id)
    limit = settings.max_download_mb * 1024 * 1024
    if not file.file_path:
        raise RuntimeError("Telegram не вернул путь к файлу.")
    if file.file_size and file.file_size > limit:
        raise ValueError(f"Максимальный размер файла: {settings.max_download_mb} МБ.")
    suffix = suffix if re.fullmatch(r"\.[A-Za-z0-9]{1,10}", suffix) else ".bin"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tmp.close()
    try:

        class LimitedWriter:
            def __init__(self, target):
                self.target, self.size = target, 0

            def write(self, chunk):
                self.size += len(chunk)
                if self.size > limit:
                    raise ValueError("Файл превышает допустимый размер.")
                return self.target.write(chunk)

            def flush(self):
                self.target.flush()

        with open(tmp.name, "wb") as target:
            await bot.download_file(file.file_path, destination=LimitedWriter(target), timeout=60, seek=False)
        return tmp.name
    except BaseException:
        Path(tmp.name).unlink(missing_ok=True)
        raise


async def ai_text(
    prompt: str, system: str = "Ты — помощник AeniaFlow. Отвечай по-русски, ясно и по делу."
) -> str:
    from aeniaflow.core.ai_service import text

    return await text(prompt, system)
