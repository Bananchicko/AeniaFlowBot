from aiogram import Bot
from aiogram.types import Message
from aeniaflow.core.runtime import db
from aeniaflow.core.helpers import esc
from aeniaflow.core.command_help import with_command
from aeniaflow.core.ui import private_only, panel
from aeniaflow.keyboards import kb


async def show(message: Message, owner_id: int, *, edit=False):
    config, connection = db.get_autoreply(owner_id), db.get_connection(owner_id)
    connected = bool(connection and connection["is_enabled"] and connection["can_reply"])
    active = connected and config["enabled"]
    text = (
        "<b>Автоответчик</b>\n\n"
        + ("Подключение активно" if connected else "Business не подключён или нет права отвечать")
        + f'\nАвтоответ: {"включён" if active else "выключен"}\nИнтервал: {config["cooldown"]} сек.\n\n'
        + f'<b>Текст ответа</b>\n{esc(config["reply_text"])}'
    )
    rows = (
        [
            [
                (
                    "Выключить" if active else "Включить",
                    "auto:off" if active else "auto:on",
                    "danger" if active else "success",
                )
            ]
        ]
        if connected
        else [[("Подключить Business", "menu:connect")]]
    )
    rows += [
        [("Изменить текст", "input:autoreply"), ("Интервал", "input:cooldown")],
        [("‹ Профиль", "menu:profile")],
    ]
    await panel(
        message, with_command(text, "autoreply"), kb(rows), edit=edit, protect_content=True, art="dialogs"
    )


async def handle(message: Message, args: str, bot: Bot):
    if not await private_only(message):
        return
    owner = message.from_user.id
    action, _, value = args.partition(" ")
    if action == "text":
        if not 1 <= len(value.strip()) <= 1000:
            raise ValueError("Текст автоответа: 1–1000 символов.")
        db.save_autoreply(owner, reply_text=value.strip())
    elif action == "cooldown":
        if not value.isdigit() or not 30 <= int(value) <= 604800:
            raise ValueError("Интервал: от 30 до 604800 секунд.")
        db.set_autoreply_cooldown(owner, int(value))
    elif action in {"on", "off"}:
        connection = db.get_connection(owner)
        if action == "on" and (not connection or not connection["is_enabled"] or not connection["can_reply"]):
            await panel(message, "Проверьте подключение и право ответа: <code>.connect</code>.")
            return
        db.save_autoreply(owner, enabled=action == "on")
    elif action not in {"", "status"}:
        raise ValueError("Используйте .autoreply on, off, text или cooldown.")
    await show(message, owner)
