from aeniaflow.core.runtime import db
from aeniaflow.core.ui import panel
from aeniaflow.core.command_help import with_command
from aeniaflow.keyboards import kb

STYLES = {"auto": "Минимал", "glass": "Стекло", "signature": "Курсив"}
SCATTERS = {"center": "Ближе к центру", "spread": "По всему фото"}
POSITIONS = {
    "tl": "↖ Слева сверху",
    "tr": "Справа сверху ↗",
    "bl": "↙ Слева снизу",
    "br": "Справа снизу ↘",
    "center": "В центре",
}


async def show_watermark(message, owner, *, edit=False):
    row = db.get_user(owner)
    style, position, opacity = row["watermark_style"], row["watermark_position"], row["watermark_opacity"]
    count, scatter = row["watermark_count"], row["watermark_scatter"]
    placement = POSITIONS[position] if count == 1 else SCATTERS[scatter]
    text = (
        f"<b>Водяные знаки</b>\n\n<blockquote>Количество: {count} · {STYLES[style]} · {opacity}%\n{placement}</blockquote>\n"
        + (
            "Одна подпись в выбранном месте.\n\n"
            if count == 1
            else "Каждое фото — новая случайная раскладка, с отступами и без наложений.\n\n"
        )
        + "Выберите количество, стиль, расположение и прозрачность. Затем нажмите «Добавить на фото». Настройки сохраняются.\n\n"
        + f"Для одного фото: <code>.wm --count {count} "
        + (f"--pos {position}" if count == 1 else f"--scatter {scatter}")
        + " alcLua</code>"
    )

    def option(label, key, value, active):
        return (("✓ " if active else "") + label, f"wmset:{key}:{value}", "primary" if active else None)

    buttons = [
        [option(f"{value} шт.", "count", value, value == count) for value in (1, 3, 5)],
        [option(f"{value} шт.", "count", value, value == count) for value in (8, 10, 12)],
        [option(label, "style", key, key == style) for key, label in STYLES.items()],
    ]
    buttons += (
        [
            [option(POSITIONS[key], "position", key, key == position) for key in ("tl", "tr")],
            [option(POSITIONS[key], "position", key, key == position) for key in ("bl", "br")],
            [option(POSITIONS["center"], "position", "center", position == "center")],
        ]
        if count == 1
        else [[option(label, "scatter", key, key == scatter) for key, label in SCATTERS.items()]]
    )
    buttons += [
        [option(f"{value}%", "opacity", value, value == opacity) for value in (25, 40, 55, 70)],
        [("Добавить на фото", "use:wm", "primary")],
        [("‹ Plus функции", "list:plus:1"), ("Профиль", "menu:profile")],
    ]
    await panel(message, with_command(text, "watermark"), kb(buttons), edit=edit)
