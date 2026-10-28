"""Finite, paced message batches with a count picker and per-user cooldown."""

import asyncio
import time
from aeniaflow.core.runtime import db, BoundedCache
from aeniaflow.core.inputs import begin_input
from aeniaflow.core.ui import panel
from aeniaflow.keyboards import kb

active = {}
drafts = BoundedCache(1000)
INTERVAL = 0.5
COOLDOWN = 5


def parse_messages(args):
    value = args.strip()
    first, _, rest = value.partition(" ")
    if first.isdigit():
        count = int(first)
        if not 1 <= count <= 50 or not rest.strip():
            raise ValueError("Укажите от 1 до 50 сообщений и текст: .send 3 Привет!")
        messages = [rest.strip()] * count
    else:
        messages = [part.strip() for part in value.split("|")]
    if not 1 <= len(messages) <= 50 or any(not part or len(part) > 1000 for part in messages):
        raise ValueError("До 50 непустых сообщений, каждое до 1000 символов. Разделитель: |")
    if sum(map(len, messages)) > 50000:
        raise ValueError("В одной серии — до 50000 символов суммарно.")
    return messages


def context(message):
    return (message.bot.id, message.business_connection_id, message.chat.id, message.from_user.id)


async def choose_count(message, *, user=None, text="", edit=False):
    if user:
        message = message.model_copy(update={"from_user": user})
    drafts[context(message)] = (time.monotonic(), text)
    begin_input(message, "send", mode="text", back="list:free:0")
    await panel(
        message,
        "<b>Серия сообщений</b>\n<code>.send 3 Привет!</code>\n\nВыберите количество кнопкой или напишите число от 1 до 50. Затем отправьте текст.\n\nПауза — 0,5 секунды. После выбранного количества серия завершится сама. Следующая серия — не раньше чем через 5 секунд.",
        kb(
            [[(str(n), f"sendcount:{n}") for n in group] for group in ((1, 5, 10), (20, 30, 50))]
            + [[("‹ Назад", "list:free:0"), ("Главное меню", "menu:home")]]
        ),
        edit=edit,
    )


async def select_count(message, count, bot):
    if not 1 <= count <= 50:
        raise ValueError("Количество: от 1 до 50.")
    draft = drafts.pop(context(message), None)
    if draft and time.monotonic() - draft[0] < 600 and draft[1]:
        await send(message, f"{count} {draft[1]}", bot)
        return
    begin_input(message, "send", str(count), mode="text", back="list:free:0")
    await panel(
        message,
        f"<b>Серия сообщений</b>\n<code>.send {count} Текст</code>\n\nКоличество: <b>{count}</b>. Теперь отправьте текст одним сообщением.",
        kb([[("Изменить количество", "use:send"), ("Главное меню", "menu:home")]]),
    )


async def send(message, args, bot):
    if not args:
        await choose_count(message)
        return
    if args.strip().isdigit():
        await select_count(message, int(args), bot)
        return
    if not args.split()[0].isdigit() and "|" not in args:
        if len(args) > 1000:
            raise ValueError("Текст одного сообщения — до 1000 символов.")
        await choose_count(message, text=args)
        return
    messages = parse_messages(args)
    key = context(message)
    if any(item[-1] == message.from_user.id for item in active):
        raise ValueError("У вас уже идёт серия. Она завершится автоматически.")
    last = float(db.get_setting(message.from_user.id, "last_series", "0"))
    if time.time() - last < COOLDOWN:
        raise ValueError("Следующую серию можно отправить через 5 секунд после завершения предыдущей серии.")
    active[key] = True
    db.set_setting(message.from_user.id, "last_series", str(time.time()))
    try:
        for index, text in enumerate(messages):
            from aeniaflow.core.policy import gate

            if not await gate(message, message.from_user, bot, "send"):
                return
            await message.answer(text, parse_mode=None)
            if index < len(messages) - 1:
                await asyncio.sleep(INTERVAL)
    finally:
        db.set_setting(message.from_user.id, "last_series", str(time.time()))
        active.pop(key, None)
