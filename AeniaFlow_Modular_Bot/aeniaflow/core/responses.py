"""Plain function results, separate from the reusable navigation menu."""

from contextvars import ContextVar
from aeniaflow.keyboards import kb
from aeniaflow.core.navigation import action_return

current_action = ContextVar("current_action", default=None)


def controls(command):
    return kb([[("‹ Назад", action_return(command)), ("Главное меню", "menu:home")]])


async def respond(message, text, reply_markup=None, *, parse_mode="HTML", protect_content=False, **kwargs):
    # Function output is separate from navigation: no automatic banner or menu.
    from html import unescape
    import re
    from aeniaflow.core.legal_pages import split_pages

    plain = unescape(re.sub(r"<[^>]+>", "", text)) if parse_mode == "HTML" else text
    if len(plain.encode("utf-16-le")) // 2 > 4096:
        chunks = split_pages(plain, limit=4000)
        result = None
        for index, chunk in enumerate(chunks):
            result = await message.answer(
                chunk,
                reply_markup=reply_markup if index == len(chunks) - 1 else None,
                parse_mode=None,
                protect_content=protect_content,
                **kwargs,
            )
        return result
    return await message.answer(
        text, reply_markup=reply_markup, parse_mode=parse_mode, protect_content=protect_content, **kwargs
    )
