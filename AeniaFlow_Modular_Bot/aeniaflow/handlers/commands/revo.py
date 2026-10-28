from aeniaflow.core.responses import respond
import random
from aiogram import Bot
from aiogram.types import Message


async def handle(message: Message, args: str, bot: Bot):
    await respond(
        message,
        (
            "🔫 Щёлк… пусто. Раунд продолжается."
            if random.randint(1, 6) != 1
            else "🎲 Раунд проигран! Это только случайная мини-игра; никаких реальных действий не выполняется."
        ),
    )
