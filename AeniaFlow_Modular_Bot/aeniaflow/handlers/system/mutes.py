"""A mute lasts until its owner turns it off. Both notices reflect the same DB state."""

import logging
import asyncio
from weakref import WeakValueDictionary
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aeniaflow.core.business_access import deletion_access
from aeniaflow.core.helpers import esc
from aeniaflow.core.runtime import db
from aeniaflow.core.command_ui import remove_command
from aeniaflow.keyboards import kb
from aeniaflow.core.access import protected_from_mute

log = logging.getLogger(__name__)
_locks = WeakValueDictionary()


def mute_lock(identifier):
    lock = _locks.get(identifier)
    if lock is None:
        lock = asyncio.Lock()
        _locks[identifier] = lock
    return lock


def notice_text(row, *, personal=False):
    heading = f"\n\n{esc(row['peer_name'])}" if personal else ""
    return (
        f"<b>✓ Готово · мут включён</b>{heading}\n\nНовые входящие сообщения удаляются.\nБез срока — до нажатия «Размутить»."
        if row["muted"]
        else f"<b>✓ Готово · мут снят</b>{heading}\n\nНовые входящие больше не удаляются."
    )


def notice_keyboard(row, *, personal=False):
    rows = [[("Размутить", f"mute:off:{row['id']}", "success")]] if row["muted"] else []
    return kb(rows) if rows else None


async def update_notice(bot, row, *, personal=False, create=True, fresh=False, extra=""):
    connection = db.connection_owner(row["connection_id"])
    if not connection or connection["owner_id"] != row["owner_id"]:
        return False
    mid = row["owner_message_id"] if personal else row["mute_message_id"]
    chat_id = (connection["user_chat_id"] or row["owner_id"]) if personal else row["chat_id"]
    business = {} if personal else {"business_connection_id": row["connection_id"]}
    text, markup = notice_text(row, personal=personal), notice_keyboard(row, personal=personal)
    if extra:
        text += "\n\n" + esc(extra)
    if mid and not fresh:
        try:
            await bot.edit_message_text(
                text, chat_id=chat_id, message_id=mid, reply_markup=markup, parse_mode="HTML", **business
            )
            return True
        except TelegramBadRequest as exc:
            if "message is not modified" in exc.message.lower():
                return True
        except TelegramAPIError:
            log.warning("Could not update mute notice for owner %s", row["owner_id"])
    if not create:
        return False
    try:
        sent = await bot.send_message(chat_id, text, reply_markup=markup, parse_mode="HTML", **business)
    except TelegramAPIError:
        log.warning("Could not send mute notice for owner %s", row["owner_id"])
        return False
    db.save_mute_notice(row["owner_id"], row["id"], sent.message_id, personal=personal)
    if mid and fresh:
        try:
            if personal:
                await bot.delete_message(chat_id=chat_id, message_id=mid)
            else:
                await bot.delete_business_messages(
                    business_connection_id=row["connection_id"], message_ids=[mid]
                )
        except TelegramAPIError:
            try:
                await bot.edit_message_reply_markup(
                    chat_id=chat_id, message_id=mid, reply_markup=None, **business
                )
            except TelegramAPIError:
                pass
    return True


async def enable_mute(bot, row, *, command=None):
    async with mute_lock(row["id"]):
        row = db.dialog(row["owner_id"], row["id"])
        if not row:
            return
        label = protected_from_mute(row["owner_id"], row["chat_id"])
        if label:
            raise ValueError(f"Данный пользователь — {label} и защищён от мута.")
        await deletion_access(bot, row["owner_id"], row["connection_id"])
        db.set_private_mute(row["owner_id"], row["id"], True)
        current = db.dialog(row["owner_id"], row["id"])
        cleanup_failed = command is not None and not await remove_command(command, bot)
        peer_updated = await update_notice(bot, current, fresh=command is not None)
        details = []
        if cleanup_failed:
            details.append("Мут включён, но Telegram не разрешил удалить сообщение с командой.")
        if not peer_updated:
            details.append("Telegram не разрешил показать подтверждение в диалоге. Снять мут можно здесь.")
        await update_notice(bot, current, personal=True, extra=" ".join(details))


async def disable_mute(bot, row, *, command=None):
    async with mute_lock(row["id"]):
        row = db.dialog(row["owner_id"], row["id"])
        if not row:
            return
        # Turning off local deletion must remain possible after Business rights are revoked.
        db.set_private_mute(row["owner_id"], row["id"], False)
        current = db.dialog(row["owner_id"], row["id"])
        cleanup_failed = command is not None and not await remove_command(command, bot)
        peer_updated = await update_notice(
            bot, current, create=command is not None, fresh=command is not None
        )
        await update_notice(
            bot,
            current,
            personal=True,
            create=False,
            extra="Мут снят, но Telegram не разрешил удалить сообщение с командой." if cleanup_failed else "",
        )
        return peer_updated
