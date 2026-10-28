"""Owner-scoped saved replies and controls for individual human conversations."""

import re
from aeniaflow.core.runtime import db
from aeniaflow.core.helpers import esc
from aeniaflow.core.ui import panel
from aeniaflow.core.responses import respond
from aeniaflow.core.inputs import begin_input, pending_input
from aeniaflow.core.business_access import current_dialog
from aeniaflow.keyboards import kb

from aeniaflow.handlers.commands import chat_plus

DIALOG_COMMANDS = chat_plus.DIALOG_COMMANDS | {"chatnote", "chatinfo", "chatauto", "pause", "resume", "read"}


def selected(message):
    if message.business_connection_id:
        return current_dialog(message)
    pending = pending_input(message)
    if pending and pending[3] and pending[3].startswith("dialog:open:"):
        return db.dialog(message.from_user.id, int(pending[3].split(":")[-1]))
    return None


async def choose_dialog(message, command, *, user=None, edit=False, page=0):
    user = user or message.from_user
    if command not in DIALOG_COMMANDS:
        return
    rows = db.dialogs(user.id, max(0, page) * 8)
    buttons = [[(row["peer_name"][:32], f"chattool:{command}:{row['id']}")] for row in rows]
    nav = []
    if page > 0:
        nav.append(("‹", f"chatpick:{command}:{page-1}"))
    if db.dialogs(user.id, (page + 1) * 8):
        nav.append(("›", f"chatpick:{command}:{page+1}"))
    buttons += [nav, [("‹ Функции", "list:free:0"), ("Главное меню", "menu:home")]]
    await panel(
        message,
        f"<b>Выберите собеседника</b>\n<code>.{command}</code>\n\n"
        + (
            "Действие будет применено к выбранному диалогу."
            if rows
            else "Чаты появятся после входящих сообщений от людей в подключённых ЛС."
        ),
        kb(buttons),
        edit=edit,
    )


async def apply_dialog(message, args, bot, command, row=None):
    row = row or selected(message)
    if not row:
        await choose_dialog(message, command)
        return
    owner = message.from_user.id
    if row["owner_id"] != owner:
        return
    if command in chat_plus.DIALOG_COMMANDS:
        await chat_plus.apply(message, args, bot, command, row)
        return
    back = f"dialog:open:{row['id']}"
    if command == "chatinfo":
        from aeniaflow.handlers.system.dialogs import show_dialog

        await show_dialog(message, owner, row["id"], edit=False)
        return
    if command in {"chatnote", "chatauto"}:
        field = "note" if command == "chatnote" else "reply_text"
        if not args:
            begin_input(message, command, user_id=owner, mode="text", back=back)
            text = (
                "Напишите пометку о собеседнике. Она хранится в вашем профиле. Введённый вами текст в Business видит собеседник; для личной пометки используйте ЛС самого бота."
                if command == "chatnote"
                else "Отправьте текст персонального автоответа. Он заменит общий автоответ и AFK для этого собеседника. Интервал — из настроек автоответчика."
            )
            await panel(
                message,
                f"<b>{esc(row['peer_name'])}</b>\n<code>.{command} текст</code>\n\n{text}\n\nУдалить: <code>.{command} off</code>",
                kb([[("‹ Назад", back), ("Главное меню", "menu:home")]]),
            )
            return
        if len(args) > 1000:
            raise ValueError("Максимум 1000 символов.")
        db.update_dialog(owner, row["id"], field, "" if args.lower() == "off" else args)
        await respond(
            message,
            (
                "Пометка сохранена."
                if command == "chatnote"
                else (
                    "Персональный автоответ выключен."
                    if args.lower() == "off"
                    else "Персональный автоответ сохранён."
                )
            ),
        )
    elif command in {"pause", "resume"}:
        db.update_dialog(owner, row["id"], "paused", int(command == "pause"))
        await respond(
            message,
            (
                "Обработка этого ЛС приостановлена: мут и автоответы не выполняются. Возобновить: <code>.resume</code> или кнопкой в профиле."
                if command == "pause"
                else "Обработка этого ЛС возобновлена."
            ),
        )
    elif command == "read":
        if not row["last_incoming_id"]:
            raise ValueError("Бот ещё не получил входящее сообщение в этом диалоге.")
        actual = await bot.get_business_connection(row["connection_id"])
        if (
            actual.user.id != owner
            or not actual.is_enabled
            or not actual.rights
            or not actual.rights.can_read_messages
        ):
            raise ValueError("Разрешите чтение сообщений в настройках Telegram Business для этого бота.")
        await bot.read_business_message(
            business_connection_id=row["connection_id"],
            chat_id=row["chat_id"],
            message_id=row["last_incoming_id"],
        )
        await respond(message, "Входящие отмечены прочитанными.")


async def replies(message, args, bot):
    rows = db.saved_replies(message.from_user.id)
    text = "<b>Быстрые ответы</b>\n\n" + (
        "\n".join(f"<code>.reply {esc(row['name'])}</code> · {esc(row['text'][:65])}" for row in rows)
        or "Пока нет сохранённых ответов."
    )
    text += "\n\nДобавить: <code>.replyadd название | текст</code>\nУдалить: <code>.replydel название</code>"
    await respond(message, text)


async def replyadd(message, args, bot):
    name, separator, text = args.partition("|")
    name, text = name.strip().lower(), text.strip()
    if not separator or not re.fullmatch(r"[\w-]{1,32}", name) or not text or len(text) > 3000:
        raise ValueError(
            "Пример: .replyadd привет | Привет! Скоро отвечу. Название — до 32 символов без пробелов, текст — до 3000."
        )
    db.save_reply(message.from_user.id, name, text)
    await respond(message, f"Сохранено. Отправить: <code>.reply {esc(name)}</code>")


async def reply(message, args, bot):
    row = db.saved_reply(message.from_user.id, args.strip().lower())
    if not row:
        raise ValueError("Ответ не найден. Список: .replies")
    await message.answer(row["text"], parse_mode=None)


async def replydel(message, args, bot):
    removed = db.delete_reply(message.from_user.id, args.strip().lower())
    await respond(message, "Ответ удалён." if removed else "Ответ не найден.")


def dialog_handler(command):
    async def handle(message, args, bot):
        await apply_dialog(message, args, bot, command)

    return handle


COMMANDS = {code: dialog_handler(code) for code in DIALOG_COMMANDS}
COMMANDS.update(replies=replies, replyadd=replyadd, reply=reply, replydel=replydel)

COMMANDS.update(
    outbox=chat_plus.outbox, chatfind=chat_plus.chatfind, mailoff=chat_plus.mailoff, mailon=chat_plus.mailon
)
