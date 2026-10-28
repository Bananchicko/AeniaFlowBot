"""Relative/absolute reminder parsing and an at-least-once delivery worker."""

from __future__ import annotations
import asyncio
import logging
import re
from datetime import datetime
from time import time
from zoneinfo import ZoneInfo
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest, TelegramRetryAfter
from aeniaflow.core.runtime import db

log = logging.getLogger(__name__)
UNITS = {
    "s": 1,
    "с": 1,
    "m": 60,
    "м": 60,
    "h": 3600,
    "ч": 3600,
    "d": 86400,
    "д": 86400,
    "w": 604800,
    "н": 604800,
}


def parse_duration(value: str) -> int:
    value = value.strip().lower()
    if value.isdigit():
        seconds = int(value)
    else:
        tokens = re.findall(r"(\d+)([smhdwсмчдн])", value)
        if not tokens or "".join(n + u for n, u in tokens) != value:
            raise ValueError("Время: 30s, 10m, 2h30m, 1d или число секунд.")
        seconds = sum(int(n) * UNITS[u] for n, u in tokens)
    if not 1 <= seconds <= 366 * 86400:
        raise ValueError("Интервал: от 1 секунды до 366 дней.")
    return seconds


def parse_reminder(args: str, zone: str, *, now: int | None = None):
    now = int(time()) if now is None else now
    interval = 0
    parts = args.split()
    if not parts:
        raise ValueError("Пример: .remind 10m Сделать перерыв")
    if parts[0].lower() == "every":
        if len(parts) < 3:
            raise ValueError("Пример повтора: .remind every 1d Проверить задачи")
        interval = parse_duration(parts[1])
        if interval < 60:
            raise ValueError("Повтор — не чаще раза в минуту.")
        return now + interval, interval, " ".join(parts[2:])
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", parts[0]):
        if len(parts) < 3:
            raise ValueError("Формат: .remind 2026-12-31 18:00 Текст")
        naive = datetime.fromisoformat(parts[0] + "T" + parts[1])
        if naive.tzinfo is not None:
            raise ValueError("Задайте часовой пояс через .clock; время укажите без смещения.")
        tz = ZoneInfo(zone)
        local = naive.replace(tzinfo=tz)
        if (
            local.utcoffset() != local.replace(fold=1).utcoffset()
            or datetime.fromtimestamp(local.timestamp(), tz).replace(tzinfo=None) != naive
        ):
            raise ValueError("Это время попало на перевод часов. Выберите другое время.")
        due = int(local.timestamp())
        text = " ".join(parts[2:])
    else:
        due = now + parse_duration(parts[0])
        text = " ".join(parts[1:])
    if not now < due <= now + 366 * 86400:
        raise ValueError("Выберите будущее время в пределах 366 дней.")
    if not text:
        raise ValueError("Добавьте текст напоминания после времени.")
    return due, interval, text


async def send_reminder(bot, row):
    text = f'⏰ Напоминание #{row["id"]}\n{row["text"]}'
    connection_id = row["business_connection_id"]
    if connection_id:
        connection = db.connection_owner(connection_id)
        if (
            connection
            and connection["owner_id"] == row["user_id"]
            and connection["is_enabled"]
            and connection["can_reply"]
        ):
            try:
                await bot.send_message(
                    row["chat_id"],
                    text,
                    parse_mode=None,
                    business_connection_id=connection_id,
                    message_thread_id=row["thread_id"],
                )
                return
            except (TelegramForbiddenError, TelegramBadRequest):
                pass
        # Business may be disconnected or its 24-hour reply window may have expired.
        # Never fall back to sending as the bot directly to the conversation partner.
        await bot.send_message(
            row["user_id"],
            text
            + "\n\nНе удалось доставить в исходный диалог. Напоминание отправлено только вам. Проверьте подключение и активность чата.",
            parse_mode=None,
        )
        return
    await bot.send_message(row["chat_id"], text, parse_mode=None, message_thread_id=row["thread_id"])


async def deliver_due(bot, *, now: int | None = None):
    now = int(time()) if now is None else now
    from aeniaflow.core.policy import maintenance, banned

    if maintenance():
        return
    rows = db.claim_due(now)
    for row in rows:
        if maintenance():
            db.conn.execute(
                "UPDATE reminders SET status='pending',lease_until=0 WHERE id=? AND status='sending'",
                (row["id"],),
            )
            continue
        if banned(row["user_id"]):
            db.conn.execute("UPDATE reminders SET status='cancelled',lease_until=0 WHERE id=?", (row["id"],))
            continue
        from aeniaflow.handlers.system.sections import channel_check

        try:
            subscribed = await channel_check(bot, row["user_id"])
        except Exception:
            subscribed = False
        if not subscribed:
            db.conn.execute(
                "UPDATE reminders SET status='pending',due_at=?,lease_until=0 WHERE id=?",
                (now + 60, row["id"]),
            )
            continue
        # Cancellation can happen while another reminder is awaiting Telegram.
        current = db.conn.execute("SELECT status FROM reminders WHERE id=?", (row["id"],)).fetchone()
        if not current or current["status"] != "sending":
            continue
        try:
            await send_reminder(bot, row)
        except TelegramRetryAfter as exc:
            db.fail_reminder(row["id"], now, "telegram_rate_limit", retry_after=exc.retry_after + 1)
        except (TelegramForbiddenError, TelegramBadRequest):
            db.fail_reminder(row["id"], now, "chat_unavailable", permanent=True)
        except Exception:
            db.fail_reminder(row["id"], now, "delivery_error")
            log.warning("Reminder delivery will be retried: id=%s", row["id"])
        else:
            db.complete_reminder(row["id"], now)


async def reminder_worker(bot):
    while True:
        try:
            await deliver_due(bot)
        except Exception:
            log.exception("Reminder queue iteration failed")
        await asyncio.sleep(2)
