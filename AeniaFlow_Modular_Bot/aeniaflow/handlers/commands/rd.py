from aeniaflow.core.responses import respond
import random
from aiogram import Bot
from aiogram.types import Message


async def handle(message: Message, args: str, bot: Bot):
    try:
        nums = [int(x) for x in args.split()] if args.strip() else [1, 100]
        if len(nums) == 1:
            nums = [1, nums[0]]
        if len(nums) != 2 or nums[0] > nums[1] or nums[1] - nums[0] > 10**9:
            raise ValueError
        await respond(message, f"🎲 {random.randint(nums[0],nums[1])}")
    except ValueError:
        await respond(message, "Использование: <code>.rd [мин] [макс]</code>")
