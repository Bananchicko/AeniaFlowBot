from __future__ import annotations
from aeniaflow.core.responses import respond
import json
from aiogram import Bot
from aiogram.types import Message, BufferedInputFile
from aeniaflow.core.runtime import db
from aeniaflow.core.helpers import esc
from aeniaflow.core.ui import private_only, answer_text, format_time
from aeniaflow.core.scheduling import parse_reminder, parse_duration
from aeniaflow.keyboards import kb


def page_number(args: str) -> int:
    try:
        return max(1, min(100, int(args or "1")))
    except ValueError as exc:
        raise ValueError("Укажите номер страницы: .notes 2") from exc


async def notes(message: Message, args: str, bot: Bot):
    if not await private_only(message):
        return
    page = page_number(args)
    rows = db.notes(message.from_user.id, offset=(page - 1) * 10)
    text = "\n".join(f'#{r["id"]} · {esc(r["title"])}' for r in rows) or "Пока пусто."
    await respond(
        message,
        f"<b>📝 Заметки · страница {page}</b>\n{text}\n\n<code>.note add Название | Текст</code>\n<code>.note ID</code> — открыть\n<code>.note delete ID</code> — удалить\n<code>.note find текст</code> — поиск\n<code>.notes 2</code> — следующая страница",
    )


async def note(message: Message, args: str, bot: Bot):
    if not await private_only(message):
        return
    user = message.from_user.id
    command, _, value = args.partition(" ")
    if command == "add":
        title, separator, body = value.partition("|")
        if not separator:
            raise ValueError("Формат: .note add Название | Текст")
        key = db.save_note(user, title, body)
        await respond(message, f"📝 Заметка #{key} сохранена. Открыть: <code>.note {key}</code>")
    elif command == "delete" and value.isdigit():
        ok = db.delete_note(user, int(value))
        await respond(message, "Заметка удалена." if ok else "Заметка не найдена.")
    elif command == "find" and value:
        rows = db.notes(user, value)
        await respond(
            message, "\n".join(f'#{r["id"]} · {esc(r["title"])}' for r in rows) or "Совпадений нет."
        )
    elif command.isdigit():
        row = db.note(user, int(command))
        if row:
            await answer_text(message, row["title"] + "\n\n" + row["body"])
        else:
            await respond(message, "Заметка не найдена.")
    else:
        await notes(message, "", bot)


async def todo(message: Message, args: str, bot: Bot):
    if not await private_only(message):
        return
    user = message.from_user.id
    command, _, value = args.partition(" ")
    if command == "add":
        key = db.add_task(user, value)
        await respond(
            message,
            f"☐ Задача #{key} добавлена.",
            reply_markup=kb([[("✓ Выполнено", f"task:done:{user}:{key}")]]),
        )
        return
    if command in {"done", "undo", "delete"}:
        if not value.isdigit():
            raise ValueError("Пример: .todo done 12")
        ok = (
            db.delete_task(user, int(value))
            if command == "delete"
            else db.change_task(user, int(value), command == "done")
        )
        await respond(message, "Задача обновлена." if ok else "Задача не найдена.")
        return
    page = page_number(args)
    rows = db.tasks(user, (page - 1) * 10)
    text = (
        "\n".join(f'{"✓" if r["done"] else "☐"} #{r["id"]} {esc(r["text"][:120])}' for r in rows)
        or "Задач пока нет."
    )
    buttons = [
        [
            (
                f'{"↩ Вернуть" if r["done"] else "✓ Готово"} #{r["id"]}',
                f'task:{"undo" if r["done"] else "done"}:{user}:{r["id"]}',
            )
        ]
        for r in rows
    ]
    await respond(
        message,
        f"<b>✅ Задачи · страница {page}</b>\n{text}\n\n<code>.todo add Текст</code>\n<code>.todo delete ID</code>\n<code>.todo 2</code> — следующая страница",
        reply_markup=kb(buttons) if buttons else None,
    )


async def remind(message: Message, args: str, bot: Bot):
    if not await private_only(message):
        return
    row = db.get_user(message.from_user.id)
    due, interval, text = parse_reminder(args, row["timezone"])
    key = db.add_reminder(
        message.from_user.id,
        message.chat.id,
        text,
        due,
        interval,
        message.message_thread_id,
        business_connection_id=message.business_connection_id,
    )
    repeat = f"\nПовтор каждые {interval} сек." if interval else ""
    destination = (
        "\nДоставка в этот диалог. Если Telegram её запретит — только вам в ЛС бота."
        if message.business_connection_id
        else ""
    )
    await respond(
        message,
        f'⏰ Напоминание #{key}: {format_time(due, row["timezone"])}{repeat}\n{esc(text)}{destination}',
        reply_markup=kb([[("Отменить", f"remind:cancel:{message.from_user.id}:{key}")]]),
    )


async def timer(message: Message, args: str, bot: Bot):
    seconds = parse_duration(args or "30")
    await remind(message, f"{seconds}s Таймер завершён.", bot)


async def reminders(message: Message, args: str, bot: Bot):
    if not await private_only(message):
        return
    user = message.from_user.id
    if args.startswith("cancel "):
        value = args.split(maxsplit=1)[1]
        if not value.isdigit():
            raise ValueError("Пример: .reminders cancel 5")
        ok = db.cancel_reminder(user, int(value))
        await respond(message, "Напоминание отменено." if ok else "Активное напоминание не найдено.")
        return
    page = page_number(args)
    rows = db.reminders(user, (page - 1) * 10)
    tz = db.get_user(user)["timezone"]
    statuses = {"failed": "❗ Ошибка доставки", "sending": "Отправляется", "pending": "Ожидает"}
    text = (
        "\n\n".join(
            f'#{r["id"]} · {format_time(r["due_at"], tz)}\n{esc(r["text"][:160])}\n{statuses[r["status"]]}{" · повтор" if r["interval_seconds"] else ""}'
            for r in rows
        )
        or "Активных напоминаний нет."
    )
    buttons = [[(f'Отменить #{r["id"]}', f'remind:cancel:{user}:{r["id"]}')] for r in rows]
    await respond(
        message,
        f"<b>⏰ Напоминания · страница {page}</b>\n{text}\n\n<code>.remind 10m Текст</code>\n<code>.reminders 2</code> — следующая страница",
        reply_markup=kb(buttons) if buttons else None,
    )


async def export(message: Message, args: str, bot: Bot):
    if not await private_only(message):
        return
    if message.business_connection_id and args.strip() != "CONFIRM":
        await respond(
            message,
            "Экспорт включает ваши заметки, задачи, платежи и список чатов. Файл в этом диалоге увидит собеседник.\n\n"
            "Чтобы отправить файл сюда: <code>.export CONFIRM</code>.\n"
            "Для получения только себе отправьте <code>.export</code> в личный чат с ботом.",
        )
        return
    data = json.dumps(db.export_user(message.from_user.id), ensure_ascii=False, indent=2).encode()
    await message.answer_document(
        BufferedInputFile(data, filename="aeniaflow-my-data.json"),
        caption="Ваши данные в AeniaFlow.",
        protect_content=True,
    )


async def delete_data(message: Message, args: str, bot: Bot):
    if not await private_only(message):
        return
    if args != "CONFIRM":
        await respond(
            message,
            "Удалятся заметки, задачи, напоминания, игры, список диалогов, муты и настройки автоответчика. Подписка и платёжные записи сохранятся.\nДля удаления: <code>.delete_data CONFIRM</code>.",
        )
        return
    db.clear_personal_data(message.from_user.id)
    await respond(
        message,
        "Личные записи и автоответы удалены. Для отключения доступа Business удалите бота также в настройках Telegram.",
    )
