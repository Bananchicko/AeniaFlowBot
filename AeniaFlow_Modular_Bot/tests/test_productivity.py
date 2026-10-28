from types import SimpleNamespace
from datetime import datetime, timezone
import pytest
from aeniaflow.core.database import Database
from aeniaflow.core.scheduling import parse_duration, parse_reminder, deliver_due
from unittest.mock import AsyncMock
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.methods import SendMessage


def test_notes_tasks_and_reminders_are_owner_scoped(repository):
    note = repository.save_note(1, "ИДЕЯ", "Секретный проект")
    task = repository.add_task(1, "Task")
    reminder = repository.add_reminder(1, 1, "Reminder", 1000)
    assert repository.note(2, note) is None
    assert not repository.delete_note(2, note)
    assert not repository.change_task(2, task, True)
    assert not repository.cancel_reminder(2, reminder)
    assert repository.notes(2) == []
    assert len(repository.notes(1, "идея")) == 1
    assert repository.save_note(1, "ИДЕЯ", "Обновлено") == note


def test_queue_survives_restart_and_recovers_expired_lease(tmp_path):
    path = str(tmp_path / "queue.db")
    repo = Database(path)
    key = repo.add_reminder(1, 1, "Persistent", 1000)
    assert len(repo.claim_due(1001)) == 1
    repo.close()
    other = Database(path)
    assert other.claim_due(1002) == []
    assert other.claim_due(1121)[0]["id"] == key
    other.complete_reminder(key, 1121)
    assert other.claim_due(2000) == []
    other.close()


def test_two_connections_cannot_claim_same_job(tmp_path):
    path = str(tmp_path / "queue.db")
    first, second = Database(path), Database(path)
    first.add_reminder(1, 1, "Once", 1000)
    assert len(first.claim_due(1000)) == 1
    assert second.claim_due(1000) == []
    first.close()
    second.close()


def test_repeat_skips_missed_intervals_without_burst(repository):
    key = repository.add_reminder(1, 1, "Daily", 1000, 60)
    repository.claim_due(2000)
    repository.complete_reminder(key, 2000)
    assert repository.reminders(1)[0]["due_at"] == 2020
    assert repository.claim_due(2000) == []
    repository.cancel_reminder(1, key)
    assert repository.claim_due(3000) == []


@pytest.mark.parametrize("text,result", [("30", 30), ("2h30m", 9000), ("1д2ч", 93600), ("1w", 604800)])
def test_duration(text, result):
    assert parse_duration(text) == result


@pytest.mark.parametrize("text", ["-1", "0", "nan", "3foo", "1m2", "1.5h", "999999d"])
def test_bad_duration(text):
    with pytest.raises(ValueError):
        parse_duration(text)


def test_absolute_timezone_and_dst_validation():
    now = int(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp())
    due, interval, text = parse_reminder("2026-01-02 12:00 Встреча", "Europe/Moscow", now=now)
    assert datetime.fromtimestamp(due, timezone.utc).hour == 9
    assert not interval and text == "Встреча"
    for stamp in ["2026-03-29 02:30", "2026-10-25 02:30"]:
        with pytest.raises(ValueError):
            parse_reminder(stamp + " Meeting", "Europe/Berlin", now=now)


async def test_delivery_plain_text_and_error_retries(repository):
    repository.add_reminder(42, 42, "<b>literal & text</b>", 1000)
    bot = AsyncMock()
    bot.get_chat_member.return_value = SimpleNamespace(status="member")
    await deliver_due(bot, now=1001)
    assert bot.send_message.await_args.kwargs["parse_mode"] is None
    assert "<b>literal & text</b>" in bot.send_message.await_args.args[1]
    assert repository.claim_due(1002) == []
    repository.add_reminder(42, 42, "Retry", 1000)
    bot.send_message.side_effect = TelegramRetryAfter(
        method=SendMessage(chat_id=42, text="x"), message="Retry", retry_after=10
    )
    await deliver_due(bot, now=1001)
    row = repository.reminders(42)[0]
    assert row["status"] == "pending" and row["due_at"] == 1012
    bot.send_message.side_effect = TelegramForbiddenError(
        method=SendMessage(chat_id=42, text="x"), message="blocked"
    )
    await deliver_due(bot, now=1012)
    assert repository.reminders(42)[0]["status"] == "failed"


def test_delete_personal_data_preserves_paid_subscription(repository):
    repository.save_note(42, "title", "body")
    repository.add_task(42, "task")
    order = repository.create_order(42, "month", 50, 30, now=1000)
    repository.fulfill_order(repository.payload(order["order_id"]), 42, "XTR", 50, "charge", now=1001)
    expiry = repository.premium_until(42)
    repository.clear_personal_data(42)
    assert repository.notes(42) == [] and repository.tasks(42) == []
    assert repository.premium_until(42) == expiry
    assert repository.payment("charge") is not None
