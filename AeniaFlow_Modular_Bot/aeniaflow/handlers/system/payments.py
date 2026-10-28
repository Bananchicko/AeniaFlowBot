"""The only payment path is Telegram Stars (XTR)."""

from __future__ import annotations
import logging
from aiogram import Bot, F, Router
from aiogram.types import Message, PreCheckoutQuery, LabeledPrice, User
from aeniaflow.catalog import PLANS
from aeniaflow.core.billing import PaymentError
from aeniaflow.core.runtime import db
from aeniaflow.core.ui import format_time
from config import settings
from aeniaflow.core.policy import banned, maintenance

router = Router(name="payments")
log = logging.getLogger(__name__)


async def send_invoice(bot: Bot, user: User, plan: str):
    if banned(user.id) or maintenance():
        raise PaymentError("Новые покупки сейчас недоступны. Поддержка: .paysupport")
    product = PLANS.get(plan)
    if not product:
        raise PaymentError("Неизвестный тариф.")
    if not settings.support_username:
        raise PaymentError("Продажи пока не открыты: владелец ещё не указал контакт платёжной поддержки.")
    db.upsert_user(user)
    order = db.create_order(user.id, plan, product["stars"], product["days"])
    await bot.send_invoice(
        chat_id=user.id,
        title=product["title"],
        description=f'Все функции AeniaFlow+ на {product["days"]} дней. Разовая оплата, без автосписаний. Условия: .terms; поддержка: .paysupport.',
        payload=db.payload(order["order_id"]),
        currency="XTR",
        provider_token="",
        prices=[LabeledPrice(label=product["title"], amount=order["amount"])],
        start_parameter="premium",
        protect_content=True,
    )


@router.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery):
    try:
        if banned(query.from_user.id) or maintenance():
            raise PaymentError("Оплата сейчас недоступна. Stars не списаны. Поддержка: .paysupport")
        db.approve_order(
            query.invoice_payload, query.from_user.id, query.currency, query.total_amount, query.id
        )
    except PaymentError as exc:
        await query.answer(ok=False, error_message=str(exc)[:200])
    except Exception:
        log.exception("Pre-checkout database failure")
        await query.answer(
            ok=False, error_message="Не удалось проверить заказ. Stars не списаны. Повторите позже."
        )
    else:
        await query.answer(ok=True)


@router.message(F.successful_payment)
async def activate_successful_payment(message: Message):
    payment = message.successful_payment
    if not payment or not message.from_user:
        return
    try:
        result = db.settle_payment(
            payment.invoice_payload,
            message.from_user.id,
            payment.currency,
            payment.total_amount,
            payment.telegram_payment_charge_id,
            now=int(message.date.timestamp()),
        )
    except PaymentError:
        log.error("Payment requires reconciliation; user_id=%s", message.from_user.id)
        await message.answer(
            "Платёж получен, но автоматическая активация не завершена. Откройте .paysupport и приложите чек Telegram."
        )
        return
    # Entitlement was committed before sending a notification; retries cannot add days twice.
    row = db.get_user(message.from_user.id)
    text = "✅ AeniaFlow+ активирован" if result.created else "✅ Этот платёж уже учтён"
    await message.answer(
        f'{text}.\nДоступ до <b>{format_time(result.expires_at, row["timezone"])}</b>.\nИстория и чек: .payments. Продлить: .premium.'
    )


@router.message(F.refunded_payment)
async def refunded_payment(message: Message):
    payment = message.refunded_payment
    if payment.currency != "XTR":
        return
    try:
        changed = db.apply_refund(
            payment.telegram_payment_charge_id, amount=payment.total_amount, payload=payment.invoice_payload
        )
    except PaymentError:
        log.error("Unknown or mismatched refund received")
        return
    if changed:
        await message.answer(
            "↩️ Возврат Stars учтён. Срок AeniaFlow+ пересчитан; остальные покупки сохранены. Статус: .profile."
        )
