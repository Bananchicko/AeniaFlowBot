from __future__ import annotations
import logging
from aiogram import Bot, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import CallbackQuery, Message
from zoneinfo import ZoneInfo
from aeniaflow.catalog import FEATURES
from aeniaflow.core.runtime import db, command_seen
from aeniaflow.core.helpers import esc
from aeniaflow.keyboards import feature_detail_keyboard, kb
from aeniaflow.core.ui import panel, private_owner, panels
from aeniaflow.core.inputs import clear_input
from aeniaflow.core.navigation import tool_return, BASIC_CODES, PLUS_CODES
from aeniaflow.core.access import is_owner, has_plus
from aeniaflow.core.policy import gate, callback_action
from aeniaflow.core.telegram_errors import error_details, report_error
from aeniaflow.catalog import PREMIUM_CODES
from aeniaflow.handlers.system.actions import start_action
from aeniaflow.handlers.system.sections import show_section
from aeniaflow.handlers.system.payments import send_invoice
from aeniaflow.handlers.system import admin
from aeniaflow.core.games import winner, bot_move
from aeniaflow.handlers.commands.x import board_markup
import time

router = Router(name="callbacks")
log = logging.getLogger(__name__)


@router.callback_query()
async def callbacks(callback: CallbackQuery, bot: Bot):
    if not isinstance(callback.message, Message):
        await callback.answer("Откройте новое меню: .start.")
        return
    try:
        await dispatch_callback(callback, bot)
    except ValueError as exc:
        await callback.answer("Не удалось выполнить действие.", show_alert=True)
        await panel(callback.message, esc(str(exc)), edit=True)
    except TelegramAPIError as exc:
        if isinstance(exc, TelegramBadRequest) and "message is not modified" in exc.message.lower():
            try:
                await callback.answer()
            except TelegramAPIError:
                pass
            return
        method, description = error_details(exc)
        try:
            await callback.answer(f"{method}: {description}"[:180], show_alert=True)
        except TelegramAPIError:
            pass
        await report_error(callback.message, bot, exc, actor=callback.from_user.id)
    except Exception:
        log.exception("Callback failed")
        await callback.answer("Ошибка действия. Откройте .menu.", show_alert=True)


async def dispatch_callback(callback: CallbackQuery, bot: Bot):
    data, message, user = callback.data or "", callback.message, callback.from_user
    if message.chat.type != "private":
        await callback.answer("Бот работает только в личных чатах.", show_alert=True)
        return
    if not message.business_connection_id and message.chat.id != user.id:
        await callback.answer("Откройте меню в своём чате с ботом.", show_alert=True)
        return
    if not private_owner(message, user, allow_disconnected=data.startswith(("mute:off:", "dialog:unmute:"))):
        await callback.answer("Эта кнопка доступна владельцу подключения.", show_alert=True)
        return
    db.upsert_user(user)
    panel_key = (bot.id, message.business_connection_id, message.chat.id)
    if message.photo and not panels.get(panel_key) and not db.load_panel(*panel_key):
        # Adopt an existing 2.6 menu before an immediate action produces a result.
        panels[panel_key] = (time.monotonic(), message.as_(bot))
    if not message.business_connection_id:
        db.mark_bot_dm(user.id)
        db.bind_referral(user.id)
    if data.startswith("admin:"):
        from aeniaflow.handlers.system import admin_menu

        if not admin_menu.allowed(message, user):
            await callback.answer()
            return
        clear_input(message, user.id)
        await admin_menu.callback(callback, bot)
        return
    if data.startswith("panelpage:") and not message.business_connection_id and is_owner(user.id):
        import json
        from aeniaflow.core.ui import panel_page

        saved = db.load_panel(*panel_key)
        if saved and json.loads(saved["pages"]).get("admin_only"):
            await callback.answer()
            await panel_page(message, int(data.split(":")[1]))
            return
    if not await gate(message, user, bot, callback_action(data), edit=True):
        await callback.answer()
        return
    action = callback_action(data)
    if action in PREMIUM_CODES and not has_plus(user.id):
        await callback.answer()
        await show_section(message, bot, user, "premium", edit=True)
        return
    if data.startswith("ref:"):
        from aeniaflow.handlers.commands.referrals import callback as ref_callback

        await ref_callback(callback, bot)
        return
    if data.startswith("mail:"):
        db.conn.execute("UPDATE users SET mail_enabled=? WHERE user_id=?", (int(data == "mail:on"), user.id))
        await callback.answer("Настройка рассылки сохранена.", show_alert=True)
        return
    if data.startswith("chatset:autoread:"):
        from aeniaflow.handlers.commands.dialog_tools import apply_dialog

        _, command, identifier, value = data.split(":")
        row = db.dialog(user.id, int(identifier))
        if row and (
            not message.business_connection_id
            or row["connection_id"] == message.business_connection_id
            and row["chat_id"] == message.chat.id
        ):
            await callback.answer()
            await apply_dialog(message.model_copy(update={"from_user": user}), value, bot, command, row)
        return
    if data.startswith("outbox:cancel:"):
        identifier = int(data.split(":")[-1])
        db.conn.execute(
            "UPDATE scheduled_messages SET state='cancelled' WHERE id=? AND owner_id=? AND state='pending'",
            (identifier, user.id),
        )
        from aeniaflow.handlers.commands.chat_plus import outbox

        await callback.answer()
        await outbox(message.model_copy(update={"from_user": user}), "", bot)
        return
    if data.startswith("nav:"):
        await callback.answer(
            {
                "nav:first": "Это первая страница.",
                "nav:last": "Это последняя страница.",
                "nav:page": "Листайте стрелками ‹ и ›.",
            }.get(data)
        )
        return
    clear_input(message, user.id)
    if data.startswith("admin:"):
        from aeniaflow.handlers.system import admin_menu

        await admin_menu.callback(callback, bot)
    elif data.startswith("panelpage:"):
        from aeniaflow.core.ui import panel_page

        await callback.answer()
        await panel_page(message, int(data.split(":")[1]))
    elif data.startswith("sendcount:"):
        from aeniaflow.handlers.commands.message_series import select_count

        await callback.answer()
        await select_count(message.model_copy(update={"from_user": user}), int(data.split(":")[1]), bot)
    elif data.startswith("muterun:"):
        code = data.split(":")[1]
        if code not in {"mute", "unmute"}:
            return
        await callback.answer()
        if message.business_connection_id:
            from aeniaflow.core.business_access import current_dialog
            from aeniaflow.handlers.system.mutes import enable_mute, disable_mute

            request = message.model_copy(update={"from_user": user})
            row = current_dialog(request)
            await (enable_mute(bot, row) if code == "mute" else disable_mute(bot, row))
        else:
            from aeniaflow.handlers.system.dialogs import show_dialogs

            await show_dialogs(message, user.id, muted=code == "unmute", edit=True)
    elif data.startswith("chatpick:"):
        from aeniaflow.handlers.commands.dialog_tools import choose_dialog

        _, command, raw_page = data.split(":")
        await callback.answer()
        await choose_dialog(message, command, user=user, edit=True, page=int(raw_page))
    elif data.startswith("chattool:"):
        from aeniaflow.handlers.commands.dialog_tools import apply_dialog, DIALOG_COMMANDS

        _, command, identifier = data.split(":")
        row = db.dialog(user.id, int(identifier))
        if not row or command not in DIALOG_COMMANDS:
            await callback.answer()
            return
        if message.business_connection_id and (
            row["connection_id"] != message.business_connection_id or row["chat_id"] != message.chat.id
        ):
            await callback.answer()
            return
        await callback.answer()
        await apply_dialog(message.model_copy(update={"from_user": user}), "", bot, command, row)
    elif data.startswith(("mute:off:", "dialog:unmute:")):
        from aeniaflow.handlers.system.mutes import disable_mute

        identifier = int(data.split(":")[2])
        row = db.dialog(user.id, identifier)
        if not row or (
            message.business_connection_id
            and data.startswith("mute:off:")
            and (message.business_connection_id != row["connection_id"] or message.chat.id != row["chat_id"])
        ):
            await callback.answer("Эта кнопка доступна владельцу этого диалога.", show_alert=True)
            return
        await disable_mute(bot, row)
        await callback.answer("Мут снят.")
        if data.startswith("dialog:unmute:") or (
            not message.business_connection_id and message.message_id != row["owner_message_id"]
        ):
            from aeniaflow.handlers.system.dialogs import show_dialog

            await show_dialog(message, user.id, identifier)
    elif data.startswith("dialog:"):
        from aeniaflow.handlers.system.dialogs import show_dialog
        from aeniaflow.handlers.system.mutes import enable_mute

        parts = data.split(":")
        if len(parts) != 3:
            raise ValueError("Мут теперь без срока. Откройте .chats заново.")
        action, identifier = parts[1], int(parts[2])
        row = db.dialog(user.id, identifier)
        if not row:
            raise ValueError("Диалог недоступен.")
        if action == "mute":
            await enable_mute(bot, row)
        elif action != "open":
            raise ValueError("Неизвестное действие.")
        await callback.answer("Мут включён." if action == "mute" else None)
        await show_dialog(message, user.id, identifier)
    elif data.startswith("wmset:"):
        _, option, value = data.split(":")
        db.set_watermark(user.id, option, int(value) if option in {"opacity", "count"} else value)
        await callback.answer("Сохранено.")
        from aeniaflow.handlers.system.watermarks import show_watermark

        await show_watermark(message, user.id, edit=True)
    elif data.startswith("plan:"):
        await callback.answer()
        await show_section(message, bot, user, data, edit=True)
    elif data == "biz:refresh":
        from aeniaflow.core.business_access import save_business_connection

        connection = (
            db.connection_owner(message.business_connection_id)
            if message.business_connection_id
            else db.get_connection(user.id)
        )
        if connection:
            actual = await bot.get_business_connection(connection["connection_id"])
            if actual.user.id != user.id:
                raise ValueError("Подключение недоступно.")
            save_business_connection(actual)
        await callback.answer(
            "Права обновлены." if connection else "Подключите бота в настройках Telegram Business."
        )
        await show_section(message, bot, user, "connect", edit=True)
    elif data == "afk:off":
        db.set_afk(user.id, None)
        await callback.answer("AFK выключен.")
        await panel(
            message,
            "<b>✓ Вы снова на связи</b>\n\nСообщение о вашем отсутствии больше не отправляется.",
            kb([[("‹ Функции", tool_return("afk")), ("Профиль", "menu:profile")]]),
            edit=True,
        )
    elif data.startswith("run:"):
        _, code, mode, raw_page = data.split(":")
        if mode not in {"free", "plus"}:
            raise ValueError("Откройте функции заново.")
        if code not in (PLUS_CODES if mode == "plus" else BASIC_CODES):
            raise ValueError("Кнопка устарела. Откройте функции заново.")
        await callback.answer()
        if code in PREMIUM_CODES and not has_plus(user.id):
            await show_section(message, bot, user, "premium", edit=True)
            return
        await start_action(message, bot, user, code, back=tool_return(code))
    elif data.startswith(("input:", "use:")):

        await callback.answer()
        code = data.split(":", 1)[1]
        if code in PREMIUM_CODES and not has_plus(user.id):
            await show_section(message, bot, user, "premium", edit=True)
            return
        await start_action(message, bot, user, code)
    elif data.startswith("legal:"):
        _, section, page = data.split(":")
        if section not in {"terms", "privacy"}:
            raise ValueError("Документ недоступен.")
        await callback.answer()
        await show_section(message, bot, user, section, page, edit=True)
    elif data.startswith("page:"):
        _, section, page = data.split(":")
        if section not in {"notes", "tasks", "reminders", "payments", "chats", "mutelist"}:
            raise ValueError("Страница недоступна.")
        await callback.answer()
        await show_section(message, bot, user, section, page, edit=True)
    elif data.startswith("cat:"):
        _, category, page = data.split(":")
        await callback.answer()
        await show_section(message, bot, user, "category:" + category, page, edit=True)
    elif data.startswith("note:"):
        _, action, owner, identifier, page = data.split(":")
        if int(owner) != user.id:
            await callback.answer("Заметка недоступна.", show_alert=True)
            return
        await callback.answer()
        from aeniaflow.handlers.system.organizer_views import show_note

        if action == "open":
            await show_note(message, user.id, int(identifier), int(page))
        elif action == "ask":
            row = db.note(user.id, int(identifier))
            if not row:
                raise ValueError("Заметка уже удалена.")
            await panel(
                message,
                f'Удалить заметку «{esc(row["title"])}»?',
                kb(
                    [
                        [
                            ("Удалить", f"note:delete:{owner}:{identifier}:0"),
                            ("Отмена", f"note:open:{owner}:{identifier}:0"),
                        ]
                    ]
                ),
                edit=True,
            )
        elif action == "delete":
            db.delete_note(user.id, int(identifier))
            await show_section(message, bot, user, "notes", edit=True)
        else:
            raise ValueError("Действие недоступно.")
    elif data.startswith("menu:"):
        await callback.answer()
        await show_section(message, bot, user, data.split(":", 1)[1], edit=True)
    elif data.startswith("list:"):
        _, mode, page = data.split(":")
        await callback.answer()
        await show_section(message, bot, user, "plus" if mode == "plus" else "free", page, edit=True)
    elif data.startswith("feat:"):
        code = data.split(":", 1)[1]
        feature = FEATURES.get(code)
        await callback.answer()
        if feature:
            name, usage = feature
            await panel(
                message,
                f"<b>{esc(name)}</b>\n\n<code>{esc(usage)}</code>",
                feature_detail_keyboard(code),
                edit=True,
            )
    elif data.startswith("pay:"):
        if is_owner(user.id):
            await callback.answer("У администратора уже есть Plus без оплаты.", show_alert=True)
            return
        key = ("invoice", user.id)
        now = time.monotonic()
        if now - command_seen.get(key, -1000) < 5:
            await callback.answer("Счёт уже создаётся. Подождите несколько секунд.")
            return
        command_seen[key] = now
        await callback.answer()
        await send_invoice(bot, user, data.split(":", 1)[1])
        if message.business_connection_id:
            await message.answer("Счёт в Stars отправлен владельцу в личный чат с ботом.")
    elif data == "sub:check":
        await callback.answer()
        await show_section(message, bot, user, "checksub", edit=True)
    elif data.startswith(("auto:", "tz:")):
        key, value = data.split(":", 1)
        if key == "tz":
            ZoneInfo(value)
            db.set_timezone(user.id, value)
            await callback.answer("Часовой пояс сохранён.")
            await show_section(message, bot, user, "settings", edit=True)
        else:
            connection = db.get_connection(user.id)
            if value not in {"on", "off"}:
                raise ValueError("Неизвестная настройка.")
            if value == "on" and (
                not connection or not connection["is_enabled"] or not connection["can_reply"]
            ):
                await callback.answer(
                    "Сначала подключите Telegram Business и разрешите отвечать.", show_alert=True
                )
                return
            db.save_autoreply(user.id, enabled=value == "on")
            await callback.answer("Сохранено.")
            await show_section(message, bot, user, "autoreply", edit=True)
    elif data.startswith(("task:", "remind:")):
        kind, action, owner, item_id = data.split(":")
        if int(owner) != user.id:
            await callback.answer("Это запись другого пользователя.", show_alert=True)
            return
        if kind == "task" and message.chat.type != "private":
            await callback.answer("Задачи доступны в личном чате.", show_alert=True)
            return
        if kind == "task" and action in {"done", "undo"}:
            ok = db.change_task(user.id, int(item_id), action == "done")
        elif kind == "remind" and action == "cancel":
            ok = db.cancel_reminder(user.id, int(item_id))
        else:
            raise ValueError("Неизвестное действие.")
        await callback.answer("Сохранено." if ok else "Запись уже закрыта или удалена.")
        await show_section(message, bot, user, "tasks" if kind == "task" else "reminders", edit=True)
    elif data.startswith("ttt:"):
        _, game_id, raw_index = data.split(":")
        index = int(raw_index)
        state = db.game("ttt", message.chat.id, user.id)
        if (
            not state
            or state["id"] != game_id
            or state["message_id"] != message.message_id
            or state.get("business_connection_id") != message.business_connection_id
        ):
            await callback.answer("Это чужая или устаревшая партия. Новая: .x.", show_alert=True)
            return
        board = state["board"]
        if not 0 <= index < 9 or board[index] != "⬜":
            await callback.answer("Эта клетка занята.")
            return
        board[index] = "❌"
        result = "Вы победили!" if winner(board, "❌") else "Ничья." if "⬜" not in board else ""
        if not result:
            board[bot_move(board)] = "⭕"
            result = "Бот победил." if winner(board, "⭕") else "Ничья." if "⬜" not in board else ""
        if result:
            db.delete_game("ttt", message.chat.id, user.id)
        else:
            db.save_game("ttt", message.chat.id, user.id, state)
        await callback.answer()
        # Final text preserves the board after the keyboard is removed.
        final_board = "\n".join("".join(board[i : i + 3]) for i in (0, 3, 6)) if result else ""
        await panel(
            message,
            "Крестики-нолики: вы ❌, бот ⭕.\n" + result + "\n" + final_board,
            reply_markup=(
                kb([[("Сыграть ещё", "use:x"), ("Главное меню", "menu:home")]])
                if result
                else board_markup(board, game_id)
            ),
            edit=True,
        )
    elif data.startswith("refund:"):
        await admin.confirm_refund(callback, bot, data.split(":", 1)[1])
    elif data.startswith("dismiss:"):
        token = data.split(":", 1)[1]
        item = admin.confirmations.get(token)
        if item and item[0] == user.id:
            admin.confirmations.pop(token, None)
            await message.edit_reply_markup(reply_markup=None)
        await callback.answer("Отменено.")
    else:
        await callback.answer("Кнопка устарела. Откройте .menu.")
