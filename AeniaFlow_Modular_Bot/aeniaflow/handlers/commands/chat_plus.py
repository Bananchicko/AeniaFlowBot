"""Useful non-AI private-chat tools; all changes are scoped to the owner."""

import time
from aeniaflow.core.runtime import db
from aeniaflow.core.helpers import esc
from aeniaflow.core.ui import panel, format_time
from aeniaflow.core.inputs import begin_input
from aeniaflow.core.responses import respond
from aeniaflow.core.scheduling import parse_duration
from aeniaflow.keyboards import kb

DIALOG_COMMANDS = {"tag", "later", "rules", "ruleadd", "ruledel", "autoread", "chatstats"}
PROMPTS = {
    "tag": "Введите метку до 32 символов. Например: работа. Удалить: off.",
    "later": "Через сколько отправить и какой текст? Например: 30m Привет! Буду через час. Одна отправка, максимум через 7 дней. Telegram должен разрешать ответ на момент отправки.",
    "ruleadd": "Ключевая фраза | ответ. Например: цена | Прайс пришлю сегодня. Фраза ищется в тексте без учёта регистра. До 20 правил в диалоге.",
    "ruledel": "Введите номер правила из .rules, которое нужно удалить.",
    "autoread": "Введите on для автоматического прочтения новых входящих или off для отключения. Нужно право чтения Business.",
}


async def apply(message, args, bot, command, row):
    owner = message.from_user.id
    if row["owner_id"] != owner:
        return
    back = f"dialog:open:{row['id']}"
    if not args and command in PROMPTS:
        begin_input(message, command, user_id=owner, mode="text", back=back)
        buttons = []
        if command == "autoread":
            buttons = [
                [
                    ("Включить", f"chatset:autoread:{row['id']}:on"),
                    ("Выключить", f"chatset:autoread:{row['id']}:off"),
                ]
            ]
        await panel(
            message,
            f"<b>{esc(row['peer_name'])}</b>\n<code>.{command}</code>\n\n{PROMPTS[command]}",
            kb(buttons + [[("‹ Назад", back)]]),
        )
        return
    if command == "tag":
        if len(args) > 32:
            raise ValueError("Метка до 32 символов.")
        db.update_dialog(owner, row["id"], "tag", "" if args.lower() == "off" else args)
        await respond(message, "Метка сохранена. Поиск по метке: <code>.chatfind метка</code>.")
    elif command == "later":
        delay, _, body = args.partition(" ")
        seconds = parse_duration(delay)
        if not 10 <= seconds <= 7 * 86400:
            raise ValueError("Отложенная отправка: от 10 секунд до 7 дней.")
        due = int(time.time()) + seconds
        identifier = db.queue_message(owner, row["id"], body.strip(), due)
        await respond(
            message,
            f"Сообщение #{identifier} запланировано на {format_time(due,db.get_user(owner)['timezone'])}.\nОчередь и отмена: <code>.outbox</code>. При обслуживании отправка приостанавливается.",
        )
    elif command == "rules":
        rules = db.conn.execute(
            "SELECT * FROM reply_rules WHERE owner_id=? AND dialog_id=? ORDER BY id", (owner, row["id"])
        ).fetchall()
        text = "<b>Ответы по ключевым словам</b>\n" + (
            "\n".join(f"#{r['id']} · {esc(r['keyword'])} → {esc(r['reply'][:100])}" for r in rules)
            or "Правил пока нет."
        )
        text += "\n\n<code>.ruleadd цена | Напишу вам сегодня</code>\n<code>.ruledel номер</code>\nПервое совпадение заменяет обычный автоответ. Интервал — из настроек автоответчика."
        await respond(
            message,
            text,
            reply_markup=kb(
                [
                    [
                        ("Добавить правило", f"chattool:ruleadd:{row['id']}"),
                        ("Удалить правило", f"chattool:ruledel:{row['id']}"),
                    ],
                    [("‹ Диалог", back)],
                ]
            ),
        )
    elif command == "ruleadd":
        key, sep, reply = args.partition("|")
        if not sep:
            raise ValueError("Формат: .ruleadd ключ | ответ")
        db.add_rule(owner, row["id"], key, reply.strip())
        await respond(message, "Правило сохранено. Список: <code>.rules</code>.")
    elif command == "ruledel":
        if not args.isdigit():
            raise ValueError("Введите номер правила из .rules.")
        changed = db.conn.execute(
            "DELETE FROM reply_rules WHERE id=? AND owner_id=? AND dialog_id=?", (int(args), owner, row["id"])
        ).rowcount
        await respond(message, "Правило удалено." if changed else "Правило не найдено в этом диалоге.")
    elif command == "autoread":
        if args not in {"on", "off"}:
            raise ValueError("Укажите on или off.")
        if args == "on":
            connection = await bot.get_business_connection(row["connection_id"])
            if (
                connection.user.id != owner
                or not connection.is_enabled
                or not connection.rights
                or not connection.rights.can_read_messages
            ):
                raise ValueError("Разрешите боту читать сообщения в настройках Business.")
        db.update_dialog(owner, row["id"], "autoread", int(args == "on"))
        await respond(message, "Автоматическое прочтение " + ("включено." if args == "on" else "выключено."))
    elif command == "chatstats":
        await respond(
            message,
            f"<b>Статистика диалога</b>\n{esc(row['peer_name'])}\n\nВходящих: {row['incoming_count']}\nИсходящих владельца: {row['outgoing_count']}\nПоследняя активность: {format_time(row['last_seen'],db.get_user(owner)['timezone'])}\n\nСчитаются только сообщения, полученные ботом с версии 2.8. История до подключения и собственные ответы бота не учитываются.",
        )


async def outbox(message, args, bot):
    owner = message.from_user.id
    if args:
        parts = args.split()
        if len(parts) != 2 or parts[0] != "cancel" or not parts[1].isdigit():
            raise ValueError("Отмена: .outbox cancel номер")
        db.conn.execute(
            "UPDATE scheduled_messages SET state='cancelled' WHERE id=? AND owner_id=? AND state='pending'",
            (int(parts[1]), owner),
        )
    rows = db.conn.execute(
        "SELECT s.*,d.peer_name FROM scheduled_messages s JOIN private_dialogs d ON d.id=s.dialog_id WHERE s.owner_id=? ORDER BY s.id DESC LIMIT 15",
        (owner,),
    ).fetchall()
    statuses = {
        "pending": "ожидает",
        "sent": "отправлено",
        "failed": "ошибка",
        "cancelled": "отменено",
        "sending": "отправляется",
        "uncertain": "результат неизвестен",
    }
    text = (
        "<b>Отложенные сообщения</b>\n\n"
        + (
            "\n".join(
                f"#{r['id']} · {esc(r['peer_name'])} · {format_time(r['due_at'],db.get_user(owner)['timezone'])}\n{statuses[r['state']]}"
                + (f" · {esc(r['error'])}" if r["error"] else "")
                for r in rows
            )
            or "Очередь пуста."
        )
        + "\n\nСоздать: <code>.later 30m текст</code>\nОтменить: <code>.outbox cancel номер</code>"
    )
    buttons = [
        [(f"Отменить #{r['id']}", f"outbox:cancel:{r['id']}")] for r in rows if r["state"] == "pending"
    ]
    await respond(message, text, reply_markup=kb(buttons + [[("‹ Plus", "list:plus:0")]]))


async def chatfind(message, args, bot):
    if not args:
        begin_input(message, "chatfind", mode="text")
        await respond(message, "Введите часть имени, username или метку собеседника.")
        return
    rows = db.conn.execute(
        "SELECT * FROM private_dialogs WHERE owner_id=? ORDER BY last_seen DESC", (message.from_user.id,)
    ).fetchall()
    found = [
        r
        for r in rows
        if args.casefold() in (r["peer_name"] + " " + r["username"] + " " + r["tag"]).casefold()
    ][:20]
    await respond(
        message,
        "<b>Поиск диалогов</b>\n" + ("Выберите собеседника." if found else "Совпадений нет."),
        reply_markup=kb(
            [[(r["peer_name"][:32], f"dialog:open:{r['id']}")] for r in found]
            + [[("Все чаты", "menu:chats")]]
        ),
    )


async def mail(message, args, bot, enabled):
    db.conn.execute("UPDATE users SET mail_enabled=? WHERE user_id=?", (int(enabled), message.from_user.id))
    await respond(
        message,
        "Рассылка " + ("включена. Отключить: .mailoff" if enabled else "отключена. Включить: .mailon"),
    )


async def mailoff(message, args, bot):
    await mail(message, args, bot, False)


async def mailon(message, args, bot):
    await mail(message, args, bot, True)


async def antimute(message, args, bot):
    if not args:
        begin_input(message, "antimute", mode="text")
        await respond(message, "Отправьте текст для одного сообщения. Команда: .antimute текст")
        return
    if len(args) > 3000:
        raise ValueError("До 3000 символов.")
    if message.business_connection_id:
        from aeniaflow.core.business_access import deletion_access

        await deletion_access(bot, message.from_user.id, message.business_connection_id)
    await message.answer(args, parse_mode=None)
    # Delete exactly the human input; never remove source media or unrelated messages.
    if message.business_connection_id:
        await bot.delete_business_messages(
            business_connection_id=message.business_connection_id, message_ids=[message.message_id]
        )
    else:
        await bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
