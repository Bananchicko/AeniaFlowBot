from __future__ import annotations
import secrets
import time
from aiogram import Bot
from aiogram.types import Message, CallbackQuery
from aiogram.exceptions import TelegramBadRequest
from aeniaflow.core.runtime import db, BoundedCache
from aeniaflow.core.helpers import esc
from aeniaflow.keyboards import kb
from aeniaflow.core.access import is_owner
from aeniaflow.core.ui import panel as ui_panel


async def panel(message, text, reply_markup=None):
    return await ui_panel(message, text, reply_markup, protect_content=True, admin_only=True)


confirmations = BoundedCache(200)


def authorized(user_id: int, chat_type: str) -> bool:
    return chat_type == "private" and is_owner(user_id)


async def handle(message: Message, args: str, bot: Bot):
    if not authorized(message.from_user.id, message.chat.type):
        await panel(message, "Этот раздел доступен владельцу бота в личном чате.")
        return
    stats = db.stats()
    await panel(
        message,
        "<b>Администрирование AeniaFlow</b>\n"
        + f'Пользователей: {stats["users"]}\nАктивных Plus: {stats["premium"]}\nОплаченных заказов: {stats["payments"]}\nУчтено Stars: {stats["stars"]}\nНезавершённых возвратов: {stats["refund_pending"]}\nАктивных напоминаний: {stats["reminders"]}\n\n'
        "<code>.refund CHARGE_ID</code> — подготовить возврат\n<code>.audit</code> — последние действия\n\nСумма Stars рассчитана по локальным платежам; это не текущий баланс Telegram.",
    )


async def audit(message, args, bot):
    if not authorized(message.from_user.id, message.chat.type):
        return
    rows = db.conn.execute("SELECT * FROM audit ORDER BY id DESC LIMIT 15").fetchall()
    await panel(
        message,
        "\n".join(
            f'{r["id"]} · {r["actor_id"]} · {esc(r["action"])} · {esc(r["detail"][:100])}' for r in rows
        )
        or "Журнал пуст.",
    )


async def refund(message: Message, args: str, bot: Bot):
    if not authorized(message.from_user.id, message.chat.type):
        await panel(message, "Возвраты доступны владельцу бота в личном чате.")
        return
    row = db.payment(args.strip())
    if not row:
        await panel(message, "Платёж не найден. Укажите ID чека: <code>.refund CHARGE_ID</code>.")
        return
    if row["status"] == "refunded":
        await panel(message, "Этот платёж уже возвращён.")
        return
    token = secrets.token_hex(10)
    confirmations[token] = (message.from_user.id, row["charge_id"], time.monotonic() + 300)
    await panel(
        message,
        f'<b>Подтверждение возврата</b>\nПользователь: <code>{row["user_id"]}</code>\nСумма: <b>{row["amount"]} ⭐</b>\nСрок: {row["days"]} дней\n\nStars будут возвращены через Telegram, срок подписки пересчитан.',
        reply_markup=kb([[("Вернуть Stars", f"refund:{token}")], [("Отмена", f"dismiss:{token}")]]),
    )


async def confirm_refund(callback: CallbackQuery, bot: Bot, token: str):
    if not callback.message or not authorized(callback.from_user.id, callback.message.chat.type):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    item = confirmations.get(token)
    if not item or item[0] != callback.from_user.id or item[2] < time.monotonic():
        await callback.answer("Подтверждение устарело. Повторите .refund.", show_alert=True)
        return
    confirmations.pop(token, None)
    await callback.answer("Обрабатываю возврат…")
    row = db.payment(item[1])
    if not db.begin_refund(item[1]):
        await panel(callback.message, "Платёж уже возвращён.")
        return
    try:
        await bot.refund_star_payment(user_id=row["user_id"], telegram_payment_charge_id=row["charge_id"])
    except TelegramBadRequest as exc:
        if "CHARGE_ALREADY_REFUNDED" not in exc.message.upper():
            await panel(
                callback.message,
                "Telegram отклонил возврат. Статус сохранён как «возврат проверяется». Проверьте чек и повторите .refund.",
            )
            return
    except Exception:
        # Outcome may be ambiguous. Keep pending and allow an idempotent retry.
        await panel(
            callback.message,
            "Нет подтверждения от Telegram. Возврат ожидает проверки; повторите .refund с тем же чеком.",
        )
        return
    db.apply_refund(row["charge_id"])
    db.audit(
        callback.from_user.id,
        "refund",
        f'user={row["user_id"]};amount={row["amount"]};charge={row["charge_id"]}',
    )
    await panel(callback.message, "✅ Stars возвращены. Подписка пересчитана.")


async def reconcile(message: Message, args: str, bot: Bot):
    """Recover missed receipts/refunds from Telegram's own ledger, one bounded page at a time."""
    from aeniaflow.core.billing import PaymentError

    if not authorized(message.from_user.id, message.chat.type):
        await panel(message, "Сверка доступна владельцу бота в личном чате.")
        return
    if args and (not args.isdigit() or int(args) > 1000000):
        raise ValueError("Пример: .reconcile 0; следующая страница: .reconcile 100")
    offset = int(args or "0")
    page = await bot.get_star_transactions(offset=offset, limit=100)
    recovered, refunded, ignored = 0, 0, 0
    # Process purchases before refunds, including when the page contains both for one charge.
    for tx in sorted(page.transactions, key=lambda x: x.date):
        source = tx.source
        if not source or getattr(source, "transaction_type", None) != "invoice_payment":
            continue
        if not getattr(source, "invoice_payload", None):
            ignored += 1
            continue
        try:
            result = db.settle_payment(
                source.invoice_payload, source.user.id, "XTR", tx.amount, tx.id, now=int(tx.date.timestamp())
            )
            recovered += int(result.created)
        except PaymentError:
            ignored += 1
    for tx in page.transactions:
        receiver = tx.receiver
        if not receiver or getattr(receiver, "type", None) != "user" or not db.payment(tx.id):
            continue
        try:
            refunded += int(db.apply_refund(tx.id, user_id=receiver.user.id, amount=abs(tx.amount)))
        except PaymentError:
            ignored += 1
    db.audit(
        message.from_user.id,
        "reconcile",
        f"offset={offset};new={recovered};refunds={refunded};unmatched={ignored}",
    )
    await panel(
        message,
        f"Проверено транзакций: {len(page.transactions)}.\nВосстановлено оплат: {recovered}\nУчтено возвратов: {refunded}\nНе сопоставлено: {ignored}\nСледующая страница: <code>.reconcile {offset+100}</code>.\nЕсли не сопоставлены старые записи, сверяйте чек вручную; повторный запуск безопасен.",
    )
