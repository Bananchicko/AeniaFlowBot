"""Private control panel. Every entry point rechecks durable administrator access."""

import re
from aiogram.exceptions import TelegramAPIError
from config import settings
from aeniaflow.core.access import is_owner, admin_ids
from aeniaflow.core.runtime import db
from aeniaflow.core.ui import panel
from aeniaflow.core.helpers import esc
from aeniaflow.core.inputs import begin_input, clear_input
from aeniaflow.core.ai_service import available, model_name
from aeniaflow.keyboards import kb
from aeniaflow.handlers.system import admin_users

INPUTS = {"adminadd", "adminremove", "aikey", "aimodel"}
COMMANDS = INPUTS | {"adminmenu", "admin", "adminpause", "adminresume"} | admin_users.COMMANDS


def allowed(message, user):
    return bool(
        user
        and not user.is_bot
        and message.chat.type == "private"
        and not message.business_connection_id
        and message.chat.id == user.id
        and is_owner(user.id)
    )


async def show(message, user, view="home", *, edit=False, notice=""):
    if not allowed(message, user):
        return
    rows = []
    if view == "admins":
        text = "<b>Администраторы</b>\n<code>.AdminMenu</code>\n\n" + "\n".join(
            f"<code>{identifier}</code> · {'владелец' if identifier in settings.owner_ids else 'администратор'}"
            for identifier in admin_ids()
        )
        text += "\n\nВсе администраторы получают Plus бесплатно. Доступ владельца защищён от удаления."
        rows = [[("Добавить", "admin:input:adminadd"), ("Удалить", "admin:input:adminremove")]]
    elif view == "ai":
        text = f"<b>Настройки ИИ</b>\n<code>.AdminMenu</code>\n\nКлюч: {'подключён' if available() else 'не подключён или ИИ выключен'}\nМодель: <code>{esc(model_name())}</code>\n\nНовый ключ применяется сразу и сохраняется после перезапуска. Значение ключа не отображается."
        rows = [
            [("Изменить API-ключ", "admin:input:aikey"), ("Изменить модель", "admin:input:aimodel")],
            [("Включить ИИ", "admin:ai:on"), ("Выключить ИИ", "admin:ai:off")],
        ]
    elif view == "audit":
        entries = db.conn.execute("SELECT * FROM audit ORDER BY id DESC LIMIT 15").fetchall()
        text = "<b>Журнал администратора</b>\n\n" + (
            "\n".join(f"{r['actor_id']} · {esc(r['action'])} · {esc(r['detail'][:100])}" for r in entries)
            or "Пока пусто."
        )
    else:
        stats = db.stats()
        paused = db.runtime_option("maintenance", "0") == "1"
        text = f"<b>Управление AeniaFlow</b>\n<code>.AdminMenu</code>\n\nРежим: {'обслуживание' if paused else 'работает'}\nПользователей: {stats['users']}\nАдминистраторов: {len(admin_ids())}\nПокупок Plus: {stats['payments']}\n\nУправление доступно только администраторам в ЛС этого бота."
        rows = [
            [("Пользователи", "admin:users:all:0"), ("Рассылки", "admin:casts:all")],
            [("Канал подписки", "admin:channel:open"), ("Выплаты рефералам", "admin:payouts:all")],
            [("Администраторы", "admin:view:admins"), ("Ключ и модель ИИ", "admin:view:ai")],
            [("Журнал", "admin:view:audit"), ("Диагностика", "admin:diagnostics:open")],
            [
                (
                    "Возобновить работу" if paused else "Режим обслуживания",
                    "admin:maintenance:off" if paused else "admin:maintenance:on",
                )
            ],
        ]
        text += "\n\nВозврат: <code>.refund ID_чека</code>\nСверка платежей: <code>.reconcile</code>"
    if notice:
        text += "\n\n" + esc(notice)
    if view != "home":
        rows.append([("‹ Админ-меню", "admin:view:home")])
    rows.append([("Главное меню", "menu:home")])
    await panel(message, text, kb(rows), edit=edit, protect_content=True, admin_only=True)


async def prompt(message, user, command, *, edit=False):
    if not allowed(message, user) or command not in INPUTS:
        return
    descriptions = {
        "adminadd": "Пришлите числовой Telegram ID нового администратора. Он получит управление ботом и бесплатный Plus.",
        "adminremove": "Пришлите Telegram ID администратора, чей доступ нужно снять.",
        "aikey": "Пришлите новый OpenAI API-ключ одним сообщением. Бот удалит сообщение с ключом и применит настройку. Ключ не будет показан в меню или журнале.",
        "aimodel": "Пришлите имя модели OpenAI, доступной вашему API-проекту.",
    }
    begin_input(message, command, user_id=user.id, mode="text", back="admin:view:home")
    await panel(
        message,
        "<b>Настройка администратора</b>\n" + f"<code>.{command}</code>\n\n" + descriptions[command],
        kb([[("‹ Отмена", "admin:view:home"), ("Главное меню", "menu:home")]]),
        edit=edit,
        protect_content=True,
        admin_only=True,
    )


async def handle(message, args, bot, command="adminmenu"):
    user = message.from_user
    if not allowed(message, user):
        return
    if command in admin_users.COMMANDS:
        await admin_users.handle(message, args, bot, command)
        return
    if command in {"adminmenu", "admin"}:
        await show(message, user)
        return
    if command in {"adminpause", "adminresume"}:
        db.set_runtime_option("maintenance", int(command == "adminpause"))
        db.audit(user.id, command, "")
        await show(message, user)
        return
    if command not in INPUTS:
        return
    if not args:
        await prompt(message, user, command)
        return
    if command in {"adminadd", "adminremove"}:
        if not re.fullmatch(r"[1-9][0-9]{0,18}", args) or int(args) >= 2**63:
            raise ValueError("Пришлите один положительный числовой Telegram ID.")
        identifier = int(args)
        if command == "adminremove" and identifier in settings.owner_ids:
            raise ValueError("Доступ владельца удалить нельзя.")
        if command == "adminremove" and identifier == user.id:
            raise ValueError("Нельзя снять свой доступ из этой сессии.")
        if command == "adminadd" and (identifier == bot.id or db.peer_type(identifier) is True):
            raise ValueError("Администратором должен быть человек.")
        db.change_admin(user.id, identifier, command == "adminadd")
        clear_input(message)
        await show(message, user, "admins", notice="Доступ сохранён. Plus применяется сразу.")
    elif command == "aikey":
        # Never echo submitted credentials, even when their format is invalid.
        try:
            await bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
        except TelegramAPIError:
            raise ValueError(
                "Не удалось удалить сообщение с ключом. Удалите его вручную и повторите ввод."
            ) from None
        if not re.fullmatch(r"sk-[A-Za-z0-9_-]{16,1020}", args):
            raise ValueError("Формат API-ключа не распознан. Пришлите полный ключ OpenAI без кавычек.")
        db.set_runtime_option("openai_api_key", args)
        db.set_runtime_option("ai_disabled", "0")
        db.audit(user.id, "openai_key_updated", "значение скрыто")
        clear_input(message)
        await show(
            message,
            user,
            "ai",
            notice="Ключ сохранён. Проверка оплаты и доступности модели произойдёт при запросе к ИИ.",
        )
    else:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,119}", args):
            raise ValueError("Укажите только имя модели, без пробелов.")
        db.set_runtime_option("openai_model", args)
        db.audit(user.id, "openai_model_updated", args)
        clear_input(message)
        await show(message, user, "ai", notice="Модель сохранена.")


async def callback(query, bot):
    message, user = query.message, query.from_user
    if not allowed(message, user):
        await query.answer()
        return
    parts = (query.data or "").split(":")
    if len(parts) > 1 and parts[1] in {
        "payouts",
        "payoutask",
        "payoutreject",
        "payoutconfirm",
        "users",
        "person",
        "grantpick",
        "prepare",
        "confirm",
        "search",
        "channel",
        "castaud",
        "casts",
        "castview",
        "castsend",
        "castpause",
        "castresume",
        "castcancel",
    }:
        await admin_users.callback(query, bot)
        return
    if len(parts) != 3:
        await query.answer()
        return
    _, action, value = parts
    await query.answer()
    if action == "diagnostics":
        from aeniaflow.handlers.commands.utilities import status

        await status(message.model_copy(update={"from_user": user}), "", bot)
    elif action == "view" and value in {"home", "admins", "ai", "audit"}:
        await show(message, user, value, edit=True)
    elif action == "input":
        await prompt(message, user, value, edit=True)
    elif action in {"ai", "maintenance"} and value in {"on", "off"}:
        key = "ai_disabled" if action == "ai" else "maintenance"
        db.set_runtime_option(key, int(value == ("off" if action == "ai" else "on")))
        db.audit(user.id, key, value)
        await show(message, user, "ai" if action == "ai" else "home", edit=True)
