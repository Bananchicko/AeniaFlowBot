from config import settings
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aeniaflow.catalog import PLANS, PREMIUM_CODES
from aeniaflow.core.navigation import tool_page, tool_name, tool_return


def kb(rows):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=item[0], callback_data=item[1], style=item[2] if len(item) > 2 else None
                )
                for item in row
            ]
            for row in rows
            if row
        ]
    )


def main_keyboard(*, needs_connection=False):
    return kb(
        [
            [("Базовые функции", "list:free:0", "primary"), ("Plus функции", "list:plus:0", "primary")],
            [("Профиль", "menu:profile")],
        ]
        + ([[("Подключить ЛС · инструкция", "menu:connect", "primary")]] if needs_connection else [])
    )


def catalog_keyboard():
    return feature_keyboard()


def feature_keyboard(premium=False, page=0, category=None):
    mode = "plus" if premium else "free"
    codes, page, total = tool_page(mode, page)
    buttons = [(tool_name(code), f"run:{code}:{mode}:{page}") for code in codes]
    rows = [buttons[i : i + 2] for i in range(0, len(buttons), 2)]
    rows += [
        [
            ("‹", f"list:{mode}:{page-1}" if page else "nav:first"),
            (f"{page+1} / {total}", "nav:page"),
            ("›", f"list:{mode}:{page+1}" if page + 1 < total else "nav:last"),
        ],
        [
            ("Поиск", "input:find"),
            ("Базовые функции" if premium else "Plus функции", "list:free:0" if premium else "list:plus:0"),
        ],
        [("‹ Главное меню", "menu:home")],
    ]
    return kb(rows)


def plans_keyboard():
    options = [(f"{p['label']} · {p['stars']} ⭐", f"plan:{code}") for code, p in PLANS.items()]
    rows = [options[i : i + 2] for i in range(0, len(options), 2)]
    return kb(
        rows
        + [
            [("Plus функции", "list:plus:0"), ("Мои платежи", "menu:payments")],
            [("Условия", "menu:terms"), ("Поддержка", "menu:paysupport")],
            [("‹ Профиль", "menu:profile")],
        ]
    )


def feature_detail_keyboard(code):
    from aeniaflow.handlers.system.actions import ACTIONS

    rows = [[("Использовать", f"use:{code}", "primary")]] if code in ACTIONS else []
    if code == "wm":
        rows.insert(0, [("Количество и стиль", "menu:watermark", "primary")])
    if code in PREMIUM_CODES:
        rows.append([("⭐ Подписка", "menu:premium")])
    rows.append([("‹ Функции", tool_return(code)), ("Главное меню", "menu:home")])
    return kb(rows)


def back_keyboard(section="home", label="Главное меню"):
    return kb([[("‹ " + label, "menu:" + section)]])


def pager(section, page, has_next):
    row = []
    if page > 1:
        row.append(("‹ Назад", f"page:{section}:{page-1}"))
    if has_next:
        row.append(("Дальше ›", f"page:{section}:{page+1}"))
    return row


def support_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Написать " + settings.support_username,
                    url=f"https://t.me/{settings.support_username}",
                    style="primary",
                )
            ],
            [InlineKeyboardButton(text="Канал AeniaFlow", url="https://t.me/AeniaFlow")],
            [
                InlineKeyboardButton(text="Мои платежи", callback_data="menu:payments"),
                InlineKeyboardButton(text="‹ Профиль", callback_data="menu:profile"),
            ],
        ]
    )
