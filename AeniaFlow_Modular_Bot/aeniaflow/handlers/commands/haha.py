from aeniaflow.core.responses import respond
import random
from aiogram import Bot
from aiogram.types import Message


async def handle(message: Message, args: str, bot: Bot):
    try:
        n = max(1, min(10, int(args.strip() or "3")))
    except ValueError:
        n = 3
    await respond(message, "😂 " + " ".join("ха" * random.randint(2, 7) + "!" for _ in range(n)))
