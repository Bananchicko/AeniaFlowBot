from aiogram import Bot
from aiogram.types import Message
from aeniaflow.handlers.system.sections import show_section


async def handle(message: Message, args: str, bot: Bot):
    if message.from_user:
        section = "premium" if "catalog" == "start" and args == "premium" else "catalog"
        await show_section(message, bot, message.from_user, section, args)
