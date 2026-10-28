"""A clean text image: no brand, window chrome, frame or technical caption."""

from io import BytesIO
from PIL import Image, ImageDraw
from aeniaflow.core.helpers import get_font


def layout(text, font, width):
    lines = []
    for paragraph in text.split("\n"):
        current = ""
        for word in paragraph.split(" "):
            candidate = current + (" " if current else "") + word
            if font.getlength(candidate) <= width:
                current = candidate
                continue
            if current:
                lines.append(current)
            current = ""
            for char in word:
                if current and font.getlength(current + char) > width:
                    lines.append(current)
                    current = ""
                current += char
        lines.append(current)
    return lines


def text_photo(text):
    text = text.strip()
    if not text or len(text) > 2000:
        raise ValueError("Для .print нужен текст от 1 до 2000 символов.")
    width, margin = 1280, 88
    for size in range(58, 25, -2):
        font = get_font(size)
        lines = layout(text, font, width - 2 * margin)
        spacing = int(size * 1.45)
        height = max(480, 2 * margin + len(lines) * spacing)
        if height <= 1800:
            break
    else:
        raise ValueError("Слишком много строк для одного фото. Разделите текст на две команды .print.")
    image = Image.new("RGB", (width, height), "#fafaf8")
    draw = ImageDraw.Draw(image)
    top = (height - len(lines) * spacing) // 2
    for index, line in enumerate(lines):
        draw.text((margin, top + index * spacing), line, font=font, fill="#202125", anchor="lt")
    output = BytesIO()
    image.save(output, "PNG")
    output.seek(0)
    return output
