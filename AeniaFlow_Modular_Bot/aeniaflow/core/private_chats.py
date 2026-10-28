"""Persistent, owner-scoped state for managed private conversations."""

import time


class PrivateChatsRepository:
    def migrate_private_chats(self):
        if self.conn.execute("PRAGMA user_version").fetchone()[0] >= 3:
            return
        with self.atomic():
            columns = {r["name"] for r in self.conn.execute("PRAGMA table_info(business_connections)")}
            for name in ("can_delete_all_messages", "can_delete_sent_messages", "user_chat_id"):
                if name not in columns:
                    self.conn.execute(
                        f"ALTER TABLE business_connections ADD COLUMN {name} INTEGER NOT NULL DEFAULT 0"
                    )
            self.conn.execute("""CREATE TABLE IF NOT EXISTS private_dialogs(
                id INTEGER PRIMARY KEY AUTOINCREMENT, owner_id INTEGER NOT NULL,
                connection_id TEXT NOT NULL, chat_id INTEGER NOT NULL,
                peer_name TEXT NOT NULL, username TEXT NOT NULL DEFAULT '',
                last_seen INTEGER NOT NULL, muted_until INTEGER NOT NULL DEFAULT 0,
                mute_error TEXT NOT NULL DEFAULT '', error_notified INTEGER NOT NULL DEFAULT 0,
                UNIQUE(owner_id,connection_id,chat_id))""")
            self.conn.execute(
                "CREATE INDEX IF NOT EXISTS private_dialogs_owner ON private_dialogs(owner_id,last_seen)"
            )
            self.conn.execute("""CREATE TABLE IF NOT EXISTS private_messages(
                dialog_id INTEGER NOT NULL REFERENCES private_dialogs(id) ON DELETE CASCADE,
                message_id INTEGER NOT NULL, seen_at INTEGER NOT NULL,
                PRIMARY KEY(dialog_id,message_id))""")
            self.conn.execute("PRAGMA user_version=3")

    def migrate_permanent_mutes(self):
        if self.conn.execute("PRAGMA user_version").fetchone()[0] >= 4:
            return
        with self.atomic():
            self.conn.execute("ALTER TABLE private_dialogs ADD COLUMN muted INTEGER NOT NULL DEFAULT 0")
            self.conn.execute("ALTER TABLE private_dialogs ADD COLUMN mute_message_id INTEGER")
            self.conn.execute("ALTER TABLE private_dialogs ADD COLUMN owner_message_id INTEGER")
            self.conn.execute("UPDATE private_dialogs SET muted=1 WHERE muted_until>?", (int(time.time()),))
            self.conn.execute("UPDATE private_dialogs SET muted_until=0")
            self.conn.execute("ALTER TABLE users ADD COLUMN watermark_style TEXT NOT NULL DEFAULT 'auto'")
            self.conn.execute("ALTER TABLE users ADD COLUMN watermark_position TEXT NOT NULL DEFAULT 'br'")
            self.conn.execute("ALTER TABLE users ADD COLUMN watermark_opacity INTEGER NOT NULL DEFAULT 55")
            self.conn.execute("PRAGMA user_version=4")

    def migrate_watermark_scatter(self):
        if self.conn.execute("PRAGMA user_version").fetchone()[0] >= 6:
            return
        with self.atomic():
            columns = {r["name"] for r in self.conn.execute("PRAGMA table_info(users)")}
            if "watermark_count" not in columns:
                self.conn.execute("ALTER TABLE users ADD COLUMN watermark_count INTEGER NOT NULL DEFAULT 5")
            if "watermark_scatter" not in columns:
                self.conn.execute(
                    "ALTER TABLE users ADD COLUMN watermark_scatter TEXT NOT NULL DEFAULT 'center'"
                )
            self.conn.execute("PRAGMA user_version=6")

    def remember_dialog(self, owner, connection_id, chat, message_id=None):
        now = int(time.time())
        name = chat.full_name or chat.username or "Собеседник"
        self.conn.execute(
            "INSERT INTO private_dialogs(owner_id,connection_id,chat_id,peer_name,username,last_seen) VALUES(?,?,?,?,?,?) "
            "ON CONFLICT(owner_id,connection_id,chat_id) DO UPDATE SET peer_name=excluded.peer_name,username=excluded.username,last_seen=excluded.last_seen",
            (owner, connection_id, chat.id, name[:128], chat.username or "", now),
        )
        row = self.conn.execute(
            "SELECT * FROM private_dialogs WHERE owner_id=? AND connection_id=? AND chat_id=?",
            (owner, connection_id, chat.id),
        ).fetchone()
        if message_id is not None:
            self.conn.execute(
                "INSERT OR IGNORE INTO private_messages VALUES(?,?,?)", (row["id"], message_id, now)
            )
            self.conn.execute(
                "DELETE FROM private_messages WHERE dialog_id=? AND (seen_at<? OR message_id NOT IN "
                "(SELECT message_id FROM private_messages WHERE dialog_id=? ORDER BY message_id DESC LIMIT 100))",
                (row["id"], now - 86400, row["id"]),
            )
        self.conn.execute(
            "DELETE FROM private_dialogs WHERE owner_id=? AND muted=0 AND id NOT IN "
            "(SELECT id FROM private_dialogs WHERE owner_id=? ORDER BY last_seen DESC,id DESC LIMIT 200)",
            (owner, owner),
        )
        return row

    def dialog(self, owner, identifier):
        return self.conn.execute(
            "SELECT * FROM private_dialogs WHERE owner_id=? AND id=?", (owner, identifier)
        ).fetchone()

    def dialogs(self, owner, offset=0, muted_only=False):
        return self.conn.execute(
            "SELECT * FROM private_dialogs WHERE owner_id=? AND (?=0 OR muted=1) ORDER BY last_seen DESC,id DESC LIMIT 8 OFFSET ?",
            (owner, int(muted_only), offset),
        ).fetchall()

    def dialog_counts(self, owner):
        return self.conn.execute(
            "SELECT COUNT(*) AS total,COALESCE(SUM(muted),0) AS muted "
            "FROM private_dialogs WHERE owner_id=?",
            (owner,),
        ).fetchone()

    def set_private_mute(self, owner, identifier, enabled):
        return bool(
            self.conn.execute(
                "UPDATE private_dialogs SET muted=?,mute_error='',error_notified=0 WHERE owner_id=? AND id=?",
                (int(bool(enabled)), owner, identifier),
            ).rowcount
        )

    def save_mute_notice(self, owner, identifier, message_id, *, personal=False):
        column = "owner_message_id" if personal else "mute_message_id"
        self.conn.execute(
            f"UPDATE private_dialogs SET {column}=? WHERE owner_id=? AND id=?",
            (message_id, owner, identifier),
        )

    def private_mute_error(self, owner, identifier, error):
        self.conn.execute(
            "UPDATE private_dialogs SET mute_error=?,error_notified=1 WHERE owner_id=? AND id=?",
            (error, owner, identifier),
        )

    def recent_private_messages(self, owner, identifier, limit):
        return [
            r[0]
            for r in self.conn.execute(
                "SELECT m.message_id FROM private_messages m JOIN private_dialogs d ON d.id=m.dialog_id "
                "WHERE d.owner_id=? AND d.id=? AND m.seen_at>? ORDER BY m.message_id DESC LIMIT ?",
                (owner, identifier, int(time.time()) - 86400, limit),
            )
        ]

    def set_watermark(self, owner, option, value):
        allowed = {
            "style": {"auto", "glass", "signature"},
            "position": {"tl", "tr", "bl", "br", "center"},
            "opacity": {25, 40, 55, 70},
            "count": set(range(1, 13)),
            "scatter": {"center", "spread"},
        }
        if option not in allowed or value not in allowed[option]:
            raise ValueError("Недоступная настройка водяного знака.")
        self.conn.execute(f"UPDATE users SET watermark_{option}=? WHERE user_id=?", (value, owner))
