"""Durable administration, control cards and private-chat tools."""

import json
import time


class ManagementRepository:
    def migrate_management(self):
        if self.conn.execute("PRAGMA user_version").fetchone()[0] >= 7:
            return
        with self.atomic():
            self.conn.execute(
                "CREATE TABLE IF NOT EXISTS bot_admins(user_id INTEGER PRIMARY KEY, enabled INTEGER NOT NULL, actor_id INTEGER NOT NULL, changed_at INTEGER NOT NULL)"
            )
            self.conn.execute(
                "CREATE TABLE IF NOT EXISTS runtime_options(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            self.conn.execute(
                "CREATE TABLE IF NOT EXISTS ui_panels(bot_id INTEGER NOT NULL, connection_id TEXT NOT NULL, chat_id INTEGER NOT NULL, message TEXT NOT NULL, pages TEXT NOT NULL DEFAULT '{}', PRIMARY KEY(bot_id,connection_id,chat_id))"
            )
            self.conn.execute(
                "CREATE TABLE IF NOT EXISTS peer_types(peer_id INTEGER PRIMARY KEY, is_bot INTEGER NOT NULL)"
            )
            self.conn.execute(
                "CREATE TABLE IF NOT EXISTS saved_replies(owner_id INTEGER NOT NULL, name TEXT NOT NULL, text TEXT NOT NULL, PRIMARY KEY(owner_id,name))"
            )
            columns = {r["name"] for r in self.conn.execute("PRAGMA table_info(private_dialogs)")}
            for name, definition in {
                "note": "TEXT NOT NULL DEFAULT ''",
                "reply_text": "TEXT NOT NULL DEFAULT ''",
                "paused": "INTEGER NOT NULL DEFAULT 0",
                "last_incoming_id": "INTEGER NOT NULL DEFAULT 0",
            }.items():
                if name not in columns:
                    self.conn.execute(f"ALTER TABLE private_dialogs ADD COLUMN {name} {definition}")
            if "checked_at" not in {
                r["name"] for r in self.conn.execute("PRAGMA table_info(business_connections)")
            }:
                self.conn.execute(
                    "ALTER TABLE business_connections ADD COLUMN checked_at INTEGER NOT NULL DEFAULT 0"
                )
            self.conn.execute("PRAGMA user_version=7")

    def admin_override(self, user_id):
        row = self.conn.execute("SELECT enabled FROM bot_admins WHERE user_id=?", (user_id,)).fetchone()
        return None if row is None else bool(row[0])

    def change_admin(self, actor, user_id, enabled):
        with self.atomic():
            self.conn.execute(
                "INSERT INTO bot_admins VALUES(?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET enabled=excluded.enabled,actor_id=excluded.actor_id,changed_at=excluded.changed_at",
                (user_id, int(enabled), actor, int(time.time())),
            )
            self.audit(actor, "admin_add" if enabled else "admin_remove", str(user_id))

    def runtime_option(self, key, default=""):
        row = self.conn.execute("SELECT value FROM runtime_options WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    def set_runtime_option(self, key, value):
        self.conn.execute(
            "INSERT INTO runtime_options VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value)),
        )

    def save_panel(self, bot_id, connection_id, chat_id, message, pages=None):
        self.conn.execute(
            "INSERT INTO ui_panels VALUES(?,?,?,?,?) ON CONFLICT(bot_id,connection_id,chat_id) DO UPDATE SET message=excluded.message,pages=excluded.pages",
            (bot_id, connection_id or "", chat_id, message, json.dumps(pages or {}, ensure_ascii=False)),
        )

    def load_panel(self, bot_id, connection_id, chat_id):
        return self.conn.execute(
            "SELECT * FROM ui_panels WHERE bot_id=? AND connection_id=? AND chat_id=?",
            (bot_id, connection_id or "", chat_id),
        ).fetchone()

    def remember_peer(self, user):
        self.conn.execute(
            "INSERT INTO peer_types VALUES(?,?) ON CONFLICT(peer_id) DO UPDATE SET is_bot=excluded.is_bot",
            (user.id, int(user.is_bot)),
        )

    def peer_type(self, peer_id):
        row = self.conn.execute("SELECT is_bot FROM peer_types WHERE peer_id=?", (peer_id,)).fetchone()
        return None if row is None else bool(row[0])

    def update_dialog(self, owner, identifier, key, value):
        if key not in {"note", "reply_text", "paused", "last_incoming_id", "tag", "autoread"}:
            raise ValueError("Неизвестная настройка диалога.")
        self.conn.execute(
            f"UPDATE private_dialogs SET {key}=? WHERE owner_id=? AND id=?", (value, owner, identifier)
        )

    def save_reply(self, owner, name, text):
        if not self.saved_reply(owner, name) and len(self.saved_replies(owner)) >= 50:
            raise ValueError("Можно сохранить до 50 быстрых ответов.")
        self.conn.execute(
            "INSERT INTO saved_replies VALUES(?,?,?) ON CONFLICT(owner_id,name) DO UPDATE SET text=excluded.text",
            (owner, name, text),
        )

    def saved_reply(self, owner, name):
        return self.conn.execute(
            "SELECT * FROM saved_replies WHERE owner_id=? AND name=?", (owner, name)
        ).fetchone()

    def saved_replies(self, owner):
        return self.conn.execute(
            "SELECT * FROM saved_replies WHERE owner_id=? ORDER BY name", (owner,)
        ).fetchall()

    def delete_reply(self, owner, name):
        return self.conn.execute(
            "DELETE FROM saved_replies WHERE owner_id=? AND name=?", (owner, name)
        ).rowcount
