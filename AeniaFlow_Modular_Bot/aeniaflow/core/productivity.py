"""Owner-scoped notes, tasks and durable reminder queue."""

from __future__ import annotations
from time import time


class ProductivityRepository:
    def organizer_counts(self, user_id: int):
        return self.conn.execute(
            "SELECT (SELECT COUNT(*) FROM notes WHERE user_id=:owner) AS notes, "
            "(SELECT COUNT(*) FROM tasks WHERE user_id=:owner AND done=0) AS tasks, "
            "(SELECT COUNT(*) FROM reminders WHERE user_id=:owner AND status IN ('pending','sending')) AS reminders, "
            "(SELECT COUNT(*) FROM reminders WHERE user_id=:owner AND status='failed') AS failed_reminders",
            {"owner": user_id},
        ).fetchone()

    def migrate_business_reminders(self):
        if self.conn.execute("PRAGMA user_version").fetchone()[0] >= 5:
            return
        with self.atomic():
            columns = {r["name"] for r in self.conn.execute("PRAGMA table_info(reminders)")}
            if "business_connection_id" not in columns:
                self.conn.execute("ALTER TABLE reminders ADD COLUMN business_connection_id TEXT")
            self.conn.execute("PRAGMA user_version=5")

    def save_note(self, user_id: int, title: str, body: str) -> int:
        title, body = title.strip(), body.strip()
        if not 1 <= len(title) <= 80 or not 1 <= len(body) <= 8000:
            raise ValueError("Название: 1–80 символов, заметка: 1–8000 символов.")
        with self.atomic():
            existing = self.conn.execute(
                "SELECT id FROM notes WHERE user_id=? AND title=?", (user_id, title)
            ).fetchone()
            count = self.conn.execute("SELECT COUNT(*) FROM notes WHERE user_id=?", (user_id,)).fetchone()[0]
            if not existing and count >= 100:
                raise ValueError("Достигнут лимит: 100 заметок.")
            self.conn.execute(
                "INSERT INTO notes(user_id,title,body,created_at) VALUES(?,?,?,?) ON CONFLICT(user_id,title) DO UPDATE SET body=excluded.body",
                (user_id, title, body, int(time())),
            )
            return self.conn.execute(
                "SELECT id FROM notes WHERE user_id=? AND title=?", (user_id, title)
            ).fetchone()["id"]

    def notes(self, user_id: int, query: str = "", offset: int = 0):
        # SQLite lower() only handles ASCII; casefold handles Russian note titles too.
        rows = self.conn.execute(
            "SELECT * FROM notes WHERE user_id=? ORDER BY id DESC", (user_id,)
        ).fetchall()
        key = query.casefold()
        return [row for row in rows if key in row["title"].casefold() or key in row["body"].casefold()][
            offset : offset + 10
        ]

    def note(self, user_id: int, note_id: int):
        return self.conn.execute(
            "SELECT * FROM notes WHERE user_id=? AND id=?", (user_id, note_id)
        ).fetchone()

    def delete_note(self, user_id: int, note_id: int) -> bool:
        return bool(
            self.conn.execute("DELETE FROM notes WHERE user_id=? AND id=?", (user_id, note_id)).rowcount
        )

    def add_task(self, user_id: int, text: str) -> int:
        if not 1 <= len(text.strip()) <= 500:
            raise ValueError("Задача: от 1 до 500 символов.")
        with self.atomic():
            count = self.conn.execute(
                "SELECT COUNT(*) FROM tasks WHERE user_id=? AND done=0", (user_id,)
            ).fetchone()[0]
            if count >= 100:
                raise ValueError("Достигнут лимит: 100 активных задач.")
            return self.conn.execute(
                "INSERT INTO tasks(user_id,text,created_at) VALUES(?,?,?)",
                (user_id, text.strip(), int(time())),
            ).lastrowid

    def tasks(self, user_id: int, offset: int = 0):
        return self.conn.execute(
            "SELECT * FROM tasks WHERE user_id=? ORDER BY done,id DESC LIMIT 10 OFFSET ?", (user_id, offset)
        ).fetchall()

    def change_task(self, user_id: int, task_id: int, done: bool) -> bool:
        return bool(
            self.conn.execute(
                "UPDATE tasks SET done=? WHERE user_id=? AND id=?", (int(done), user_id, task_id)
            ).rowcount
        )

    def delete_task(self, user_id: int, task_id: int) -> bool:
        return bool(
            self.conn.execute("DELETE FROM tasks WHERE user_id=? AND id=?", (user_id, task_id)).rowcount
        )

    def add_reminder(
        self,
        user_id: int,
        chat_id: int,
        text: str,
        due_at: int,
        interval: int = 0,
        thread_id: int | None = None,
        *,
        business_connection_id: str | None = None,
    ) -> int:
        if not 1 <= len(text) <= 1000 or interval < 0 or interval and interval < 60:
            raise ValueError("Текст: 1–1000 символов; повтор — не чаще раза в минуту.")
        if business_connection_id:
            connection = self.connection_owner(business_connection_id)
            if (
                not connection
                or connection["owner_id"] != user_id
                or not connection["is_enabled"]
                or not connection["can_reply"]
            ):
                raise ValueError("Подключение для напоминания недоступно.")
        with self.atomic():
            count = self.conn.execute(
                "SELECT COUNT(*) FROM reminders WHERE user_id=? AND status IN ('pending','sending')",
                (user_id,),
            ).fetchone()[0]
            if count >= 50:
                raise ValueError("Достигнут лимит: 50 активных напоминаний.")
            return self.conn.execute(
                "INSERT INTO reminders(user_id,chat_id,thread_id,text,due_at,interval_seconds,business_connection_id) VALUES(?,?,?,?,?,?,?)",
                (user_id, chat_id, thread_id, text, due_at, interval, business_connection_id),
            ).lastrowid

    def reminders(self, user_id: int, offset: int = 0):
        return self.conn.execute(
            "SELECT * FROM reminders WHERE user_id=? AND status IN ('pending','sending','failed') ORDER BY due_at LIMIT 10 OFFSET ?",
            (user_id, offset),
        ).fetchall()

    def cancel_reminder(self, user_id: int, reminder_id: int) -> bool:
        return bool(
            self.conn.execute(
                "UPDATE reminders SET status='cancelled' WHERE user_id=? AND id=? AND status IN ('pending','sending','failed')",
                (user_id, reminder_id),
            ).rowcount
        )

    def claim_due(self, now: int, limit: int = 20):
        with self.atomic():
            self.conn.execute(
                "UPDATE reminders SET status='pending' WHERE status='sending' AND lease_until<=?", (now,)
            )
            rows = self.conn.execute(
                "SELECT * FROM reminders WHERE status='pending' AND due_at<=? ORDER BY due_at LIMIT ?",
                (now, limit),
            ).fetchall()
            for row in rows:
                self.conn.execute(
                    "UPDATE reminders SET status='sending',lease_until=? WHERE id=?", (now + 120, row["id"])
                )
            return rows

    def complete_reminder(self, reminder_id: int, now: int):
        with self.atomic():
            row = self.conn.execute(
                "SELECT * FROM reminders WHERE id=? AND status='sending'", (reminder_id,)
            ).fetchone()
            if not row:
                return
            interval = row["interval_seconds"]
            if interval:
                due = row["due_at"] + max(1, (now - row["due_at"]) // interval + 1) * interval
                self.conn.execute(
                    "UPDATE reminders SET status='pending',due_at=?,attempts=0,last_error='' WHERE id=?",
                    (due, reminder_id),
                )
            else:
                self.conn.execute("UPDATE reminders SET status='sent' WHERE id=?", (reminder_id,))

    def fail_reminder(
        self, reminder_id: int, now: int, error: str, retry_after: int | None = None, permanent: bool = False
    ):
        with self.atomic():
            row = self.conn.execute(
                "SELECT * FROM reminders WHERE id=? AND status='sending'", (reminder_id,)
            ).fetchone()
            if not row:
                return
            attempts = row["attempts"] + 1
            status = "failed" if permanent or attempts >= 5 else "pending"
            self.conn.execute(
                "UPDATE reminders SET status=?,attempts=?,due_at=?,last_error=? WHERE id=?",
                (
                    status,
                    attempts,
                    now + (retry_after or min(3600, 30 * 2**attempts)),
                    error[:100],
                    reminder_id,
                ),
            )

    def export_user(self, user_id: int):
        result = {}
        for table in ("users", "notes", "tasks", "reminders", "payments"):
            result[table] = [
                dict(row) for row in self.conn.execute(f"SELECT * FROM {table} WHERE user_id=?", (user_id,))
            ]
        for table in (
            "private_dialogs",
            "business_connections",
            "autoreply",
            "saved_replies",
            "scheduled_messages",
            "reply_rules",
        ):
            result[table] = [
                dict(row) for row in self.conn.execute(f"SELECT * FROM {table} WHERE owner_id=?", (user_id,))
            ]
        result["plus_grants"] = [
            dict(row)
            for row in self.conn.execute(
                "SELECT id,days,created_at,revoked FROM plus_grants WHERE user_id=?", (user_id,)
            )
        ]
        result["referral_rewards"] = [
            dict(row)
            for row in self.conn.execute(
                "SELECT stars_milli,days,revoked FROM referral_rewards WHERE inviter_id=?", (user_id,)
            )
        ]
        result["referral_payouts"] = [
            dict(row)
            for row in self.conn.execute(
                "SELECT id,stars,state,created_at,resolved_at FROM referral_payouts WHERE user_id=?",
                (user_id,),
            )
        ]
        result["referral_balance_milli"] = self.referral_balance(user_id)
        return result

    def clear_personal_data(self, user_id: int):
        with self.atomic():
            for table in ("notes", "tasks", "reminders", "game_state", "usage"):
                self.conn.execute(f"DELETE FROM {table} WHERE user_id=?", (user_id,))
            self.conn.execute("DELETE FROM private_dialogs WHERE owner_id=?", (user_id,))
            self.conn.execute("DELETE FROM autoreply WHERE owner_id=?", (user_id,))
            self.conn.execute("DELETE FROM saved_replies WHERE owner_id=?", (user_id,))
            self.conn.execute(
                "DELETE FROM ui_panels WHERE chat_id=? OR connection_id IN (SELECT connection_id FROM business_connections WHERE owner_id=?)",
                (user_id, user_id),
            )
            self.conn.execute(
                "DELETE FROM autoreply_delivery WHERE connection_id IN (SELECT connection_id FROM business_connections WHERE owner_id=?)",
                (user_id,),
            )
            self.conn.execute("DELETE FROM business_connections WHERE owner_id=?", (user_id,))
            self.conn.execute(
                "UPDATE users SET username='',first_name='',afk_reason=NULL,afk_since=NULL,timezone='UTC',mail_enabled=0,watermark_style='auto',watermark_position='br',watermark_opacity=55,watermark_count=5,watermark_scatter='center' WHERE user_id=?",
                (user_id,),
            )
