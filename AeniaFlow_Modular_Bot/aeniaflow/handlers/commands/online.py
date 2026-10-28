from aeniaflow.core.responses import respond
from aiogram import Bot
from aiogram.types import Message


async def handle(message: Message, args: str, bot: Bot):
    await respond(
        message,
        "Telegram Bot API не позволяет удерживать личный аккаунт пользователя в статусе «онлайн». Бот не будет имитировать такую возможность.",
    )
