import pytest
from aiogram.types import User
from aeniaflow.core import access
from test_revision_28 import OWNER, callback_data
from test_revision_21 import requests, texts


def person(repo, identifier):
    repo.upsert_user(User(id=identifier, is_bot=False, first_name=f"User{identifier}"))


def buy(repo, user, amount=100, days=30, charge="receipt", now=None):
    order = repo.create_order(user, "test", amount, days, now=now)
    result = repo.fulfill_order(repo.payload(order["order_id"]), user, "XTR", amount, charge, now=now)
    return order, result


async def test_deeplink_records_first_inviter_once_even_before_subscription(client, repository):
    await client.send("/start", user_id=90)
    await client.send("/start ref_90")
    assert repository.conn.execute("SELECT inviter_id FROM referrals WHERE user_id=42").fetchone()[0] == 90
    await client.send("/start ref_91")
    assert repository.conn.execute("SELECT inviter_id FROM referrals WHERE user_id=42").fetchone()[0] == 90
    await client.send("/start", user_id=55)
    await client.send("/start ref_90", user_id=55)
    assert not repository.conn.execute("SELECT * FROM referrals WHERE user_id=55").fetchone()


@pytest.mark.parametrize("inviter", [42, 999])
def test_referral_rejects_self_and_unknown(repository, inviter):
    person(repository, 42)
    assert not repository.bind_referral(42, inviter)
    assert not repository.conn.execute("SELECT * FROM referrals").fetchone()


@pytest.mark.parametrize(
    "amount,days,stars,bonus",
    [(50, 30, 25, 0), (100, 30, 50, 4), (125, 90, 62.5, 5), (99, 365, 49.5, 0), (100, 7, 0, 4), (5, 1, 0, 0)],
)
def test_rewards_match_thresholds_and_each_receipt_is_idempotent(repository, amount, days, stars, bonus):
    person(repository, 90)
    person(repository, 42)
    repository.bind_referral(42, 90)
    order, result = buy(repository, 42, amount, days)
    expiry = repository.premium_until(90)
    assert repository.referral_balance(90) == stars * 1000
    assert bool(access.has_plus(90)) == bool(bonus)
    repository.fulfill_order(repository.payload(order["order_id"]), 42, "XTR", amount, "receipt")
    assert repository.referral_balance(90) == stars * 1000
    assert repository.premium_until(90) == expiry


def test_refund_reverses_reward_but_keeps_other_grants(repository):
    person(repository, 90)
    person(repository, 42)
    repository.bind_referral(42, 90)
    repository.grant_plus(OWNER, 90, 7)
    before = repository.premium_until(90)
    buy(repository, 42, 100, 30)
    assert repository.premium_until(90) == before + 4 * 86400
    repository.apply_refund("receipt")
    assert repository.referral_balance(90) == 0
    assert repository.premium_until(90) == before
    repository.apply_refund("receipt")
    assert repository.premium_until(90) == before


def test_revoke_does_not_erase_receipts_or_get_undone_by_refund(repository):
    person(repository, 42)
    buy(repository, 42, 100, 30, "old")
    repository.revoke_plus(OWNER, 42)
    assert repository.payment("old")["status"] == "paid" and not access.has_plus(42)
    buy(repository, 42, 50, 30, "new")
    expiry = repository.premium_until(42)
    repository.apply_refund("old")
    assert repository.premium_until(42) == expiry


def test_grant_then_purchase_and_refund_preserves_manual_entitlement(repository):
    person(repository, 42)
    repository.grant_plus(OWNER, 42, 30)
    before = repository.premium_until(42)
    buy(repository, 42, 100, 90)
    assert repository.premium_until(42) == before + 90 * 86400
    repository.apply_refund("receipt")
    assert repository.premium_until(42) == before


def test_payout_reservation_cannot_be_duplicated_and_refund_blocks_payment(repository):
    person(repository, 90)
    person(repository, 42)
    repository.bind_referral(42, 90)
    buy(repository, 42)
    identifier = repository.request_payout(90)
    assert repository.referral_balance(90) == 0
    with pytest.raises(ValueError):
        repository.request_payout(90)
    repository.apply_refund("receipt")
    with pytest.raises(ValueError):
        repository.resolve_payout(OWNER, identifier, True)
    assert repository.resolve_payout(OWNER, identifier, False)
    assert repository.referral_balance(90) == 0


def test_paid_payout_then_refund_creates_debt_not_free_new_credit(repository):
    person(repository, 90)
    person(repository, 42)
    repository.bind_referral(42, 90)
    buy(repository, 42)
    identifier = repository.request_payout(90)
    assert repository.resolve_payout(OWNER, identifier, True)
    assert not repository.resolve_payout(OWNER, identifier, True)
    repository.apply_refund("receipt")
    assert repository.referral_balance(90) == -50000
    buy(repository, 42, 100, 30, "new")
    assert repository.referral_balance(90) == 0


async def test_referral_and_admin_payout_flow_records_only_after_confirmation(client, repository):
    await client.send("/start", user_id=90)
    await client.send("/start ref_90")
    buy(repository, 42)
    await client.send(".ref", user_id=90)
    assert "баланс вашего Telegram" in "\n".join(texts(client))
    await client.callback("ref:payout", user_id=90)
    assert not repository.conn.execute("SELECT * FROM referral_payouts").fetchone()
    await client.callback("ref:confirm", user_id=90)
    payout = repository.conn.execute("SELECT * FROM referral_payouts").fetchone()
    await client.callback("admin:payouts:all", user_id=OWNER)
    await client.callback(f"admin:payoutask:{payout['id']}", user_id=OWNER)
    token = callback_data(client, "admin:payoutconfirm:")
    assert repository.conn.execute("SELECT state FROM referral_payouts").fetchone()[0] == "pending"
    await client.callback(token, user_id=42)
    assert repository.conn.execute("SELECT state FROM referral_payouts").fetchone()[0] == "pending"
    await client.callback(token, user_id=OWNER)
    assert repository.conn.execute("SELECT state FROM referral_payouts").fetchone()[0] == "paid"
    assert not requests(client, "transferBusinessAccountStars") and not requests(client, "refundStarPayment")
