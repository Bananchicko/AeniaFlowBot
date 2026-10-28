from aeniaflow.core.runtime import db
from aeniaflow.core.helpers import esc
from aeniaflow.core.ui import panel, format_time
from aeniaflow.core.command_help import with_command
from aeniaflow.keyboards import kb, pager


async def show_organizer(message, user, section, page=1, *, edit=False):
    page = max(1, min(10000, int(page or 1)))
    owner = user.id
    rows = (
        db.notes(owner, offset=(page - 1) * 10)
        if section == "notes"
        else getattr(db, section)(owner, (page - 1) * 10)
    )
    buttons = []
    if section == "notes":
        text = "<b>Заметки</b>\n\n" + (
            "Выберите заметку, чтобы открыть." if rows else "Здесь появятся ваши заметки."
        )
        buttons = [[(row["title"], f'note:open:{owner}:{row["id"]}:0')] for row in rows]
        create = "note"
    elif section == "tasks":
        text = "<b>Задачи</b>\n\n" + (
            "Нажмите задачу, чтобы изменить её статус." if rows else "Задач пока нет. Добавьте первую."
        )
        buttons = [
            [
                (
                    ("✓ " if row["done"] else "○ ") + row["text"][:55],
                    f'task:{"undo" if row["done"] else "done"}:{owner}:{row["id"]}',
                )
            ]
            for row in rows
        ]
        create = "todo"
    else:
        tz = db.get_user(owner)["timezone"]
        text = "<b>Напоминания</b>\n\n" + (
            "\n\n".join(
                f'#{r["id"]} · {format_time(r["due_at"], tz)}\n{esc(r["text"][:140])}'
                + ("\nНе доставлено · проверьте доступ бота" if r["status"] == "failed" else "")
                for r in rows
            )
            or "Активных напоминаний нет."
        )
        buttons = [[(f'Отменить #{r["id"]}', f'remind:cancel:{owner}:{r["id"]}')] for r in rows]
        create = "remind"
    has_next = bool(
        db.notes(owner, offset=page * 10) if section == "notes" else getattr(db, section)(owner, page * 10)
    )
    buttons += [
        pager(section, page, has_next),
        [("+ Добавить", f"input:{create}")],
        [("‹ Профиль", "menu:profile")],
    ]
    await panel(
        message,
        with_command(text + (f"\n\nСтраница {page}" if page > 1 or has_next else ""), section),
        kb(buttons),
        edit=edit,
        protect_content=True,
    )


async def show_note(message, owner, note_id, page=0):
    row = db.note(owner, note_id)
    if not row:
        raise ValueError("Заметка удалена или недоступна.")
    parts = [row["body"][i : i + 1800] for i in range(0, len(row["body"]), 1800)]
    page = max(0, min(page, len(parts) - 1))
    nav = []
    if page:
        nav.append(("‹ Назад", f"note:open:{owner}:{note_id}:{page-1}"))
    if page + 1 < len(parts):
        nav.append(("Дальше ›", f"note:open:{owner}:{note_id}:{page+1}"))
    await panel(
        message,
        f'<b>{esc(row["title"])}</b>\n\n{esc(parts[page])}',
        kb([nav, [("Удалить", f"note:ask:{owner}:{note_id}:0")], [("‹ Заметки", "menu:notes")]]),
        edit=True,
    )
