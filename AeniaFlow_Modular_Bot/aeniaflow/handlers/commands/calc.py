from aeniaflow.core.responses import respond
from aiogram import Bot
from aiogram.types import Message
from aeniaflow.core.helpers import esc
from aeniaflow.core.calculator import safe_eval


async def handle(message: Message, args: str, bot: Bot):
    try:
        await respond(message, f"🧮 <code>{esc(safe_eval(args))}</code>")
    except (ValueError, SyntaxError, ZeroDivisionError, OverflowError) as exc:
        await respond(message, f"Не удалось вычислить: {esc(exc)}")
