"""Durable, rate-limited outbound jobs. Ambiguous sends are never retried automatically."""

import asyncio
import time
import logging
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramRetryAfter,
)
from aeniaflow.core.runtime import db
from aeniaflow.core.policy import maintenance, banned
from aeniaflow.core.access import has_plus, is_owner
from aeniaflow.keyboards import kb

log = logging.getLogger(__name__)
INTERVAL = 0.12


def recover_interrupted():
    db.conn.execute(
        "UPDATE broadcast_recipients SET state='uncertain',error='interrupted' WHERE state='sending'"
    )
    db.conn.execute(
        "UPDATE scheduled_messages SET state='uncertain',error='Перезапуск во время отправки; проверьте диалог' WHERE state='sending'"
    )


async def broadcasts_due(bot, *, now=None):
    now = int(time.time()) if now is None else now
    if maintenance():
        return
    job = db.conn.execute(
        "SELECT * FROM broadcasts WHERE state='queued' AND next_at<=? ORDER BY id LIMIT 1", (now,)
    ).fetchone()
    if not job:
        return
    if not is_owner(job["actor"]):
        db.conn.execute("UPDATE broadcasts SET state='paused' WHERE id=?", (job["id"],))
        return
    rows = db.conn.execute(
        "SELECT * FROM broadcast_recipients WHERE job_id=? AND state='pending' ORDER BY user_id LIMIT 10",
        (job["id"],),
    ).fetchall()
    for item in rows:
        if maintenance() or db.broadcast(job["id"])["state"] != "queued":
            return
        target = item["user_id"]
        user = db.get_user(target)
        eligible = user and user["dm_started"] and user["mail_enabled"] and not banned(target)
        if eligible and job["audience"] != "all":
            eligible = has_plus(target) == (job["audience"] == "plus")
        if not eligible:
            db.conn.execute(
                "UPDATE broadcast_recipients SET state='skipped' WHERE job_id=? AND user_id=?",
                (job["id"], target),
            )
            continue
        claimed = db.conn.execute(
            "UPDATE broadcast_recipients SET state='sending' WHERE job_id=? AND user_id=? AND state='pending'",
            (job["id"], target),
        ).rowcount
        if not claimed:
            continue
        state, error = "sent", ""
        try:
            await bot.send_message(
                target,
                job["body"],
                parse_mode=None,
                allow_paid_broadcast=False,
                reply_markup=kb([[("Не получать рассылку", "mail:off")]]),
            )
        except TelegramRetryAfter as exc:
            db.conn.execute(
                "UPDATE broadcasts SET next_at=? WHERE id=?", (now + exc.retry_after + 1, job["id"])
            )
            db.conn.execute(
                "UPDATE broadcast_recipients SET state='pending' WHERE job_id=? AND user_id=?",
                (job["id"], target),
            )
            return
        except (TelegramBadRequest, TelegramForbiddenError):
            state, error = "failed", "chat_unavailable"
        except Exception:
            state, error = "uncertain", "delivery_result_unknown"
        db.conn.execute(
            "UPDATE broadcast_recipients SET state=?,error=? WHERE job_id=? AND user_id=?",
            (state, error, job["id"], target),
        )
        await asyncio.sleep(INTERVAL)
    pending = db.conn.execute(
        "SELECT 1 FROM broadcast_recipients WHERE job_id=? AND state IN ('pending','sending') LIMIT 1",
        (job["id"],),
    ).fetchone()
    if not pending:
        db.conn.execute("UPDATE broadcasts SET state='finished' WHERE id=? AND state='queued'", (job["id"],))


async def scheduled_due(bot, *, now=None):
    now = int(time.time()) if now is None else now
    if maintenance():
        return
    rows = db.conn.execute(
        "SELECT * FROM scheduled_messages WHERE state='pending' AND due_at<=? ORDER BY due_at,id LIMIT 5",
        (now,),
    ).fetchall()
    for item in rows:
        if maintenance():
            return
        owner = item["owner_id"]
        dialog = db.dialog(owner, item["dialog_id"])
        if not dialog:
            continue
        if banned(owner) or not has_plus(owner):
            db.conn.execute(
                "UPDATE scheduled_messages SET state='cancelled',error='Нет доступа Plus' WHERE id=?",
                (item["id"],),
            )
            continue
        if dialog["paused"]:
            continue
        # Refresh permission, but do not mark sending until the actual send is about to start.
        try:
            connection = await bot.get_business_connection(dialog["connection_id"])
            if (
                connection.user.id != owner
                or not connection.is_enabled
                or not connection.rights
                or not connection.rights.can_reply
            ):
                raise ValueError("Нет права ответа Business")
        except (TelegramAPIError, ValueError):
            db.conn.execute(
                "UPDATE scheduled_messages SET state='failed',error='Проверьте подключение и право ответа' WHERE id=?",
                (item["id"],),
            )
            continue
        if maintenance() or banned(owner) or not has_plus(owner):
            return
        claimed = db.conn.execute(
            "UPDATE scheduled_messages SET state='sending' WHERE id=? AND state='pending'", (item["id"],)
        ).rowcount
        if not claimed:
            continue
        state, error = "sent", ""
        try:
            await bot.send_message(
                dialog["chat_id"],
                item["body"],
                parse_mode=None,
                business_connection_id=dialog["connection_id"],
            )
        except TelegramRetryAfter as exc:
            db.conn.execute(
                "UPDATE scheduled_messages SET state='pending',due_at=? WHERE id=?",
                (now + exc.retry_after + 1, item["id"]),
            )
            continue
        except (TelegramBadRequest, TelegramForbiddenError):
            state, error = "failed", "Telegram не разрешил отправку. Проверьте права и активность диалога."
        except Exception:
            state, error = "uncertain", "Результат неизвестен. Проверьте диалог перед повтором."
        db.conn.execute(
            "UPDATE scheduled_messages SET state=?,error=? WHERE id=?", (state, error, item["id"])
        )


async def delivery_worker(bot):
    recover_interrupted()
    while True:
        try:
            await broadcasts_due(bot)
            await scheduled_due(bot)
        except Exception:
            log.exception("Delivery queue iteration failed")
        await asyncio.sleep(2)
