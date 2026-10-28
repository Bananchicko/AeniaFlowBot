from __future__ import annotations
import logging
import time
from aiogram import Bot, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import Message, BusinessConnection
from aeniaflow.core.runtime import db, business_notices
from aeniaflow.core.business_access import save_business_connection, human_dialog, refresh_connection
from aeniaflow.core.telegram_errors import log_error, report_error
from aeniaflow.core.policy import banned, maintenance
from aeniaflow.core.access import has_plus, protected_from_mute

router = Router(name="telegram_business")
log = logging.getLogger(__name__)


@router.business_connection()
async def business_connection_update(connection: BusinessConnection):
    save_business_connection(connection)


async def mute_failure(bot, connection, dialog, reason):
    db.private_mute_error(dialog["owner_id"], dialog["id"], reason)
    if not dialog["error_notified"]:
        try:
            await bot.send_message(
                connection["user_chat_id"] or dialog["owner_id"],
                f"Мут в диалоге «{dialog['peer_name']}» не смог удалить сообщение. {reason} Откройте Профиль → Подключение. После восстановления прав удаление новых сообщений возобновится. Снять мут можно в Профиль → Муты.",
                parse_mode=None,
            )
        except TelegramAPIError:
            log.warning("Could not notify Business owner about mute failure")


@router.business_message()
async def business_message_update(message: Message, bot: Bot):
    try:
        await process_business_message(message, bot)
    except TelegramAPIError as exc:
        connection = db.connection_owner(message.business_connection_id)
        if connection and message.from_user and connection["owner_id"] == message.from_user.id:
            await report_error(message, bot, exc, actor=message.from_user.id)
        else:
            log_error(exc)


async def owner_notice(bot, connection, message, reason):
    """Explain rejected owner commands privately, without spamming every outgoing message."""
    key = (bot.id, connection["connection_id"], message.chat.id, reason)
    now = time.monotonic()
    if now - business_notices.get(key, -1000) < 30:
        return
    business_notices[key] = now
    from aeniaflow.keyboards import kb

    try:
        await bot.send_message(
            chat_id=connection["user_chat_id"] or connection["owner_id"],
            text="Команда в подключённом ЛС не выполнена.\n\n" + reason,
            parse_mode=None,
            reply_markup=kb([[("Подключение", "menu:connect"), ("Профиль", "menu:profile")]]),
        )
    except TelegramAPIError as exc:
        log_error(exc)


async def process_business_message(message: Message, bot: Bot):
    connection_id = message.business_connection_id
    if (
        not connection_id
        or message.chat.id == bot.id
        or message.chat.type != "private"
        or not message.from_user
    ):
        return
    db.remember_peer(message.from_user)
    connection = db.connection_owner(connection_id)
    if not connection:
        if message.from_user.is_bot or not human_dialog(message):
            return
        try:
            actual = await bot.get_business_connection(connection_id)
        except TelegramAPIError as exc:
            log_error(exc)
            return
        if actual.id != connection_id:
            return
        save_business_connection(actual)
        connection = db.connection_owner(connection_id)
    owner = connection["owner_id"]
    outgoing = message.from_user.id == owner
    raw = (message.text or message.caption or "").lstrip()
    if outgoing and (message.sender_business_bot or message.via_bot or raw.startswith("/")):
        return
    if message.from_user.id == bot.id:
        return
    previous = db.conn.execute(
        "SELECT * FROM private_dialogs WHERE owner_id=? AND connection_id=? AND chat_id=?",
        (owner, connection_id, message.chat.id),
    ).fetchone()
    incoming = not outgoing and (message.from_user.id == message.chat.id or bool(message.sender_business_bot))
    muted_incoming = bool(incoming and previous and previous["muted"])
    if not muted_incoming and (message.from_user.is_bot or not human_dialog(message)):
        return
    connection = await refresh_connection(bot, owner, connection_id)
    if not connection:
        return
    is_command = raw.startswith(".") and len(raw) > 1 and raw[1].isascii() and raw[1].isalpha()
    if not connection["is_enabled"] or not connection["can_reply"]:
        if outgoing and is_command:
            await owner_notice(
                bot,
                connection,
                message,
                (
                    "Подключение отключено. Включите бота в настройках Telegram Business → Чат-боты."
                    if not connection["is_enabled"]
                    else "Нет права отвечать. Разрешите отправку сообщений и проверьте доступ к этому диалогу."
                ),
            )
        if not connection["is_enabled"] or outgoing:
            return
    dialog = db.remember_dialog(owner, connection_id, message.chat, message.message_id)
    if outgoing:
        db.conn.execute(
            "UPDATE private_dialogs SET outgoing_count=outgoing_count+1 WHERE id=?", (dialog["id"],)
        )
        command = raw.split(maxsplit=1)[0].lower() if raw else ""
        if dialog["paused"] and command not in {".resume", ".chatinfo", ".menu", ".profile", ".ping"}:
            if is_command:
                await owner_notice(
                    bot,
                    connection,
                    message,
                    "Обработка этого диалога на паузе. Отправьте .resume или откройте Профиль → Чаты → Возобновить.",
                )
            return
        from aeniaflow.handlers.system.command_dispatcher import incoming_message

        await incoming_message(message, bot)
        return
    if not incoming or banned(owner) or maintenance():
        return
    db.conn.execute("UPDATE private_dialogs SET incoming_count=incoming_count+1 WHERE id=?", (dialog["id"],))
    db.update_dialog(owner, dialog["id"], "last_incoming_id", message.message_id)
    if dialog["paused"]:
        return
    if dialog["muted"] and protected_from_mute(owner, message.chat.id):
        db.set_private_mute(owner, dialog["id"], False)
        dialog = db.dialog(owner, dialog["id"])
    now = int(time.time())
    if dialog["autoread"] and has_plus(owner):
        try:
            actual = await bot.get_business_connection(connection_id)
            if (
                actual.user.id == owner
                and actual.is_enabled
                and actual.rights
                and actual.rights.can_read_messages
                and not maintenance()
                and not banned(owner)
            ):
                await bot.read_business_message(
                    business_connection_id=connection_id,
                    chat_id=message.chat.id,
                    message_id=message.message_id,
                )
        except TelegramAPIError as exc:
            log_error(exc)
    if dialog["muted"]:
        from aeniaflow.handlers.system.sections import channel_check

        if not await channel_check(bot, owner):
            return
        if not connection["can_delete_all_messages"]:
            await mute_failure(bot, connection, dialog, "Нет права удалять все сообщения.")
            return
        try:
            await bot.delete_business_messages(
                business_connection_id=connection_id, message_ids=[message.message_id]
            )
        except TelegramAPIError:
            await mute_failure(bot, connection, dialog, "Telegram отклонил удаление.")
        else:
            if dialog["mute_error"]:
                db.set_private_mute(owner, dialog["id"], True)
        return
    # Generated messages from other business bots can be muted, but must never
    # start an auto-reply loop or become a new human command/input source.
    if message.sender_business_bot or message.from_user.is_bot:
        return
    from aeniaflow.core.inputs import remember_media

    remember_media(message, owner)
    if not connection["can_reply"]:
        return
    config = db.get_autoreply(owner)
    user = db.get_user(owner)
    afk = user["afk_reason"] if user else None
    rule = None
    if has_plus(owner):
        body = (message.text or message.caption or "").casefold()
        rules = db.conn.execute(
            "SELECT * FROM reply_rules WHERE owner_id=? AND dialog_id=? ORDER BY id", (owner, dialog["id"])
        ).fetchall()
        rule = next((r["reply"] for r in rules if r["keyword"] in body), None)
    if not config["enabled"] and not afk and not dialog["reply_text"] and not rule:
        return
    from aeniaflow.handlers.system.sections import channel_check

    if not await channel_check(bot, owner) or maintenance() or banned(owner):
        return
    previous = db.last_reply(connection_id, message.chat.id)
    if now - previous < config["cooldown"]:
        return
    db.mark_reply(connection_id, message.chat.id, now)
    try:
        await bot.send_message(
            chat_id=message.chat.id,
            text=rule
            or dialog["reply_text"]
            or (f"Сейчас не могу ответить: {afk}" if afk else config["reply_text"]),
            parse_mode=None,
            business_connection_id=connection_id,
        )
    except TelegramAPIError:
        db.mark_reply(connection_id, message.chat.id, previous)
        log.warning("Business auto-reply failed for connection owner %s", owner)


@router.deleted_business_messages()
async def business_messages_deleted(event, bot: Bot):
    from aeniaflow.core.ui import panels

    key = (bot.id, event.business_connection_id, event.chat.id)
    saved = db.load_panel(*key)
    if saved:
        import json

        if json.loads(saved["message"]).get("message_id") in event.message_ids:
            panels.pop(key, None)
            db.conn.execute("DELETE FROM ui_panels WHERE bot_id=? AND connection_id=? AND chat_id=?", key)
