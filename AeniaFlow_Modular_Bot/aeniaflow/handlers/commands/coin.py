from aeniaflow.core.responses import respond
import random
from aiogram import Bot
from aiogram.types import Message


async def handle(message: Message, args: str, bot: Bot):
    await respond(message, "🪙 Орёл!" if random.choice([True, False]) else "🪙 Решка!")
