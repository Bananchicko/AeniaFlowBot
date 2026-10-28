from aeniaflow.core.responses import respond
import re
from aiogram import Bot
from aiogram.types import Message
from aeniaflow.core.runtime import db
from aeniaflow.core.games import score_word


async def handle(message: Message, args: str, bot: Bot):
    user, chat = message.from_user.id, message.chat.id
    game = db.game("word", chat, user)
    guess = args.strip().lower().replace("ё", "е")
    if not game or game.get("business_connection_id") != message.business_connection_id:
        await respond(message, "Начните игру: <code>.word</code>.")
        return
    if not re.fullmatch("[а-я]{5}", guess):
        raise ValueError("Нужно русское слово ровно из 5 букв.")
    answer = game["answer"]
    game["turns"] += 1
    marks = score_word(answer, guess)
    if guess == answer or game["turns"] >= 6:
        db.delete_game("word", chat, user)
        await respond(
            message,
            ("Победа! " if guess == answer else "Попытки закончились. Слово: ") + answer + "\n" + marks,
        )
    else:
        db.save_game("word", chat, user, game)
        await respond(message, f'{marks}\nПопытка {game["turns"]}/6')
