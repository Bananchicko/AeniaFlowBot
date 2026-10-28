"""Explain the failed Telegram operation without exposing credentials or request bodies."""

from __future__ import annotations

import logging
import re
from html import escape

from aiogram.exceptions import (
    TelegramAPIError,
    TelegramNetworkError,
    TelegramRetryAfter,
    TelegramServerError,
    TelegramUnauthorizedError,
)
from config import settings
from aeniaflow.core.runtime import db

log = logging.getLogger(__name__)


def redact(text: str) -> str:
    dynamic_key = ""
    try:
        if db.instance:
            dynamic_key = db.instance.runtime_option("openai_api_key")
    except Exception:
        pass
    for secret in (settings.bot_token, settings.openai_api_key, dynamic_key):
        if secret and secret.lower() not in {"none", "null"}:
            text = text.replace(secret, "[REDACTED]")
    text = re.sub(r"\b\d{5,20}:[A-Za-z0-9_-]{25,}", "[REDACTED]", text)
    return re.sub(r"\bsk-[A-Za-z0-9_-]{20,}", "[REDACTED]", text)


def error_details(exc: TelegramAPIError) -> tuple[str, str]:
    method = getattr(exc.method, "__api_method__", type(exc.method).__name__)
    # Never stringify exc.method: it can contain private text, files and payment data.
    description = " ".join(redact(exc.message).split())[:600]
    return method, description


def error_hint(exc: TelegramAPIError) -> str:
    method, description = error_details(exc)
    reason = description.lower()
    if isinstance(exc, TelegramRetryAfter):
        return f"Telegram ограничил частоту запросов. Повторите через {exc.retry_after} сек."
    if isinstance(exc, TelegramNetworkError):
        return "Хостинг не смог связаться с Telegram. Проверьте доступ сервера к api.telegram.org и сеть."
    if isinstance(exc, TelegramServerError):
        return "Telegram вернул ошибку сервера. Повторите действие позже."
    if isinstance(exc, TelegramUnauthorizedError):
        return "Проверьте, что хостинг использует действующий BOT_TOKEN именно этого бота."
    if method == "getChatMember":
        return (
            "Не удалось проверить подписку на канал. Владелец бота: проверьте канал в .AdminMenu "
            "и добавьте бота администратором этого канала. Настройка панели имеет приоритет над NEWS_CHANNEL. "
            "Пустое значение не отключает проверку. Для Plus подписка на канал необязательна."
        )
    if "voice_messages_forbidden" in reason:
        return "Собеседник запретил голосовые сообщения. Разрешение меняется в его настройках Telegram."
    if "business_connection" in reason or method == "getBusinessConnection":
        return (
            "Проверьте Secretary Mode / Business Mode в BotFather и активное подключение "
            "в Telegram → Настройки → Telegram Business → Чат-боты. "
            "Затем откройте .connect в ЛС бота и нажмите «Проверить права»."
        )
    if "can't parse entities" in reason or "button_" in reason or "reply markup" in reason:
        return "Telegram отклонил разметку сообщения или кнопок. Передайте этот ответ разработчику бота."
    if method in {"deleteBusinessMessages", "deleteMessage", "deleteMessages"}:
        return (
            "Telegram не разрешил удалить сообщение. В подключённых ЛС требуется право "
            "«Удалять все сообщения»; также проверьте доступность и возраст сообщения."
        )
    if method.startswith("editMessage") and (
        "message_id_invalid" in reason or "message to edit not found" in reason
    ):
        return "Старое сообщение уже недоступно. Откройте новое меню командой .menu. Переподключать Business из-за этой ошибки не требуется."
    if getattr(exc.method, "business_connection_id", None):
        return (
            "В настройках Telegram Business → Чат-боты разрешите отвечать и включите этот диалог "
            "в доступные чаты. Проверьте, что бот не приостановлен в диалоге. "
            "Для ответа от вашего имени нужно входящее сообщение за последние 24 часа. "
            "Проверка подключения: .connect в ЛС бота."
        )
    if "blocked" in reason or "chat not found" in reason or "can't initiate" in reason:
        return "Откройте личный чат с этим ботом, разблокируйте его и нажмите «Запустить» (/start)."
    if "query is too old" in reason or "query id is invalid" in reason:
        return "Срок ответа на нажатие истёк. Откройте новое меню командой .menu."
    return "Сохраните название запроса и ответ Telegram ниже: они показывают, где произошёл сбой."


def error_text(exc: TelegramAPIError) -> str:
    method, description = error_details(exc)
    return (
        "<b>Не удалось выполнить запрос Telegram</b>\n"
        f"Запрос: <code>{escape(method)}</code>\n"
        f"Ответ: <code>{escape(description)}</code>\n\n"
        f"{escape(error_hint(exc))}"
    )


def log_error(exc: TelegramAPIError) -> None:
    method, description = error_details(exc)
    log.warning("Telegram request failed: method=%s error=%s: %s", method, type(exc).__name__, description)


async def report_error(message, bot, exc: TelegramAPIError, *, actor: int) -> None:
    """Try the current chat, then only the verified Business owner's bot DM."""
    log_error(exc)
    from aeniaflow.keyboards import back_keyboard

    text = error_text(exc)
    try:
        await message.answer(text, parse_mode="HTML", reply_markup=back_keyboard())
        return
    except TelegramAPIError as delivery_error:
        log_error(delivery_error)
    connection = (
        db.connection_owner(message.business_connection_id) if message.business_connection_id else None
    )
    if not connection or connection["owner_id"] != actor:
        return
    try:
        await bot.send_message(
            chat_id=connection["user_chat_id"] or actor,
            text="Не удалось ответить в подключённом ЛС.\n\n" + text,
            reply_markup=back_keyboard(),
            parse_mode="HTML",
        )
    except TelegramAPIError as delivery_error:
        log_error(delivery_error)
