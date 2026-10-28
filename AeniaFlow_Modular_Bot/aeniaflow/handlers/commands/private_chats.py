from aeniaflow.core.runtime import db
from aeniaflow.core.business_access import current_dialog, deletion_access
from aeniaflow.handlers.system.mutes import enable_mute, disable_mute
from aeniaflow.core.responses import respond


async def mute(message, args, bot):
    if args.strip():
        raise ValueError(
            "Мут теперь без срока. Напишите .mute без аргументов. Снять — кнопкой «Размутить» или командой .unmute."
        )
    if not message.business_connection_id:
        from aeniaflow.handlers.system.dialogs import show_dialogs

        await show_dialogs(message, message.from_user.id)
        return
    row = current_dialog(message)
    await enable_mute(bot, row, command=message)


async def unmute(message, args, bot):
    if args.strip():
        raise ValueError("Напишите .unmute без аргументов в нужном диалоге.")
    if not message.business_connection_id:
        from aeniaflow.handlers.system.dialogs import show_dialogs

        await show_dialogs(message, message.from_user.id, muted=True)
        return
    row = current_dialog(message)
    updated = await disable_mute(bot, row, command=message)
    if not updated:
        await respond(message, "Мут снят. Новые сообщения больше не удаляются.")


async def panic(message, args, bot):
    value = args.strip() or "20"
    if not value.isdigit() or not 1 <= int(value) <= 100:
        raise ValueError("Очистка: .panic 20 — от 1 до 100 недавних сообщений в текущем диалоге.")
    row = current_dialog(message)
    await deletion_access(bot, row["owner_id"], row["connection_id"])
    identifiers = db.recent_private_messages(row["owner_id"], row["id"], int(value))
    if not identifiers:
        await respond(message, "Нет недавних сообщений, полученных ботом. История до подключения недоступна.")
        return
    await bot.delete_business_messages(business_connection_id=row["connection_id"], message_ids=identifiers)
    db.conn.executemany(
        "DELETE FROM private_messages WHERE dialog_id=? AND message_id=?",
        [(row["id"], mid) for mid in identifiers],
    )
    await respond(
        message,
        f"Очистка выполнена для {len(identifiers)} сообщений из доступной боту истории за последние сутки.",
    )
