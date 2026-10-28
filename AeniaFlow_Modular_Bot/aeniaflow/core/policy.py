"""One access policy for commands, buttons and background actions."""

from config import settings
from aeniaflow.core.runtime import db
from aeniaflow.core.access import has_plus, is_owner
from aeniaflow.core.ui import panel
from aeniaflow.core.helpers import esc
from aeniaflow.keyboards import kb

ESSENTIAL = {"paysupport", "terms", "privacy", "payments", "export", "delete_data", "mailoff", "mailon"}
PURCHASE = {"premium", "plan", "pay", "subscribe", "checksub"}


def maintenance():
    return db.runtime_option("maintenance", "0") == "1"


def banned(user):
    row = db.get_user(user)
    return bool(row and row["banned"])


def required_channel(config=None):
    config = config or settings
    return db.runtime_option("required_channel") or config.news_channel or "@AeniaFlow"


def channel_url(config=None):
    config = config or settings
    channel = required_channel(config)
    if isinstance(channel, str) and channel.startswith("@"):
        return "https://t.me/" + channel[1:]
    return config.news_channel_url or "https://t.me/AeniaFlow"


async def membership(bot, user, config=None):
    if has_plus(user):
        return True
    member = await bot.get_chat_member(required_channel(config), user)
    return (
        member.status in {"member", "administrator", "creator"}
        or member.status == "restricted"
        and member.is_member
    )


async def subscription_prompt(message, *, edit=False, fresh=False):
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Открыть канал", url=channel_url())],
            [InlineKeyboardButton(text="Проверить подписку", callback_data="sub:check")],
            [InlineKeyboardButton(text="Plus без подписки на канал", callback_data="menu:premium")],
            [InlineKeyboardButton(text="Поддержка", callback_data="menu:paysupport")],
        ]
    )
    await panel(
        message,
        "<b>Подпишитесь для работы</b>\n\nДля бесплатных функций нужна подписка на канал бота. Подпишитесь и нажмите «Проверить подписку».\n\nПользователям Plus подписываться необязательно.",
        markup,
        edit=edit,
        fresh=fresh,
    )


async def gate(message, user, bot, action="", *, edit=False, fresh=False):
    if action in ESSENTIAL:
        return True
    if banned(user.id):
        row = db.get_user(user.id)
        reason = "\nПричина: " + esc(row["ban_reason"]) if row["ban_reason"] else ""
        await panel(
            message,
            "<b>Доступ к боту заблокирован</b>"
            + reason
            + "\nОбратиться к администратору можно через поддержку.",
            kb([[("Поддержка", "menu:paysupport")]]),
            edit=edit,
            fresh=fresh,
        )
        return False
    if maintenance():
        buttons = [[("Поддержка", "menu:paysupport")]]
        if is_owner(user.id) and not message.business_connection_id:
            buttons.insert(0, [("Админ-панель", "admin:view:home")])
        await panel(
            message,
            "<b>Бот на обслуживании</b>\n\nФункции и фоновые отправки временно приостановлены. Попробуйте позже.",
            kb(buttons),
            edit=edit,
            fresh=fresh,
        )
        return False
    if action in PURCHASE:
        return True
    from aeniaflow.handlers.system.sections import channel_check

    if not await channel_check(bot, user.id):
        await subscription_prompt(message, edit=edit, fresh=fresh)
        return False
    return True


def callback_action(data):
    parts = data.split(":")
    if parts[0] == "menu":
        return parts[1]
    if parts[0] in {"pay", "plan"}:
        return "pay"
    if data == "sub:check":
        return "checksub"
    if parts[0] in {"run", "use", "input", "chattool", "chatpick", "chatset"} and len(parts) > 1:
        return parts[1]
    if data.startswith("delete_data:"):
        return "delete_data"
    if data.startswith("export:"):
        return "export"
    if data.startswith("mail:"):
        return "mailoff"
    if data.startswith("legal:"):
        return parts[1]
    if data.startswith("page:payments:"):
        return "payments"
    return ""
