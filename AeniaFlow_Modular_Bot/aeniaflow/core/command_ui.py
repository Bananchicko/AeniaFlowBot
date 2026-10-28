"""Remove only the human's command message, never source media or a menu."""

import logging
from aiogram.exceptions import TelegramAPIError
from aeniaflow.core.runtime import db
from aeniaflow.core.inputs import media_file

log = logging.getLogger(__name__)


async def remove_command(message, bot):
    if (
        message.chat.type != "private"
        or not message.from_user
        or message.from_user.is_bot
        or not message.text
        or not message.text.lstrip().startswith((".", "/"))
        or media_file(message)
    ):
        return False
    connection_id = message.business_connection_id
    if connection_id:
        connection = db.connection_owner(connection_id)
        if not connection or not connection["is_enabled"] or connection["owner_id"] != message.from_user.id:
            return False
        if not connection["can_delete_all_messages"]:
            return False
    elif message.chat.id != message.from_user.id:
        return False
    try:
        if connection_id:
            await bot.delete_business_messages(
                business_connection_id=connection_id, message_ids=[message.message_id]
            )
            db.conn.execute(
                "DELETE FROM private_messages WHERE message_id=? AND dialog_id IN "
                "(SELECT id FROM private_dialogs WHERE owner_id=? AND connection_id=? AND chat_id=?)",
                (message.message_id, message.from_user.id, connection_id, message.chat.id),
            )
        else:
            await bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
        return True
    except TelegramAPIError:
        # A display cleanup failure must not roll back a completed action.
        log.info("Command cleanup unavailable in chat %s", message.chat.id)
        return False
