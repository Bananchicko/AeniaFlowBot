"""Validate the human owner and refresh Telegram Business rights before moderation."""

from aeniaflow.core.runtime import db
import time
from aiogram.exceptions import TelegramAPIError


def save_business_connection(connection):
    rights = connection.rights
    db.upsert_user(connection.user)
    db.save_connection(
        connection.id,
        connection.user.id,
        connection.is_enabled,
        bool(rights and rights.can_reply),
        can_delete_all_messages=bool(rights and rights.can_delete_all_messages),
        can_delete_sent_messages=bool(rights and rights.can_delete_sent_messages),
        user_chat_id=connection.user_chat_id,
    )


async def refresh_connection(bot, owner, connection_id=None, *, force=False):
    cached = db.connection_owner(connection_id) if connection_id else db.get_connection(owner)
    if not cached or cached["owner_id"] != owner:
        return None
    if not force and time.time() - cached["checked_at"] < 60:
        return cached
    try:
        actual = await bot.get_business_connection(cached["connection_id"])
    except TelegramAPIError:
        return cached
    if actual.id != cached["connection_id"] or actual.user.id != owner:
        return None
    save_business_connection(actual)
    return db.connection_owner(actual.id)


def human_dialog(message):
    """Reject identified bots without requiring a new incoming message after install.

    An outgoing Message contains the owner's User, not the recipient's User.
    Missing peer data is therefore not evidence that the recipient is a bot.
    Never persist an inferred is_bot=False: only Telegram User objects establish it.
    """
    if not message.business_connection_id:
        return True
    sender = message.from_user
    if sender and sender.id == message.chat.id:
        db.remember_peer(sender)
    peer = db.peer_type(message.chat.id)
    if peer is not None:
        return peer is False
    source = message.reply_to_message
    if source and source.from_user and source.from_user.id == message.chat.id:
        db.remember_peer(source.from_user)
        return not source.from_user.is_bot
    # With no User object, exclude conventional bot usernames as a best-effort
    # filter. A known human User takes precedence over this naming heuristic.
    return not (message.chat.username or "").lower().endswith("bot")


async def deletion_access(bot, owner, connection_id):
    cached = db.connection_owner(connection_id)
    if not cached or cached["owner_id"] != owner:
        raise ValueError("Это подключение недоступно.")
    actual = await bot.get_business_connection(connection_id)
    if actual.id != connection_id or actual.user.id != owner:
        raise ValueError("Это подключение недоступно.")
    save_business_connection(actual)
    if not actual.is_enabled:
        raise ValueError("Подключение Business отключено. Включите его в настройках Telegram.")
    if not actual.rights or not actual.rights.can_delete_all_messages:
        raise ValueError(
            "Для мута и очистки разрешите боту удалять все сообщения в настройках Telegram Business → Чат-боты."
        )
    return actual


def current_dialog(message):
    connection_id = message.business_connection_id
    if message.chat.type != "private" or not connection_id:
        raise ValueError(
            "Напишите команду в личном диалоге с собеседником. В боте управление доступно через Профиль → Чаты."
        )
    row = db.connection_owner(connection_id)
    if not row or not row["is_enabled"] or row["owner_id"] != message.from_user.id:
        raise ValueError("Команду может выполнить только владелец подключения Business.")
    return db.remember_dialog(row["owner_id"], connection_id, message.chat)
