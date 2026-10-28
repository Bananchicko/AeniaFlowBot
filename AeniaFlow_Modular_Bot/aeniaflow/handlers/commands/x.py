import secrets
from aiogram import Bot
from aiogram.types import Message
from aeniaflow.core.runtime import db
from aeniaflow.keyboards import kb
from aeniaflow.core.ui import panel


def board_markup(board, game_id):
    return kb(
        [[(board[i], f"ttt:{game_id}:{i}") for i in row] for row in [(0, 1, 2), (3, 4, 5), (6, 7, 8)]]
        + [[("‹ Функции", "list:free:0"), ("Главное меню", "menu:home")]]
    )


async def handle(message: Message, args: str, bot: Bot):
    board = ["⬜"] * 9
    game_id = secrets.token_hex(4)
    sent = await panel(
        message,
        "<b>Крестики-нолики</b>\n<code>.x</code>\n\nВы — ❌, бот — ⭕.",
        reply_markup=board_markup(board, game_id),
    )
    db.save_game(
        "ttt",
        message.chat.id,
        message.from_user.id,
        {
            "id": game_id,
            "board": board,
            "message_id": sent.message_id,
            "business_connection_id": message.business_connection_id,
        },
    )
