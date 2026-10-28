import sqlite3
import pytest
from aeniaflow.core.billing import PaymentError
from aeniaflow.core.database import Database


def order(repo, user=42, plan="month", amount=50, days=30, now=1000):
    row = repo.create_order(user, plan, amount, days, now=now)
    return repo.payload(row["order_id"])


def test_first_payment_creates_user_and_is_idempotent(repository):
    payload = order(repository)
    first = repository.fulfill_order(payload, 42, "XTR", 50, "charge", now=1001)
    repeat = repository.fulfill_order(payload, 42, "XTR", 50, "charge", now=3000)
    assert first.created and not repeat.created
    assert first.expires_at == repeat.expires_at == 1001 + 30 * 86400
    assert len(repository.payments_for(42)) == 1


@pytest.mark.parametrize(
    "user,currency,amount",
    [(43, "XTR", 50), (42, "RUB", 50), (42, "USD", 50), (42, "XTR", 1), (42, "XTR", 5000)],
)
def test_invalid_checkout_cannot_grant_access(repository, user, currency, amount):
    payload = order(repository)
    with pytest.raises(PaymentError):
        repository.approve_order(payload, user, currency, amount, "checkout", now=1001)
    with pytest.raises(PaymentError):
        repository.fulfill_order(payload, user, currency, amount, "charge", now=1001)
    assert repository.premium_until(42) == 0


def test_unknown_expired_and_replayed_orders(repository):
    payload = order(repository)
    with pytest.raises(PaymentError):
        repository.approve_order("af2:unknown", 42, "XTR", 50, "q", now=1001)
    with pytest.raises(PaymentError):
        repository.approve_order(payload, 42, "XTR", 50, "q", now=5000)
    repository.approve_order(payload, 42, "XTR", 50, "q", now=1001)
    repository.approve_order(payload, 42, "XTR", 50, "q", now=1001)
    with pytest.raises(PaymentError):
        repository.approve_order(payload, 42, "XTR", 50, "other-query", now=1002)
    result = repository.fulfill_order(payload, 42, "XTR", 50, "charge", now=6000)
    assert result.created  # delayed confirmed receipt must still be fulfilled
    with pytest.raises(PaymentError):
        repository.fulfill_order(payload, 42, "XTR", 50, "second-charge", now=6001)
    with pytest.raises(PaymentError):
        repository.approve_order(payload, 42, "XTR", 50, "q", now=1002)


def test_price_is_fixed_in_order_not_current_plan(repository):
    payload = order(repository, amount=77)
    repository.approve_order(payload, 42, "XTR", 77, "q", now=1001)
    assert repository.fulfill_order(payload, 42, "XTR", 77, "charge", now=1002).created


def test_charge_collision_rolls_back_and_connection_is_usable(repository):
    first, second = order(repository), order(repository, user=43)
    repository.fulfill_order(first, 42, "XTR", 50, "same", now=1001)
    with pytest.raises(PaymentError):
        repository.fulfill_order(second, 43, "XTR", 50, "same", now=1002)
    assert not repository.conn.in_transaction
    assert repository.fulfill_order(second, 43, "XTR", 50, "different", now=1003).created


def test_sql_failure_cannot_half_activate(repository):
    payload = order(repository)
    repository.conn.execute(
        "CREATE TRIGGER break_payment BEFORE INSERT ON payments BEGIN SELECT RAISE(ABORT, 'test failure'); END"
    )
    with pytest.raises(sqlite3.IntegrityError):
        repository.fulfill_order(payload, 42, "XTR", 50, "charge", now=1001)
    assert repository.premium_until(42) == 0
    assert repository.order(payload[4:])["status"] == "pending"
    assert not repository.conn.in_transaction
    repository.conn.execute("DROP TRIGGER break_payment")
    assert repository.fulfill_order(payload, 42, "XTR", 50, "charge", now=1002).created


def test_renewal_refund_and_replayed_receipt(repository):
    p1, p2 = order(repository), order(repository, plan="quarter", amount=100, days=90)
    repository.fulfill_order(p1, 42, "XTR", 50, "first", now=1001)
    repository.fulfill_order(p2, 42, "XTR", 100, "second", now=1002)
    assert repository.premium_until(42) == 1001 + 120 * 86400
    assert repository.begin_refund("first")
    assert repository.apply_refund("first", user_id=42, amount=50, payload=p1)
    assert repository.premium_until(42) == 1002 + 90 * 86400
    assert not repository.apply_refund("first")
    assert not repository.fulfill_order(p1, 42, "XTR", 50, "first", now=1003).created
    assert repository.premium_until(42) == 1002 + 90 * 86400
    assert repository.apply_refund("second")
    assert repository.premium_until(42) == 0


def test_refund_wrong_owner_amount_or_payload_rejected(repository):
    payload = order(repository)
    repository.fulfill_order(payload, 42, "XTR", 50, "charge", now=1001)
    for kwargs in [{"user_id": 43}, {"amount": 1}, {"payload": "af2:other"}]:
        with pytest.raises(PaymentError):
            repository.apply_refund("charge", **kwargs)
    assert repository.payment("charge")["status"] == "paid"


def test_out_of_order_reconciliation_replays_actual_timeline(repository):
    early, late = order(repository), order(repository, now=1000 + 100 * 86400)
    repository.fulfill_order(late, 42, "XTR", 50, "late", now=1000 + 100 * 86400)
    repository.fulfill_order(early, 42, "XTR", 50, "early", now=1000)
    assert repository.premium_until(42) == 1000 + 130 * 86400


def test_legacy_schema_migrates_without_losing_entitlement(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """CREATE TABLE users(user_id INTEGER PRIMARY KEY,username TEXT DEFAULT '',first_name TEXT DEFAULT '',premium_until INTEGER DEFAULT 0,timezone TEXT DEFAULT 'UTC',afk_reason TEXT,afk_since INTEGER);
        CREATE TABLE payments(charge_id TEXT PRIMARY KEY,user_id INTEGER,plan TEXT,amount INTEGER,paid_at INTEGER,expires_at INTEGER);"""
        )
        connection.execute("INSERT INTO users(user_id,premium_until) VALUES(42,?)", (1000 + 30 * 86400,))
        connection.execute(
            "INSERT INTO payments VALUES('old-charge',42,'month',50,1000,?)", (1000 + 30 * 86400,)
        )
    migrated = Database(str(path))
    assert migrated.premium_until(42) == 1000 + 30 * 86400
    assert migrated.payment("old-charge")["days"] == 30
    assert list(tmp_path.glob("*.bak"))
    migrated.close()
    migrated = Database(str(path))
    migrated.apply_refund("old-charge")
    assert migrated.premium_until(42) == 1000
    migrated.close()


def test_legacy_inflight_stars_receipt_is_accepted_once(repository):
    payload = "aeniaflow_plus|42|month|1000"
    assert repository.settle_payment(payload, 42, "XTR", 50, "legacy", now=1001).created
    assert not repository.settle_payment(payload, 42, "XTR", 50, "legacy", now=1002).created
    with pytest.raises(PaymentError):
        repository.approve_order(payload, 42, "XTR", 50, "q", now=1001)


def test_legacy_refund_matches_original_payload(repository):
    payload = "aeniaflow_plus|42|month|1000"
    repository.settle_payment(payload, 42, "XTR", 50, "legacy", now=1001)
    assert repository.apply_refund("legacy", amount=50, payload=payload)
    assert repository.premium_until(42) == 0
