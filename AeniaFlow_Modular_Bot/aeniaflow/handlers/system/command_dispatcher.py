from __future__ import annotations
import asyncio
import logging
import re
import time
from aiogram import Bot, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import Message
from config import settings
from aeniaflow import __version__
from aeniaflow.catalog import PREMIUM_CODES
from aeniaflow.core.runtime import db, command_seen, processed_messages
from aeniaflow.core.helpers import esc
from aeniaflow.core.ai_service import actor_id, AIUnavailable
from aeniaflow.handlers.commands import COMMANDS
from aeniaflow.handlers.system import autoreply, admin, admin_menu
from aeniaflow.handlers.system.sections import show_section
from aeniaflow.keyboards import kb
from aeniaflow.core.access import has_plus
from aeniaflow.core.policy import gate
from aeniaflow.core.command_ui import remove_command
from aeniaflow.core.telegram_errors import report_error
from aeniaflow.core.ui import private_owner
from aeniaflow.core.responses import respond, current_action
from aeniaflow.core.inputs import (
    remember_media,
    media_source,
    media_file,
    MEDIA_COMMANDS,
    MEDIA_NAMES,
    begin_input,
    pending_input,
    clear_input,
    pending_inputs,
    input_key,
)

log = logging.getLogger(__name__)
router = Router(name="message_commands")
heavy_slots = asyncio.Semaphore(4)
HEAVY = {
    "gpt",
    "hint",
    "tr",
    "stt",
    "fix",
    "summarize",
    "rewrite",
    "explain",
    "gif",
    "speed",
    "voice",
    "videonote",
    "blur",
    "meme",
    "wm",
    "msay",
    "resize",
    "rotate",
    "mirror",
    "audio",
    "print",
    "circle",
}
SECTIONS = {
    "start": "home",
    "menu": "home",
    "help": "help",
    "commands": "help",
    "catalog": "catalog",
    "free": "free",
    "plus": "plus",
    "premium": "premium",
    "subscribe": "subscribe",
    "checksub": "checksub",
    "privacy": "privacy",
    "terms": "terms",
    "paysupport": "paysupport",
    "profile": "profile",
    "payments": "payments",
    "settings": "settings",
    "organizer": "organizer",
    "connect": "connect",
    "chats": "chats",
    "mutelist": "mutelist",
    "watermark": "watermark",
}
SYSTEM_COMMANDS = {
    "autoreply": autoreply.handle,
    "admin": admin.handle,
    "audit": admin.audit,
    "refund": admin.refund,
    "reconcile": admin.reconcile,
}


@router.message()
async def incoming_message(message: Message, bot: Bot, *, from_button=False):
    if message.chat.type != "private" or not message.from_user or message.from_user.is_bot:
        return
    if (
        (message.sender_business_bot and not from_button)
        or message.business_connection_id
        and message.chat.id == bot.id
    ):
        return
    if message.business_connection_id and (message.text or message.caption or "").lstrip().startswith("/"):
        return
    if not private_owner(message):
        return
    db.upsert_user(message.from_user)
    db.remember_peer(message.from_user)
    if not message.business_connection_id:
        db.mark_bot_dm(message.from_user.id)
    token = actor_id.set(message.from_user.id)
    action_token = current_action.set(None)
    try:
        remember_media(message)
        raw = (message.text or message.caption or "").strip()
        match = re.fullmatch(r"\.([A-Za-z_][A-Za-z0-9_]*)(?:@([A-Za-z0-9_]+))?(?:\s+(.*))?", raw, re.S)
        # Telegram's Start button and mandatory payment support use service commands.
        if not match and raw.startswith("/"):
            service = re.fullmatch(r"/(start|help|paysupport)(?:@([A-Za-z0-9_]+))?(?:\s+(.*))?", raw, re.S)
            if service:
                match = service
            else:
                if message.chat.type == "private":
                    await respond(
                        message,
                        "Префикс команд — точка. Например: <code>.calc 2+2</code>. Меню: <code>.menu</code>.",
                    )
                return
        if not message.business_connection_id:
            ref_match = re.fullmatch(r"/start\s+ref_([0-9]{1,19})", raw)
            db.bind_referral(message.from_user.id, int(ref_match.group(1)) if ref_match else None)
        resuming = False
        input_back = None
        if match:
            cmd, target, args = match.group(1).lower(), match.group(2), (match.group(3) or "").strip()
            previous = pending_input(message)
            if previous and previous[0] == cmd and (previous[3] or "").startswith("dialog:open:"):
                input_back = previous[3]
            else:
                clear_input(message)
        else:
            pending = pending_input(message)
            if not pending:
                return
            resuming = True
            cmd, prefix, input_mode, input_back = pending
            target = None
            if cmd in MEDIA_COMMANDS and input_mode != "text":
                if not media_file(message, MEDIA_COMMANDS[cmd]):
                    await respond(
                        message, f"Жду {MEDIA_NAMES[MEDIA_COMMANDS[cmd]]}. Отмена: <code>.cancel</code>."
                    )
                    return
                args = prefix
            elif raw:
                args = (prefix + " " + raw).strip()
            else:
                await respond(message, "Отправьте текст. Отмена: <code>.cancel</code>.")
                return
        if not from_button:
            delivery = (bot.id, message.business_connection_id, message.chat.id, message.message_id)
            now = time.monotonic()
            if now - processed_messages.get(delivery, -1000) < 300:
                return
            processed_messages[delivery] = now
        if target:
            me = await bot.get_me()
            if not me.username or target.casefold() != me.username.casefold():
                return
        if cmd in admin_menu.COMMANDS:
            if not admin_menu.allowed(message, message.from_user):
                return
            await admin_menu.handle(message, args, bot, cmd)
            if not from_button and cmd != "aikey":
                await remove_command(message, bot)
            return
        if cmd in SYSTEM_COMMANDS and cmd != "autoreply":
            if admin_menu.allowed(message, message.from_user):
                await SYSTEM_COMMANDS[cmd](message, args, bot)
            return
        if not await gate(message, message.from_user, bot, cmd, fresh=cmd in {"menu", "start"}):
            return
        if cmd == "ping":
            # A fresh plain reply is deliberately independent of covers, old
            # menu messages and optional services. The central access policy still applies.
            context = "Подключённый личный диалог" if message.business_connection_id else "ЛС бота"
            await message.answer(
                f"AeniaFlow {__version__}: на связи.\n{context}: команда получена, ответ отправлен.",
                parse_mode=None,
            )
            return
        current_action.set(cmd)
        if cmd == "cancel":
            clear_input(message)
            await respond(
                message,
                "Действие отменено.",
                reply_markup=kb([[("Меню", "menu:home")]]),
            )
            if not from_button:
                await remove_command(message, bot)
            return
        if target:
            me = await bot.get_me()
            if not me.username or target.casefold() != me.username.casefold():
                return
        # The central policy above decides access to each section.
        if cmd in SECTIONS:
            clear_input(message)
            await show_section(
                message,
                bot,
                message.from_user,
                "premium" if cmd == "start" and args == "premium" else SECTIONS[cmd],
                args,
                fresh=cmd in {"menu", "start"},
            )
            if not from_button:
                await remove_command(message, bot)
            return
        if cmd in SYSTEM_COMMANDS:
            if cmd != "autoreply" and not admin_menu.allowed(message, message.from_user):
                return
            await SYSTEM_COMMANDS[cmd](message, args, bot)
            if cmd == "autoreply" and not from_button and not resuming:
                await remove_command(message, bot)
            clear_input(message)
            return
        if cmd not in COMMANDS:
            if message.chat.type == "private":
                await respond(message, "Команда не найдена. Откройте функции: .menu. Поиск: .find название.")
            return
        user = message.from_user.id
        now = time.monotonic()
        key = ("command", user)
        if not resuming and now - command_seen.get(key, -1000) < settings.command_cooldown:
            await respond(message, "Подождите пару секунд перед следующей командой.")
            return
        command_seen[key] = now
        if cmd in PREMIUM_CODES and not has_plus(user):
            await respond(
                message,
                "⭐ Эта функция входит в AeniaFlow+.",
                reply_markup=kb([[("Тарифы в Stars", "menu:premium")]]),
            )
            return
        if cmd in MEDIA_COMMANDS and (
            not media_source(message, MEDIA_COMMANDS[cmd])
            or (resuming and input_mode == "text" and not media_file(message, MEDIA_COMMANDS[cmd]))
        ):
            begin_input(message, cmd, args, back=input_back)
            await respond(
                message,
                f"Отправьте {MEDIA_NAMES[MEDIA_COMMANDS[cmd]]} следующим сообщением.\nОтмена: <code>.cancel</code>.",
                reply_markup=kb([[("‹ Назад", input_back or "menu:home")]]),
            )
            if not from_button and not resuming:
                await remove_command(message, bot)
            return
        if cmd == "resize" and not args:
            args = "800"
        if cmd == "print" and not args:
            from aeniaflow.handlers.system.actions import ACTIONS

            begin_input(message, cmd, "", mode="text", back=input_back)
            await respond(message, ACTIONS[cmd][2] + "\nОтмена: .cancel")
            if not from_button:
                await remove_command(message, bot)
            return
        before_record = pending_inputs.get(input_key(message))
        if cmd in HEAVY:
            if heavy_slots.locked():
                await respond(message, "Сейчас все слоты обработки заняты. Попробуйте через минуту.")
                return
            async with heavy_slots:
                await COMMANDS[cmd](message, args, bot)
        else:
            await COMMANDS[cmd](message, args, bot)
        if not from_button and not resuming and cmd not in {"mute", "unmute", "panic", "antimute"}:
            await remove_command(message, bot)
        if pending_inputs.get(input_key(message)) is before_record:
            clear_input(message)
    except (ValueError, AIUnavailable) as exc:
        await respond(message, esc(str(exc)[:1500]))
    except TelegramAPIError as exc:
        await report_error(message, bot, exc, actor=message.from_user.id)
    except Exception:
        log.exception("Command failed")
        await respond(
            message, "Не удалось выполнить команду. Попробуйте позже; владелец может проверить журнал."
        )
    finally:
        actor_id.reset(token)
        current_action.reset(action_token)
