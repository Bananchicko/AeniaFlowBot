"""Subtle, resolution-aware watermarks with true alpha compositing."""

import io
import math
import random
import re
from dataclasses import dataclass
from PIL import Image, ImageDraw, ImageOps, ImageStat
from aeniaflow.core.helpers import get_font


@dataclass(frozen=True)
class Watermark:
    text: str = "alcLua"
    style: str = "auto"
    position: str = "br"
    opacity: int = 55
    count: int = 5
    scatter: str = "center"


def parse_options(args, user=None):
    values = {
        "style": user["watermark_style"] if user else "auto",
        "position": user["watermark_position"] if user else "br",
        "opacity": user["watermark_opacity"] if user else 55,
        "count": user["watermark_count"] if user else 5,
        "scatter": user["watermark_scatter"] if user else "center",
    }
    text = args.strip()
    while text.startswith("--"):
        match = re.match(r"--(style|pos|opacity|count|scatter)(?:=|\s+)(\S+)(?:\s+|$)", text)
        if not match:
            raise ValueError("Пример: .wm --count 5 --scatter center --opacity 40 alcLua")
        key, value = match.groups()
        values["position" if key == "pos" else key] = value
        text = text[match.end() :].strip()
    if values["style"] not in {"auto", "glass", "signature"} or values["position"] not in {
        "tl",
        "tr",
        "bl",
        "br",
        "center",
    }:
        raise ValueError(
            "Стили: auto, glass, signature. Положение: tl, tr, bl, br, center. Настройки: .watermark"
        )
    try:
        values["opacity"] = int(values["opacity"])
    except ValueError as exc:
        raise ValueError("Непрозрачность — целое число от 10 до 90.") from exc
    if not 10 <= values["opacity"] <= 90:
        raise ValueError("Непрозрачность — от 10 до 90.")
    try:
        values["count"] = int(values["count"])
    except (TypeError, ValueError) as exc:
        raise ValueError("Количество знаков — целое число от 1 до 12.") from exc
    if not 1 <= values["count"] <= 12:
        raise ValueError("Количество знаков — от 1 до 12.")
    if values["scatter"] not in {"center", "spread"}:
        raise ValueError("Размещение: center — ближе к центру, spread — по всему фото.")
    if len(text) > 80:
        raise ValueError("Текст водяного знака — до 80 символов.")
    return Watermark(text=" ".join(text.split()) or "alcLua", **values)


def place_watermarks(image_size, stamp_size, options, *, rng=None):
    """Jitter separate cells so every requested mark fits with a clear gap.

    Return None when the font needs shrinking. Central scatter uses an inset
    region; wide scatter uses the full image with safe outer margins. A fresh
    RNG per image avoids imposing a repeating pattern on different photos.
    """
    width, height = image_size
    bw, bh = stamp_size
    margin = max(4, round(min(width, height) * 0.035))
    if options.count == 1:
        if bw > width - 2 * margin or bh > height - 2 * margin:
            return None
        x = margin if options.position in {"tl", "bl"} else width - margin - bw
        y = margin if options.position in {"tl", "tr"} else height - margin - bh
        if options.position == "center":
            x, y = (width - bw) // 2, (height - bh) // 2
        return [(x, y)]

    inset_x = max(margin, round(width * 0.12)) if options.scatter == "center" else margin
    inset_y = max(margin, round(height * 0.12)) if options.scatter == "center" else margin
    area_w, area_h = width - 2 * inset_x, height - 2 * inset_y
    gap = max(3, round(min(width, height) * 0.025))
    layouts = []
    for columns in range(1, options.count + 1):
        rows = math.ceil(options.count / columns)
        cell_w, cell_h = area_w // columns, area_h // rows
        if cell_w < bw + gap or cell_h < bh + gap:
            continue
        # Near-square cells spread the marks in both dimensions. Penalize
        # spare cells so a small count doesn't cluster in one half by chance.
        score = abs(math.log(cell_w / cell_h)) + (columns * rows - options.count) * 0.35
        if options.count >= 3 and min(columns, rows) == 1 and 0.5 <= area_w / area_h <= 2:
            score += 0.5
        layouts.append((score, columns, rows, cell_w, cell_h))
    if not layouts:
        return None
    _, columns, rows, cell_w, cell_h = min(layouts)
    rng = rng or random.SystemRandom()
    cells = [(column, row) for row in range(rows) for column in range(columns)]
    chosen = rng.sample(cells, options.count)
    offset = gap // 2
    positions = []
    for column, row in chosen:
        x = inset_x + column * cell_w + offset
        y = inset_y + row * cell_h + offset
        # Room on both sides is reserved even for extreme random samples.
        x += rng.randint(0, cell_w - bw - gap)
        y += rng.randint(0, cell_h - bh - gap)
        positions.append((x, y))
    return positions


def render_watermark(source, options):
    with Image.open(source) as original:
        image = ImageOps.exif_transpose(original).convert("RGBA")
    if min(image.size) < 64:
        raise ValueError("Для водяного знака нужно изображение не меньше 64 × 64 пикселей.")
    image.thumbnail((2560, 2560), Image.Resampling.LANCZOS)
    width, height = image.size
    padding = max(3, round(min(width, height) * 0.012)) if options.style == "glass" else 1
    size = max(6, min(round(width * 0.032), round(height * 0.12), 68))
    draw = ImageDraw.Draw(image)
    while True:
        font = get_font(size, italic=options.style == "signature")
        box = draw.textbbox((0, 0), options.text, font=font)
        tw, th = box[2] - box[0], box[3] - box[1]
        # Include the one-pixel shadow and rounded-box endpoints in placement.
        bw, bh = tw + 2 * padding + 2, th + 2 * padding + 2
        positions = place_watermarks(image.size, (bw, bh), options)
        if positions is not None:
            break
        size -= 1
        if size < 4:
            raise ValueError(
                "Знаки не помещаются. Сократите текст, уменьшите количество или отправьте фото крупнее."
            )
    layer = Image.new("RGBA", image.size)
    pen = ImageDraw.Draw(layer)
    alpha = round(255 * options.opacity / 100)
    for x, y in positions:
        brightness = ImageStat.Stat(image.crop((x, y, x + bw, y + bh)).convert("L")).mean[0]
        color, shadow = (
            ((255, 255, 255), (0, 0, 0))
            if brightness < 150 or options.style == "glass"
            else ((24, 28, 36), (255, 255, 255))
        )
        if options.style == "glass":
            pen.rounded_rectangle(
                (x, y, x + bw - 2, y + bh - 2), radius=max(2, bh // 4), fill=(16, 20, 28, round(alpha * 0.55))
            )
        origin = (x + padding - box[0], y + padding - box[1])
        pen.text((origin[0] + 1, origin[1] + 1), options.text, font=font, fill=(*shadow, round(alpha * 0.25)))
        pen.text(origin, options.text, font=font, fill=(*color, alpha))
    result = Image.alpha_composite(image, layer)
    output = io.BytesIO()
    result.save(output, format="PNG")
    return output.getvalue()
