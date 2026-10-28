"""Referral rewards use confirmed receipts, never invoice requests or screenshots."""

import time


class ReferralRepository:
    def bind_referral(self, user_id, inviter_id=None):
        with self.atomic():
            row = self.get_user(user_id)
            if not row or row["referral_locked"]:
                return False
            self.conn.execute("UPDATE users SET referral_locked=1 WHERE user_id=?", (user_id,))
            if not inviter_id or inviter_id == user_id:
                return False
            inviter = self.get_user(inviter_id)
            if not inviter or inviter["banned"]:
                return False
            if self.conn.execute("SELECT 1 FROM payments WHERE user_id=?", (user_id,)).fetchone():
                return False
            self.conn.execute(
                "INSERT OR IGNORE INTO referrals(user_id,inviter_id,created_at) VALUES(?,?,?)",
                (user_id, inviter_id, int(time.time())),
            )
            return True

    def reward_referral(self, charge_id):
        payment = self.payment(charge_id)
        referral = (
            self.conn.execute("SELECT * FROM referrals WHERE user_id=?", (payment["user_id"],)).fetchone()
            if payment
            else None
        )
        if not referral or payment["status"] != "paid":
            return
        inviter = referral["inviter_id"]
        stars = payment["amount"] * 500 if payment["days"] >= 30 else 0
        days = payment["amount"] // 25 if payment["amount"] >= 100 else 0
        if not stars and not days:
            return
        with self.atomic():
            changed = self.conn.execute(
                "INSERT OR IGNORE INTO referral_rewards(charge_id,inviter_id,buyer_id,stars_milli,days) VALUES(?,?,?,?,?)",
                (charge_id, inviter, payment["user_id"], stars, days),
            ).rowcount
            if not changed:
                return
            if days:
                self.conn.execute(
                    "INSERT INTO plus_grants(user_id,days,created_at,reward_charge) VALUES(?,?,?,?)",
                    (inviter, days, payment["paid_at"], charge_id),
                )
                self._recalculate(inviter)
            self.audit(inviter, "referral_reward", f"{charge_id}: {stars}/1000 stars, {days} days")

    def reverse_referral(self, charge_id):
        row = self.conn.execute("SELECT * FROM referral_rewards WHERE charge_id=?", (charge_id,)).fetchone()
        if not row or row["revoked"]:
            return
        self.conn.execute("UPDATE referral_rewards SET revoked=1 WHERE charge_id=?", (charge_id,))
        self.conn.execute("UPDATE plus_grants SET revoked=1 WHERE reward_charge=?", (charge_id,))
        self._recalculate(row["inviter_id"])
        self.audit(row["inviter_id"], "referral_reversed", charge_id)

    def referral_balance(self, user_id):
        earned = self.conn.execute(
            "SELECT COALESCE(SUM(stars_milli),0) FROM referral_rewards WHERE inviter_id=? AND revoked=0",
            (user_id,),
        ).fetchone()[0]
        held = self.conn.execute(
            "SELECT COALESCE(SUM(stars),0)*1000 FROM referral_payouts WHERE user_id=? AND state IN ('pending','paid')",
            (user_id,),
        ).fetchone()[0]
        return earned - held

    def request_payout(self, user_id):
        with self.atomic():
            if self.conn.execute(
                "SELECT 1 FROM referral_payouts WHERE user_id=? AND state='pending'", (user_id,)
            ).fetchone():
                raise ValueError("У вас уже есть заявка на выплату.")
            amount = self.referral_balance(user_id) // 1000
            if amount < 1:
                raise ValueError("Для заявки нужен доступный баланс от 1 Stars.")
            return self.conn.execute(
                "INSERT INTO referral_payouts(user_id,stars,created_at) VALUES(?,?,?)",
                (user_id, amount, int(time.time())),
            ).lastrowid

    def resolve_payout(self, actor, identifier, paid):
        with self.atomic():
            row = self.conn.execute(
                "SELECT * FROM referral_payouts WHERE id=? AND state='pending'", (identifier,)
            ).fetchone()
            if not row:
                return False
            # Refunds can make a reserved balance negative before payout occurs.
            if paid and self.referral_balance(row["user_id"]) < 0:
                raise ValueError(
                    "Награда была уменьшена возвратом. Отклоните заявку и попросите создать новую."
                )
            self.conn.execute(
                "UPDATE referral_payouts SET state=?,resolved_at=?,actor=? WHERE id=?",
                ("paid" if paid else "rejected", int(time.time()), actor, identifier),
            )
            self.audit(
                actor, "referral_payout_recorded" if paid else "referral_payout_rejected", str(identifier)
            )
            return True
