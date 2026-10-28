from __future__ import annotations
import sqlite3
import time
from pathlib import Path
from typing import Any
from contextlib import contextmanager, closing
from aeniaflow.core.billing import BillingRepository
from aeniaflow.core.productivity import ProductivityRepository
from aeniaflow.core.private_chats import PrivateChatsRepository
from aeniaflow.core.management import ManagementRepository
from aeniaflow.core.admin_repository import AdminRepository
from aeniaflow.core.referrals import ReferralRepository


def now_ts() -> int:
    return int(time.time())


class Database(
    BillingRepository,
    ProductivityRepository,
    PrivateChatsRepository,
    ManagementRepository,
    AdminRepository,
    ReferralRepository,
):
    """Small SQLite repository. All SQL lives here, never inside command handlers."""

    def __init__(self, path: str):
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        existed = target.exists() and target.stat().st_size > 0
        self.conn = sqlite3.connect(str(target), timeout=3, isolation_level=None)
        version = self.conn.execute("PRAGMA user_version").fetchone()[0]
        if version > 8:
            self.conn.close()
            raise RuntimeError("База создана более новой версией AeniaFlow.")
        if existed and version < 8:
            backup_path = target.with_name(
                target.name + f".pre-v{2 if version < 2 else version + 1}-{time.time_ns()}.bak"
            )
            with closing(sqlite3.connect(str(backup_path))) as backup:
                self.conn.backup(backup)
        self.conn.row_factory = sqlite3.Row
        self.conn.create_function("CASEFOLD", 1, lambda value: (value or "").casefold(), deterministic=True)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript("""
        CREATE TABLE IF NOT EXISTS users(
            user_id INTEGER PRIMARY KEY, username TEXT NOT NULL DEFAULT '',
            first_name TEXT NOT NULL DEFAULT '', premium_until INTEGER NOT NULL DEFAULT 0,
            timezone TEXT NOT NULL DEFAULT 'UTC', afk_reason TEXT, afk_since INTEGER
        );
        CREATE TABLE IF NOT EXISTS warns(
            chat_id INTEGER NOT NULL, user_id INTEGER NOT NULL, count INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(chat_id,user_id)
        );
        CREATE TABLE IF NOT EXISTS group_settings(
            chat_id INTEGER NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL,
            PRIMARY KEY(chat_id,key)
        );
        CREATE TABLE IF NOT EXISTS business_connections(
            connection_id TEXT PRIMARY KEY, owner_id INTEGER NOT NULL,
            is_enabled INTEGER NOT NULL DEFAULT 1, can_reply INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS autoreply(
            owner_id INTEGER PRIMARY KEY, enabled INTEGER NOT NULL DEFAULT 0,
            reply_text TEXT NOT NULL DEFAULT 'Привет! Сейчас не могу ответить. Напишу вам позже.',
            cooldown INTEGER NOT NULL DEFAULT 3600
        );
        CREATE TABLE IF NOT EXISTS payments(
            charge_id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, plan TEXT NOT NULL,
            amount INTEGER NOT NULL, paid_at INTEGER NOT NULL, expires_at INTEGER NOT NULL
        );
        """)
        self.conn.commit()
        self._migrate()
        self.migrate_private_chats()
        self.migrate_permanent_mutes()
        self.migrate_business_reminders()
        self.migrate_watermark_scatter()
        self.migrate_management()
        self.migrate_admin()

    def upsert_user(self, user: Any) -> None:
        self.conn.execute(
            "INSERT INTO users(user_id,username,first_name,created_at,last_seen) VALUES(?,?,?,?,?) "
            "ON CONFLICT(user_id) DO UPDATE SET username=excluded.username,first_name=excluded.first_name,last_seen=excluded.created_at",
            (user.id, user.username or "", user.first_name or "", now_ts(), now_ts()),
        )
        self.conn.commit()

    def get_user(self, user_id: int):
        return self.conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()

    def is_premium(self, user_id: int) -> bool:
        row = self.get_user(user_id)
        return bool(row and int(row["premium_until"]) > now_ts())

    def premium_until(self, user_id: int) -> int:
        row = self.get_user(user_id)
        return int(row["premium_until"] or 0) if row else 0

    def set_timezone(self, user_id: int, tz: str) -> None:
        self.conn.execute("UPDATE users SET timezone=? WHERE user_id=?", (tz, user_id))
        self.conn.commit()

    def set_afk(self, user_id: int, reason: str | None) -> None:
        self.conn.execute(
            "UPDATE users SET afk_reason=?,afk_since=? WHERE user_id=?",
            (reason, now_ts() if reason else None, user_id),
        )
        self.conn.commit()

    def get_setting(self, chat_id: int, key: str, default: str = "0") -> str:
        row = self.conn.execute(
            "SELECT value FROM group_settings WHERE chat_id=? AND key=?", (chat_id, key)
        ).fetchone()
        return str(row["value"]) if row else default

    def set_setting(self, chat_id: int, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO group_settings(chat_id,key,value) VALUES(?,?,?) ON CONFLICT(chat_id,key) DO UPDATE SET value=excluded.value",
            (chat_id, key, value),
        )
        self.conn.commit()

    def add_warn(self, chat_id: int, user_id: int) -> int:
        self.conn.execute(
            "INSERT INTO warns(chat_id,user_id,count) VALUES(?,?,1) ON CONFLICT(chat_id,user_id) DO UPDATE SET count=count+1",
            (chat_id, user_id),
        )
        self.conn.commit()
        row = self.conn.execute(
            "SELECT count FROM warns WHERE chat_id=? AND user_id=?", (chat_id, user_id)
        ).fetchone()
        return int(row["count"])

    def save_connection(
        self,
        connection_id: str,
        owner_id: int,
        enabled: bool,
        can_reply: bool,
        *,
        can_delete_all_messages=False,
        can_delete_sent_messages=False,
        user_chat_id=0,
    ) -> None:
        self.conn.execute(
            "INSERT INTO business_connections(connection_id,owner_id,is_enabled,can_reply,can_delete_all_messages,can_delete_sent_messages,user_chat_id) "
            "VALUES(?,?,?,?,?,?,?) ON CONFLICT(connection_id) DO UPDATE SET owner_id=excluded.owner_id,is_enabled=excluded.is_enabled,"
            "can_reply=excluded.can_reply,can_delete_all_messages=excluded.can_delete_all_messages,"
            "can_delete_sent_messages=excluded.can_delete_sent_messages,user_chat_id=excluded.user_chat_id",
            (
                connection_id,
                owner_id,
                int(enabled),
                int(can_reply),
                int(can_delete_all_messages),
                int(can_delete_sent_messages),
                user_chat_id,
            ),
        )
        self.conn.execute(
            "UPDATE business_connections SET checked_at=? WHERE connection_id=?", (now_ts(), connection_id)
        )

    def get_connection(self, owner_id: int):
        return self.conn.execute(
            "SELECT * FROM business_connections WHERE owner_id=? ORDER BY is_enabled DESC,checked_at DESC,rowid DESC LIMIT 1",
            (owner_id,),
        ).fetchone()

    def connection_owner(self, connection_id: str):
        return self.conn.execute(
            "SELECT * FROM business_connections WHERE connection_id=?", (connection_id,)
        ).fetchone()

    def save_autoreply(
        self, owner_id: int, *, enabled: bool | None = None, reply_text: str | None = None
    ) -> None:
        self.conn.execute("INSERT OR IGNORE INTO autoreply(owner_id) VALUES(?)", (owner_id,))
        if enabled is not None:
            self.conn.execute("UPDATE autoreply SET enabled=? WHERE owner_id=?", (int(enabled), owner_id))
        if reply_text is not None:
            self.conn.execute("UPDATE autoreply SET reply_text=? WHERE owner_id=?", (reply_text, owner_id))
        self.conn.commit()

    def get_autoreply(self, owner_id: int):
        self.conn.execute("INSERT OR IGNORE INTO autoreply(owner_id) VALUES(?)", (owner_id,))
        self.conn.commit()
        return self.conn.execute("SELECT * FROM autoreply WHERE owner_id=?", (owner_id,)).fetchone()

    def close(self) -> None:
        self.conn.close()

    @contextmanager
    def atomic(self):
        nested = self.conn.in_transaction
        name = "sp_" + str(time.time_ns())
        self.conn.execute(f"SAVEPOINT {name}" if nested else "BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            if nested:
                self.conn.execute(f"ROLLBACK TO {name}")
                self.conn.execute(f"RELEASE {name}")
            else:
                self.conn.rollback()
            raise
        else:
            if nested:
                self.conn.execute(f"RELEASE {name}")
            else:
                self.conn.commit()

    def _migrate(self):
        if self.conn.execute("PRAGMA user_version").fetchone()[0] >= 2:
            return
        with self.atomic():

            def add(table, column, definition):
                if column not in {r["name"] for r in self.conn.execute(f"PRAGMA table_info({table})")}:
                    self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

            add("users", "legacy_until", "INTEGER NOT NULL DEFAULT 0")
            add("users", "created_at", "INTEGER NOT NULL DEFAULT 0")
            add("payments", "days", "INTEGER NOT NULL DEFAULT 0")
            add("payments", "order_id", "TEXT")
            add("payments", "status", "TEXT NOT NULL DEFAULT 'paid'")
            add("payments", "refunded_at", "INTEGER")
            self.conn.execute("UPDATE users SET created_at=? WHERE created_at=0", (now_ts(),))
            self.conn.execute(
                "UPDATE payments SET days=CASE plan WHEN 'month' THEN 30 WHEN 'quarter' THEN 90 WHEN 'year' THEN 365 ELSE 0 END WHERE days=0"
            )
            for user in self.conn.execute("SELECT * FROM users").fetchall():
                first = self.conn.execute(
                    "SELECT * FROM payments WHERE user_id=? ORDER BY paid_at,rowid LIMIT 1",
                    (user["user_id"],),
                ).fetchone()
                baseline = (
                    user["premium_until"]
                    if first is None
                    else max(0, first["expires_at"] - first["days"] * 86400)
                )
                self.conn.execute(
                    "UPDATE users SET legacy_until=? WHERE user_id=?", (baseline, user["user_id"])
                )
            statements = [
                """CREATE TABLE IF NOT EXISTS orders(
                    order_id TEXT PRIMARY KEY,user_id INTEGER NOT NULL,plan TEXT NOT NULL,
                    amount INTEGER NOT NULL CHECK(amount>0),days INTEGER NOT NULL CHECK(days>0),
                    created_at INTEGER NOT NULL,expires_at INTEGER NOT NULL,
                    checkout_id TEXT,status TEXT NOT NULL DEFAULT 'pending')""",
                "CREATE UNIQUE INDEX IF NOT EXISTS payments_order ON payments(order_id) WHERE order_id IS NOT NULL",
                "CREATE INDEX IF NOT EXISTS payments_user ON payments(user_id,paid_at)",
                """CREATE TABLE IF NOT EXISTS notes(id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,title TEXT NOT NULL,body TEXT NOT NULL,created_at INTEGER NOT NULL,
                    UNIQUE(user_id,title))""",
                """CREATE TABLE IF NOT EXISTS tasks(id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,text TEXT NOT NULL,done INTEGER NOT NULL DEFAULT 0,created_at INTEGER NOT NULL)""",
                """CREATE TABLE IF NOT EXISTS reminders(id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,chat_id INTEGER NOT NULL,thread_id INTEGER,
                    text TEXT NOT NULL,due_at INTEGER NOT NULL,interval_seconds INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'pending',lease_until INTEGER NOT NULL DEFAULT 0,
                    attempts INTEGER NOT NULL DEFAULT 0,last_error TEXT NOT NULL DEFAULT '')""",
                "CREATE INDEX IF NOT EXISTS reminders_due ON reminders(status,due_at)",
                "CREATE INDEX IF NOT EXISTS notes_owner ON notes(user_id,id)",
                "CREATE INDEX IF NOT EXISTS tasks_owner ON tasks(user_id,id)",
                """CREATE TABLE IF NOT EXISTS usage(user_id INTEGER NOT NULL,day TEXT NOT NULL,
                    kind TEXT NOT NULL,count INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(user_id,day,kind))""",
                """CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY AUTOINCREMENT,actor_id INTEGER NOT NULL,
                    action TEXT NOT NULL,detail TEXT NOT NULL,created_at INTEGER NOT NULL)""",
                """CREATE TABLE IF NOT EXISTS autoreply_delivery(connection_id TEXT NOT NULL,chat_id INTEGER NOT NULL,
                    sent_at INTEGER NOT NULL,PRIMARY KEY(connection_id,chat_id))""",
                """CREATE TABLE IF NOT EXISTS game_state(kind TEXT NOT NULL,chat_id INTEGER NOT NULL,user_id INTEGER NOT NULL,
                    data TEXT NOT NULL,updated_at INTEGER NOT NULL,PRIMARY KEY(kind,chat_id,user_id))""",
            ]
            for statement in statements:
                self.conn.execute(statement)
            self.conn.execute("PRAGMA user_version=2")

    def get_warns(self, chat_id: int, user_id: int) -> int:
        row = self.conn.execute(
            "SELECT count FROM warns WHERE chat_id=? AND user_id=?", (chat_id, user_id)
        ).fetchone()
        return row["count"] if row else 0

    def clear_warns(self, chat_id: int, user_id: int):
        self.conn.execute("DELETE FROM warns WHERE chat_id=? AND user_id=?", (chat_id, user_id))

    def audit(self, actor_id: int, action: str, detail: str):
        self.conn.execute(
            "INSERT INTO audit(actor_id,action,detail,created_at) VALUES(?,?,?,?)",
            (actor_id, action, detail[:1000], now_ts()),
        )

    def stats(self):
        return {
            "users": self.conn.execute("SELECT COUNT(*) FROM users").fetchone()[0],
            "premium": self.conn.execute(
                "SELECT COUNT(*) FROM users WHERE premium_until>?", (now_ts(),)
            ).fetchone()[0],
            "payments": self.conn.execute("SELECT COUNT(*) FROM payments WHERE status='paid'").fetchone()[0],
            "stars": self.conn.execute(
                "SELECT COALESCE(SUM(amount),0) FROM payments WHERE status='paid'"
            ).fetchone()[0],
            "refund_pending": self.conn.execute(
                "SELECT COUNT(*) FROM payments WHERE status='refund_pending'"
            ).fetchone()[0],
            "reminders": self.conn.execute(
                "SELECT COUNT(*) FROM reminders WHERE status IN ('pending','sending')"
            ).fetchone()[0],
        }

    def backup(self, destination: str):
        with closing(sqlite3.connect(destination)) as target:
            self.conn.backup(target)

    def take_quota(self, user_id: int, day: str, kind: str, limit: int) -> bool:
        with self.atomic():
            self.conn.execute(
                "INSERT OR IGNORE INTO usage(user_id,day,kind) VALUES(?,?,?)", (user_id, day, kind)
            )
            cursor = self.conn.execute(
                "UPDATE usage SET count=count+1 WHERE user_id=? AND day=? AND kind=? AND count<?",
                (user_id, day, kind, limit),
            )
            return bool(cursor.rowcount)

    def release_quota(self, user_id: int, day: str, kind: str):
        self.conn.execute(
            "UPDATE usage SET count=MAX(0,count-1) WHERE user_id=? AND day=? AND kind=?", (user_id, day, kind)
        )

    def set_autoreply_cooldown(self, owner_id: int, seconds: int):
        self.get_autoreply(owner_id)
        self.conn.execute("UPDATE autoreply SET cooldown=? WHERE owner_id=?", (seconds, owner_id))

    def last_reply(self, connection_id: str, chat_id: int) -> int:
        row = self.conn.execute(
            "SELECT sent_at FROM autoreply_delivery WHERE connection_id=? AND chat_id=?",
            (connection_id, chat_id),
        ).fetchone()
        return row["sent_at"] if row else 0

    def mark_reply(self, connection_id: str, chat_id: int, stamp: int):
        self.conn.execute(
            "INSERT INTO autoreply_delivery VALUES(?,?,?) ON CONFLICT(connection_id,chat_id) DO UPDATE SET sent_at=excluded.sent_at",
            (connection_id, chat_id, stamp),
        )

    def game(self, kind: str, chat_id: int, user_id: int):
        import json

        row = self.conn.execute(
            "SELECT data FROM game_state WHERE kind=? AND chat_id=? AND user_id=? AND updated_at>?",
            (kind, chat_id, user_id, now_ts() - 86400),
        ).fetchone()
        return json.loads(row["data"]) if row else None

    def save_game(self, kind: str, chat_id: int, user_id: int, data):
        import json

        self.conn.execute(
            "INSERT INTO game_state VALUES(?,?,?,?,?) ON CONFLICT(kind,chat_id,user_id) DO UPDATE SET data=excluded.data,updated_at=excluded.updated_at",
            (kind, chat_id, user_id, json.dumps(data), now_ts()),
        )

    def delete_game(self, kind: str, chat_id: int, user_id: int):
        self.conn.execute(
            "DELETE FROM game_state WHERE kind=? AND chat_id=? AND user_id=?", (kind, chat_id, user_id)
        )
