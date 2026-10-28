from aeniaflow.core.responses import respond
from aeniaflow.keyboards import kb
import random
from aiogram import Bot
from aiogram.types import Message

WORDS = [
    "лампа",
    "книга",
    "ветер",
    "океан",
    "парус",
    "школа",
    "поезд",
    "земля",
    "сосна",
    "волна",
    "маска",
    "арбуз",
    "тропа",
    "сахар",
    "город",
    "сфера",
    "майка",
    "берег",
    "карта",
    "полка",
]


async def handle(message: Message, args: str, bot: Bot):
    from aeniaflow.core.runtime import db

    word = random.choice(WORDS)
    db.save_game(
        "word",
        message.chat.id,
        message.from_user.id,
        {"answer": word, "turns": 0, "business_connection_id": message.business_connection_id},
    )
    await respond(
        message,
        "Wordle: русское слово из 5 букв, 6 попыток. Введите <code>.guess слово</code>. Игра сохраняется на сутки.",
        reply_markup=kb([[("Ввести слово", "input:guess"), ("Главное меню", "menu:home")]]),
    )
