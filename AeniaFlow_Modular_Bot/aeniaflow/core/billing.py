"""Stars orders and entitlements. No network calls inside SQLite transactions."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from time import time


class PaymentError(ValueError):
    pass


@dataclass(frozen=True)
class PaymentResult:
    expires_at: int
    created: bool


class BillingRepository:
    def create_order(self, user_id: int, plan: str, amount: int, days: int, *, now: int | None = None):
        now = int(time()) if now is None else now
        if amount <= 0 or days <= 0:
            raise PaymentError("Некорректный тариф.")
        order_id = secrets.token_urlsafe(18)
        with self.atomic():
            self.conn.execute("INSERT OR IGNORE INTO users(user_id) VALUES(?)", (user_id,))
            self.conn.execute(
                "INSERT INTO orders(order_id,user_id,plan,amount,days,created_at,expires_at) VALUES(?,?,?,?,?,?,?)",
                (order_id, user_id, plan, amount, days, now, now + 3600),
            )
        return self.order(order_id)

    def order(self, order_id: str):
        return self.conn.execute("SELECT * FROM orders WHERE order_id=?", (order_id,)).fetchone()

    @staticmethod
    def payload(order_id: str) -> str:
        return "af2:" + order_id

    def validate_order(self, payload: str, user_id: int, currency: str, amount: int):
        if not payload.startswith("af2:"):
            raise PaymentError("Счёт устарел. Откройте .premium и создайте новый.")
        row = self.order(payload[4:])
        if not row or row["user_id"] != user_id:
            raise PaymentError("Счёт принадлежит другому пользователю или не найден.")
        if currency != "XTR" or amount != row["amount"]:
            raise PaymentError("Сумма или валюта не совпадает со счётом. Принимаются только Stars.")
        return row

    def approve_order(
        self, payload: str, user_id: int, currency: str, amount: int, query_id: str, *, now: int | None = None
    ):
        now = int(time()) if now is None else now
        with self.atomic():
            row = self.validate_order(payload, user_id, currency, amount)
            if row["status"] != "pending" or row["expires_at"] < now:
                raise PaymentError("Этот счёт уже закрыт или устарел. Создайте новый в .premium.")
            if row["checkout_id"] and row["checkout_id"] != query_id:
                raise PaymentError("Этот счёт уже обрабатывается. Дождитесь результата оплаты.")
            self.conn.execute("UPDATE orders SET checkout_id=? WHERE order_id=?", (query_id, row["order_id"]))

    def fulfill_order(
        self,
        payload: str,
        user_id: int,
        currency: str,
        amount: int,
        charge_id: str,
        *,
        now: int | None = None,
    ) -> PaymentResult:
        now = int(time()) if now is None else now
        if not charge_id:
            raise PaymentError("Отсутствует идентификатор платежа.")
        with self.atomic():
            row = self.validate_order(payload, user_id, currency, amount)
            existing = self.payment(charge_id)
            if existing:
                if (
                    existing["user_id"] != user_id
                    or existing["order_id"] != row["order_id"]
                    or existing["amount"] != amount
                ):
                    raise PaymentError("Идентификатор платежа не соответствует заказу.")
                return PaymentResult(self.premium_until(user_id), False)
            if row["status"] != "pending":
                raise PaymentError("По этому заказу уже есть другой платёж. Обратитесь в .paysupport.")
            # SuccessfulPayment remains authoritative after invoice TTL or delayed delivery.
            expiry = max(now, self.premium_until(user_id)) + row["days"] * 86400
            self.conn.execute(
                "INSERT INTO payments(charge_id,user_id,plan,amount,paid_at,expires_at,days,order_id) VALUES(?,?,?,?,?,?,?,?)",
                (charge_id, user_id, row["plan"], amount, now, expiry, row["days"], row["order_id"]),
            )
            self.conn.execute("UPDATE orders SET status='paid' WHERE order_id=?", (row["order_id"],))
            expiry = self._recalculate(user_id)
            self.reward_referral(charge_id)
        return PaymentResult(expiry, True)

    def payment(self, charge_id: str):
        return self.conn.execute("SELECT * FROM payments WHERE charge_id=?", (charge_id,)).fetchone()

    def payments_for(self, user_id: int, limit: int = 10, offset: int = 0):
        return self.conn.execute(
            "SELECT * FROM payments WHERE user_id=? ORDER BY paid_at DESC,rowid DESC LIMIT ? OFFSET ?",
            (user_id, limit, offset),
        ).fetchall()

    def begin_refund(self, charge_id: str) -> bool:
        with self.atomic():
            row = self.payment(charge_id)
            if not row:
                raise PaymentError("Платёж не найден.")
            if row["status"] == "refunded":
                return False
            self.conn.execute("UPDATE payments SET status='refund_pending' WHERE charge_id=?", (charge_id,))
        return True

    def apply_refund(
        self,
        charge_id: str,
        *,
        user_id: int | None = None,
        amount: int | None = None,
        payload: str | None = None,
    ) -> bool:
        with self.atomic():
            row = self.payment(charge_id)
            if not row:
                raise PaymentError("Возвращённый платёж не найден в базе.")
            if (user_id is not None and row["user_id"] != user_id) or (
                amount is not None and row["amount"] != amount
            ):
                raise PaymentError("Данные возврата не совпадают с платежом.")
            if payload and payload.startswith("aeniaflow_plus|"):
                import hashlib

                payload = self.payload("legacy_" + hashlib.sha256(payload.encode()).hexdigest()[:32])
            if payload is not None and row["order_id"] and payload != self.payload(row["order_id"]):
                raise PaymentError("Заказ возврата не совпадает с платежом.")
            if row["status"] == "refunded":
                return False
            self.conn.execute(
                "UPDATE payments SET status='refunded',refunded_at=? WHERE charge_id=?",
                (int(time()), charge_id),
            )
            if row["order_id"]:
                self.conn.execute("UPDATE orders SET status='refunded' WHERE order_id=?", (row["order_id"],))
            self._recalculate(row["user_id"])
            self.reverse_referral(charge_id)
        return True

    def _recalculate(self, user_id: int) -> int:
        from aeniaflow.core.admin_repository import LIFETIME

        until = self.get_user(user_id)["legacy_until"]
        payments = self.conn.execute(
            "SELECT rowid AS sequence,* FROM payments WHERE user_id=? AND status!='refunded' AND access_revoked=0 ORDER BY paid_at,rowid",
            (user_id,),
        ).fetchall()
        grants = self.conn.execute(
            "SELECT * FROM plus_grants WHERE user_id=? AND revoked=0", (user_id,)
        ).fetchall()
        events = [(r["paid_at"], 0, r["sequence"], r) for r in payments] + [
            (r["created_at"], 1, r["id"], r) for r in grants
        ]
        for stamp, kind, _, event in sorted(events, key=lambda item: item[:3]):
            until = (
                LIFETIME
                if kind == 1 and event["days"] == 0
                else min(LIFETIME, max(until, stamp) + event["days"] * 86400)
            )
            if kind == 0:
                self.conn.execute(
                    "UPDATE payments SET expires_at=? WHERE charge_id=?", (until, event["charge_id"])
                )
        self.conn.execute("UPDATE users SET premium_until=? WHERE user_id=?", (until, user_id))
        return until

    def settle_payment(
        self,
        payload: str,
        user_id: int,
        currency: str,
        amount: int,
        charge_id: str,
        *,
        now: int | None = None,
    ) -> PaymentResult:
        # Only Telegram-confirmed receipts use this compatibility path. Pre-checkout rejects old invoices.
        if payload.startswith("aeniaflow_plus|"):
            import hashlib

            parts = payload.split("|")
            legacy = {"month": (50, 30), "quarter": (100, 90), "year": (400, 365)}
            if (
                len(parts) != 4
                or not parts[1].isdigit()
                or int(parts[1]) != user_id
                or not parts[3].isdigit()
            ):
                raise PaymentError("Неверный старый счёт.")
            plan = legacy.get(parts[2])
            if not plan or currency != "XTR" or amount != plan[0]:
                raise PaymentError("Данные старого платежа не совпадают.")
            existing = self.payment(charge_id)
            if existing:
                if (
                    existing["user_id"] != user_id
                    or existing["amount"] != amount
                    or existing["plan"] != parts[2]
                ):
                    raise PaymentError("Платёж не соответствует пользователю.")
                return PaymentResult(self.premium_until(user_id), False)
            order_id = "legacy_" + hashlib.sha256(payload.encode()).hexdigest()[:32]
            with self.atomic():
                self.conn.execute("INSERT OR IGNORE INTO users(user_id) VALUES(?)", (user_id,))
                self.conn.execute(
                    "INSERT OR IGNORE INTO orders(order_id,user_id,plan,amount,days,created_at,expires_at) VALUES(?,?,?,?,?,?,?)",
                    (order_id, user_id, parts[2], amount, plan[1], int(parts[3]), int(parts[3]) + 3600),
                )
            payload = self.payload(order_id)
        return self.fulfill_order(payload, user_id, currency, amount, charge_id, now=now)
