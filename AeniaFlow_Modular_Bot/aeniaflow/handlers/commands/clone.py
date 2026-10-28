from aeniaflow.core.responses import respond
from aeniaflow.core.helpers import esc


async def handle(message, args, bot):
    if args.strip():
        raise ValueError("Напишите .clone без аргументов в нужном диалоге.")
    person = message.chat if message.business_connection_id else message.from_user
    username = "@" + person.username if person.username else "не указан"
    await respond(
        message,
        f"<b>Карточка собеседника</b>\nИмя: {esc(person.full_name or 'Собеседник')}\nUsername: {esc(username)}",
    )
