"""Native Telegram screens; the actor is always passed explicitly."""

from __future__ import annotations
from aiogram import Bot
from aiogram.types import Message, User
from config import settings
from aeniaflow.core.ai_service import available as ai_available
from aeniaflow.core.ffmpeg import ffmpeg_binary
from aeniaflow.catalog import PLANS
from aeniaflow.core.navigation import tool_page, tool_name
from aeniaflow.core.command_help import with_command
from aeniaflow.keyboards import (
    main_keyboard,
    feature_keyboard,
    plans_keyboard,
    kb,
    back_keyboard,
    pager,
    support_keyboard,
)
from aeniaflow.core.runtime import LEGAL, db
from aeniaflow.core.helpers import esc
from aeniaflow.core.ui import format_time, private_only, panel
from aeniaflow.core.access import is_owner
from aeniaflow.core.business_access import refresh_connection


async def channel_check(bot: Bot, user_id: int) -> bool:
    from aeniaflow.core.policy import membership

    return await membership(bot, user_id, settings)


async def show_section(
    message: Message, bot: Bot, user: User, section: str, args: str = "", *, edit=False, fresh=False
):
    # Old messages and saved commands keep working without reviving the category tree.
    if section == "catalog" or section.startswith("category:"):
        section = "free"
    elif section == "organizer":
        section = "profile"
    personal = {
        "profile",
        "settings",
        "payments",
        "autoreply",
        "organizer",
        "notes",
        "tasks",
        "reminders",
        "chats",
        "mutelist",
        "data",
    }
    if not await private_only(message, user):
        return
    db.upsert_user(user)
    markup = back_keyboard()
    text = ""
    if section in {"home", "start", "menu"}:
        connection = await refresh_connection(bot, user.id, message.business_connection_id)
        needs_connection = False
        text = (
            "<b>AeniaFlow</b>\n\n"
            "Выберите функции и нажмите нужную кнопку.\n"
            "Бот подскажет, что отправить.\n\n"
            "Чаты, муты и настройки — в <b>профиле</b>."
        )
        if connection and connection["is_enabled"]:
            text += (
                "\n\nЛичные чаты подключены."
                if connection["can_reply"]
                else "\n\nЛС подключены. Проверьте право ответа в профиле."
            )
        markup = main_keyboard(needs_connection=needs_connection)
    elif section in {"free", "plus"}:
        codes, page, _ = tool_page(section, args or 0)
        title = "Plus функции" if section == "plus" else "Базовые функции"
        text = f"<b>{title}</b>\n\nНажмите кнопку или введите команду в ЛС:\n\n"
        text += "\n".join(f"<code>.{code}</code> — {esc(tool_name(code))}" for code in codes)
        text += "\n\nПримеры ввода — при выборе функции."
        if section == "plus":
            from aeniaflow.core.access import has_plus

            text += "\n\n" + (
                "Ваш Plus активен."
                if has_plus(user.id)
                else "Для запуска нужен Plus. Срок и цена — в профиле → «Подписка»."
            )
        markup = feature_keyboard(section == "plus", page)
    elif section == "premium":
        text = (
            "<b>AeniaFlow+</b>\n\nОтложенные сообщения · ответы по ключевым словам\nАвтопрочтение · статистика диалогов\nПеревод и ИИ · голос в текст\nВодяные знаки · видео в кружок · обработка аудио\nБез обязательной подписки на канал\n\n"
            + (
                "У вас доступ администратора: Plus без срока и без оплаты.\n\n"
                if is_owner(user.id)
                else "Выберите срок: от 1 дня до года.\nОплата только Telegram Stars. Без автосписаний.\nНовая покупка продлевает оставшийся срок.\n\n"
            )
        )
        text += f"ИИ: {'подключён' if ai_available() else 'пока не подключён'}\nОбработка видео: {'подключена' if ffmpeg_binary() else 'пока не подключена'}"
        markup = (
            kb(
                [
                    [("Возможности Plus", "list:plus:0"), ("Мои платежи", "menu:payments")],
                    [("‹ Профиль", "menu:profile")],
                ]
            )
            if is_owner(user.id)
            else plans_keyboard()
        )
    elif section.startswith("plan:"):
        import time

        code = section.split(":", 1)[1]
        product = PLANS.get(code)
        if not product:
            raise ValueError("Тариф не найден.")
        row = db.get_user(user.id)
        expiry = max(int(time.time()), db.premium_until(user.id)) + product["days"] * 86400
        text = (
            f"<b>AeniaFlow+ · {product['label']}</b>\n\n"
            f"<b>{product['stars']} ⭐</b> · разовая оплата\nВсе возможности Plus на {product['days']} дн.\n\n"
            f"Доступ примерно до {format_time(expiry, row['timezone'])}.\nТочная дата зависит от времени оплаты. Остаток действующей подписки сохраняется.\n\nБез автосписаний. Поддержка: @{esc(settings.support_username)}"
        )
        if message.business_connection_id and not is_owner(user.id):
            text += "\nСчёт в Stars придёт вам в личный чат с ботом."
        markup = kb(
            [[("Уже доступно администратору", "menu:premium")]]
            if is_owner(user.id)
            else [
                [(f"Оплатить {product['stars']} ⭐", f"pay:{code}", "primary")],
                [("‹ Другой срок", "menu:premium"), ("Условия", "menu:terms")],
            ]
        )
    elif section == "watermark":
        from aeniaflow.handlers.system.watermarks import show_watermark

        await show_watermark(message, user.id, edit=edit)
        return
    elif section == "profile":
        row = db.get_user(user.id)
        status = (
            "Администратор · Plus без срока"
            if is_owner(user.id)
            else (
                (
                    "Plus без срока"
                    if row["premium_until"] >= 253402300799
                    else "Plus до " + format_time(row["premium_until"], row["timezone"])
                )
                if db.is_premium(user.id)
                else "Бесплатный тариф"
            )
        )
        connection = (
            db.connection_owner(message.business_connection_id)
            if message.business_connection_id
            else db.get_connection(user.id)
        )
        connected = bool(connection and connection["is_enabled"] and connection["can_reply"])
        counts = db.dialog_counts(user.id)
        records = db.organizer_counts(user.id)
        auto = db.get_autoreply(user.id)
        connection_text = (
            "ЛС подключены"
            if connected
            else (
                "ЛС подключены · проверьте права"
                if connection and connection["is_enabled"]
                else (
                    "Подключение ЛС отключено"
                    if connection
                    else "Статус ЛС ещё не получен · откройте «Подключение ЛС»"
                )
            )
        )
        text = (
            f"<b>Профиль</b>\n\n<b>{esc(user.full_name)}</b>\n{status}\n{connection_text}\n\n"
            "<b>Чаты</b> — собеседники. <b>Муты</b> — кого вы заглушили.\n"
            "Числа рядом с задачами и напоминаниями — сколько ещё ожидает выполнения.\n\n"
            "История платежей — в «Подписке Plus». Часовой пояс и данные — в «Настройках»."
        )
        if records["failed_reminders"]:
            text += f'\n\nНе доставлено напоминаний: {records["failed_reminders"]}. Откройте их список.'
        markup = kb(
            [
                [
                    (f"Чаты · {counts['total']}", "menu:chats"),
                    (f"Муты · {counts['muted']}", "menu:mutelist", "primary" if counts["muted"] else None),
                ],
                [
                    (f"Заметки · {records['notes']}", "menu:notes"),
                    (f"Задачи · {records['tasks']}", "menu:tasks"),
                ],
                [
                    (
                        f"Напоминания · {records['reminders']}"
                        + (" !" if records["failed_reminders"] else ""),
                        "menu:reminders",
                    ),
                    ("Автоответ · " + ("вкл" if auto["enabled"] else "выкл"), "menu:autoreply"),
                ],
                [
                    ("Подписка Plus", "menu:premium"),
                    (
                        "Подключение ЛС",
                        "menu:connect",
                        None if connected else "primary",
                    ),
                ],
                [("Пригласить друзей", "use:ref"), ("Очередь сообщений", "use:outbox")],
                [("Настройки", "menu:settings"), ("Помощь", "menu:help")],
                [("‹ Главное меню", "menu:home")],
            ]
        )
        if is_owner(user.id) and not message.business_connection_id:
            markup.inline_keyboard.insert(
                -1, kb([[("Управление ботом", "admin:view:home")]]).inline_keyboard[0]
            )
    elif section == "payments":
        page = max(1, min(100000, int(args or 1)))
        rows = db.payments_for(user.id, limit=5, offset=(page - 1) * 5)
        items = []
        for row in rows:
            status = {
                "paid": "Оплачен",
                "refunded": "Возвращён",
                "refund_pending": "Возврат проверяется",
            }.get(row["status"], row["status"])
            items.append(
                f'<b>{row["amount"]} ⭐ · {row["days"]} дней · {status}</b>\n{format_time(row["paid_at"])}\nЧек: <code>{esc(row["charge_id"])}</code>'
            )
        text = "<b>Мои платежи</b>\n\n" + ("\n\n".join(items) or "На этой странице нет платежей.")
        markup = kb(
            [
                pager("payments", page, bool(db.payments_for(user.id, limit=1, offset=page * 5))),
                [("Поддержка", "menu:paysupport"), ("‹ Профиль", "menu:profile")],
            ]
        )
    elif section == "settings":
        row = db.get_user(user.id)
        text = f'<b>Настройки</b>\n\nЧасовой пояс: <b>{esc(row["timezone"])}</b>\nОн используется для времени напоминаний.\n\nID аккаунта: <code>{user.id}</code>'
        text += (
            "\nДоступ: <b>администратор · Plus без оплаты</b>"
            if is_owner(user.id)
            else "\nДоступ: пользователь. Администратор может выдать доступ через .AdminMenu."
        )
        markup = kb(
            [
                [("Москва", "tz:Europe/Moscow"), ("UTC", "tz:UTC")],
                [("Другой пояс", "input:timezone"), ("Водяной знак", "menu:watermark")],
                [("Мои данные", "menu:data"), ("Состояние бота", "use:status")],
                [("Условия", "menu:terms"), ("Конфиденциальность", "menu:privacy")],
                [("‹ Профиль", "menu:profile")],
            ]
        )
    elif section == "data":
        text = "<b>Мои данные</b>\n\nСкачайте свои записи или откройте управление удалением. Удаление требует отдельного подтверждения."
        markup = kb(
            [
                [("Скачать данные", "use:export")],
                [("Управление удалением", "use:delete_data")],
                [("‹ Профиль", "menu:profile")],
            ]
        )
    elif section in {"notes", "tasks", "reminders"}:
        from aeniaflow.handlers.system.organizer_views import show_organizer

        await show_organizer(message, user, section, args or 1, edit=edit)
        return
    elif section in {"chats", "mutelist"}:
        from aeniaflow.handlers.system.dialogs import show_dialogs

        await show_dialogs(message, user.id, args or 1, muted=section == "mutelist", edit=edit)
        return
    elif section in {"help", "search"}:
        text = (
            "<b>Как пользоваться</b>\n\n"
            "<b>В боте и в подключённом ЛС</b>\nОткройте <code>.menu</code>, выберите функцию или введите её команду. "
            "Отправьте текст или файл по подсказке. «Назад» отменяет ввод.\n\n"
            "<b>В личном диалоге</b>\n"
            "<code>.mute</code> — включить бессрочный мут.\n"
            "Команда исчезнет, появится подтверждение с кнопкой «Размутить».\n"
            "<code>.unmute</code> — снять мут командой.\n\n"
            "Также работают заметки, задачи, игры, таймеры и настройки. Результат команды в диалоге виден собеседнику.\n\n"
            "Чаты, муты, подписка и настройки — в профиле.\n"
            "Быстрые команды: <code>.msay Привет!</code> · <code>.calc 2+2</code>.\n"
            "Медиа можно отправить до или после команды, без ответа на сообщение."
        )
        markup = kb(
            [
                [("Подключить Business", "menu:connect"), ("Найти функцию", "input:find")],
                [("Состояние сервисов", "use:status"), ("Поддержка", "menu:paysupport")],
                [("‹ Профиль", "menu:profile")],
            ]
        )
    elif section in {"privacy", "terms"}:
        from aeniaflow.core.legal_pages import plain_legal, split_pages

        path = LEGAL / ("privacy_policy.md" if section == "privacy" else "terms_of_service.md")
        if path.exists():
            pages = split_pages(plain_legal(path.read_text(encoding="utf-8")))
            page = max(0, min(int(args or 0), len(pages) - 1))
            title = "Условия" if section == "terms" else "Конфиденциальность"
            text = f"<b>{title} · {page + 1}/{len(pages)}</b>\n\n{esc(pages[page])}"
            markup = kb(
                [
                    [
                        ("‹", f"legal:{section}:{page-1}" if page else "nav:first"),
                        (f"{page+1} / {len(pages)}", "nav:page"),
                        ("›", f"legal:{section}:{page+1}" if page + 1 < len(pages) else "nav:last"),
                    ],
                    [("Подписка Plus", "menu:premium"), ("‹ Настройки", "menu:settings")],
                ]
            )
        else:
            text = "Документ сейчас недоступен. .paysupport"
    elif section == "paysupport":
        contact = (
            "@" + settings.support_username
            if settings.support_username
            else "Контакт ещё не настроен владельцем."
        )
        text = f"<b>Поддержка платежей</b>\n\n{esc(contact)}\n\nПриложите чек Telegram, дату и сумму в Stars.\nПо вопросам бота тоже пишите сюда."
        markup = support_keyboard()
    elif section in {"subscribe", "checksub"}:
        if await channel_check(bot, user.id):
            text, markup = "Доступ подтверждён. Можно пользоваться ботом.", main_keyboard()
        else:
            from aeniaflow.core.policy import subscription_prompt

            await subscription_prompt(message, edit=edit)
            return
    elif section in {"connect", "connecthelp"}:
        from aeniaflow.handlers.system.dialogs import rights_text

        connection = await refresh_connection(bot, user.id, message.business_connection_id)
        if section == "connect" and connection and connection["is_enabled"]:
            text = (
                "<b>Личные чаты подключены</b>\n\n"
                + rights_text(connection)
                + "\n\nКоманды — через точку в доступных боту ЛС. Новое входящее после обновления не требуется; Telegram проверяет право ответа и активность диалога."
            )
            markup = kb(
                [
                    [("Проверить права", "biz:refresh"), ("Инструкция", "menu:connecthelp")],
                    [("‹ Профиль", "menu:profile")],
                ]
            )
            await panel(message, with_command(text, "connect"), markup, edit=edit, art="dialogs")
            return
        me = await bot.get_me()
        bot_name = "@" + me.username if me.username else "username из профиля этого бота"
        text = (
            "<b>Подключение личных чатов</b>\n\n"
            f"Добавьте <b>{esc(bot_name)}</b> в Telegram → Настройки → Telegram Business → Чат-боты. Шаги и права показаны на картинке.\n\n"
            "Владелец бота: @BotFather → /mybots → Bot Settings → Secretary Mode / Business Mode → включить.\n\n"
            "Для ответа от вашего имени нужно входящее за последние 24 часа. После подключения: <code>.ping</code> и <code>.calc 2+2</code> в выбранном ЛС.\n\n"
            + (
                rights_text(connection)
                if connection
                else "Если подключение уже есть, отправьте команду в доступном боту ЛС: статус восстановится из события. Можно также переподключить бота."
            )
        )
        markup = kb([[("Проверить права", "biz:refresh", "primary")], [("‹ Профиль", "menu:profile")]])
    elif section == "autoreply":
        from aeniaflow.handlers.system.autoreply import show

        await show(message, user.id, edit=edit)
        return
    else:
        text = "Раздел не найден. Откройте главное меню."
    await panel(
        message,
        with_command(text, "premium" if section.startswith("plan:") else section),
        markup,
        edit=edit,
        protect_content=section in personal,
        fresh=fresh,
        art=(
            "plus"
            if section in {"premium", "plus"} or section.startswith("plan:")
            else "connect" if section in {"connect", "connecthelp"} else "home"
        ),
    )
