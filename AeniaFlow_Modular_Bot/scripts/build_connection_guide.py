"""Optional artwork build: reportlab + pdftoppm. Not required to run the bot."""

from pathlib import Path
from reportlab.pdfgen.canvas import Canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.colors import HexColor
from reportlab.platypus import Paragraph
from reportlab.lib.styles import ParagraphStyle
import subprocess
import shutil

ROOT = Path(__file__).resolve().parents[1]
FONT = ROOT / "assets/fonts/DejaVuSans.ttf"
pdfmetrics.registerFont(TTFont("Flow", str(FONT)))
W, H = 600, 840
out = ROOT / "assets/connection_guide.pdf"
c = Canvas(str(out), pagesize=(W, H))
c.setTitle("AeniaFlow - Подключение личных чатов")
c.setAuthor("alcLua")
PAPER = "#F8F5EF"
INK = "#14234A"
BLUE = "#174DDE"
MUTED = "#54637D"
c.setFillColor(HexColor(PAPER))
c.rect(0, 0, W, H, fill=1, stroke=0)


def text(x, y, value, size=12, color=INK):
    c.setFillColor(HexColor(color))
    c.setFont("Flow", size)
    c.drawString(x, y, value)


def paragraph(x, top, width, body, size=12, color=INK, leading=None):
    p = Paragraph(
        body,
        ParagraphStyle(
            "body", fontName="Flow", fontSize=size, leading=leading or size * 1.45, textColor=HexColor(color)
        ),
    )
    _, height = p.wrap(width, 1000)
    p.drawOn(c, x, top - height)
    return height


text(34, 805, "AeniaFlow", 14, BLUE)
text(34, 780, "ЛИЧНЫЕ ЧАТЫ / ПОДКЛЮЧЕНИЕ", 9, MUTED)
c.drawImage(str(ROOT / "assets/connection_illustration.png"), 320, 643, width=250, height=167)
text(34, 732, "Бот в ваших", 28)
text(34, 695, "личных чатах", 28)
text(34, 663, "4 шага. Команды через точку.", 11, MUTED)

steps = [
    (
        "01",
        "Запустите бота",
        "Откройте его ЛС и нажмите «Начать» (/start). Скопируйте @username из профиля именно бота.",
    ),
    (
        "02",
        "Подключите личные диалоги",
        "Настройки → Telegram Business → Чат-боты. Укажите @username бота и выберите нужные ЛС.",
    ),
    (
        "03",
        "Разрешите нужные действия",
        "Включите ответы и удаление всех сообщений. Для .autoread разрешите чтение. Бот в диалоге должен быть активен.",
    ),
    (
        "04",
        "Проверьте результат",
        "В ЛС бота: .connect → «Проверить права». В ЛС человека: .ping, затем .calc 2+2.",
    ),
]
for i, (num, title, body) in enumerate(steps):
    y = 616 - i * 100
    c.setStrokeColor(HexColor("#DADFE9"))
    c.setLineWidth(0.6)
    c.line(34, y + 16, 566, y + 16)
    text(34, y - 8, num, 19, BLUE)
    text(82, y - 5, title, 16)
    h = paragraph(82, y - 20, 472, body, 12)
    assert h < 65

c.setFillColor(HexColor("#E8EDFA"))
c.roundRect(34, 142, 532, 63, 10, fill=1, stroke=0)
text(48, 184, "Ответы от вашего имени: окно 24 часа", 12, BLUE)
paragraph(
    48,
    175,
    500,
    "Для ответа через Business собеседник должен написать вам за последние 24 часа. В ЛС самого бота Business не нужен.",
    10,
    INK,
    14,
)
text(34, 115, "ТОЛЬКО ДЛЯ ВЛАДЕЛЬЦА БОТА", 9, BLUE)
paragraph(
    34,
    104,
    532,
    "В @BotFather откройте /mybots → свой бот → Bot Settings и включите Secretary Mode (в некоторых интерфейсах: Business Mode). Privacy Mode относится к группам.",
    10,
    MUTED,
    14,
)
text(34, 31, "Поддержка: @alcLua", 9, MUTED)
text(409, 31, "AeniaFlow 2.8 · 28.10.2026", 9, MUTED)
c.save()
renderer = "/usr/bin/pdftoppm" if Path("/usr/bin/pdftoppm").exists() else shutil.which("pdftoppm")
if not renderer:
    raise SystemExit("Install Poppler to render the guide as PNG")
subprocess.run(
    [renderer, "-singlefile", "-scale-to", "1800", "-png", str(out), str(ROOT / "assets/connect")], check=True
)
print("Connection guide PDF + PNG built")
