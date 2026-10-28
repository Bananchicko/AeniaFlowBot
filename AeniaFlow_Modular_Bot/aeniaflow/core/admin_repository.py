"""Schema 8: user controls, auditable grants and durable delivery queues."""

import json
import secrets
import time

LIFETIME = 253402300799


class AdminRepository:
    def migrate_admin(self):
        if self.conn.execute("PRAGMA user_version").fetchone()[0] >= 8:
            return
        with self.atomic():
            user_columns = {r["name"] for r in self.conn.execute("PRAGMA table_info(users)")}
            for name, definition in {
                "banned": "INTEGER NOT NULL DEFAULT 0",
                "referral_locked": "INTEGER NOT NULL DEFAULT 0",
                "ban_reason": "TEXT NOT NULL DEFAULT ''",
                "last_seen": "INTEGER NOT NULL DEFAULT 0",
                "dm_started": "INTEGER NOT NULL DEFAULT 0",
                "mail_enabled": "INTEGER NOT NULL DEFAULT 1",
            }.items():
                if name not in user_columns:
                    self.conn.execute(f"ALTER TABLE users ADD COLUMN {name} {definition}")
            payment_columns = {r["name"] for r in self.conn.execute("PRAGMA table_info(payments)")}
            if "access_revoked" not in payment_columns:
                self.conn.execute("ALTER TABLE payments ADD COLUMN access_revoked INTEGER NOT NULL DEFAULT 0")
            dialog_columns = {r["name"] for r in self.conn.execute("PRAGMA table_info(private_dialogs)")}
            for name, definition in {
                "tag": "TEXT NOT NULL DEFAULT ''",
                "autoread": "INTEGER NOT NULL DEFAULT 0",
                "incoming_count": "INTEGER NOT NULL DEFAULT 0",
                "outgoing_count": "INTEGER NOT NULL DEFAULT 0",
            }.items():
                if name not in dialog_columns:
                    self.conn.execute(f"ALTER TABLE private_dialogs ADD COLUMN {name} {definition}")
            for statement in (
                "CREATE TABLE referrals(user_id INTEGER PRIMARY KEY, inviter_id INTEGER NOT NULL, created_at INTEGER NOT NULL)",
                "CREATE TABLE referral_rewards(charge_id TEXT PRIMARY KEY,inviter_id INTEGER NOT NULL,buyer_id INTEGER NOT NULL,stars_milli INTEGER NOT NULL,days INTEGER NOT NULL,revoked INTEGER NOT NULL DEFAULT 0)",
                "CREATE TABLE referral_payouts(id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL,stars INTEGER NOT NULL,state TEXT NOT NULL DEFAULT 'pending',created_at INTEGER NOT NULL,resolved_at INTEGER,actor INTEGER)",
                "CREATE TABLE plus_grants(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, days INTEGER NOT NULL, created_at INTEGER NOT NULL, revoked INTEGER NOT NULL DEFAULT 0, reward_charge TEXT UNIQUE)",
                "CREATE TABLE admin_actions(token TEXT PRIMARY KEY, actor INTEGER NOT NULL, action TEXT NOT NULL, payload TEXT NOT NULL, created_at INTEGER NOT NULL, used INTEGER NOT NULL DEFAULT 0)",
                "CREATE TABLE broadcasts(id INTEGER PRIMARY KEY, actor INTEGER NOT NULL, audience TEXT NOT NULL, body TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'draft', created_at INTEGER NOT NULL, next_at INTEGER NOT NULL DEFAULT 0)",
                "CREATE TABLE broadcast_recipients(job_id INTEGER NOT NULL REFERENCES broadcasts(id) ON DELETE CASCADE, user_id INTEGER NOT NULL, state TEXT NOT NULL DEFAULT 'pending', error TEXT NOT NULL DEFAULT '', PRIMARY KEY(job_id,user_id))",
                "CREATE TABLE scheduled_messages(id INTEGER PRIMARY KEY, owner_id INTEGER NOT NULL, dialog_id INTEGER NOT NULL REFERENCES private_dialogs(id) ON DELETE CASCADE, body TEXT NOT NULL, due_at INTEGER NOT NULL, state TEXT NOT NULL DEFAULT 'pending', error TEXT NOT NULL DEFAULT '')",
                "CREATE INDEX scheduled_due ON scheduled_messages(state,due_at)",
                "CREATE TABLE reply_rules(id INTEGER PRIMARY KEY, owner_id INTEGER NOT NULL, dialog_id INTEGER NOT NULL REFERENCES private_dialogs(id) ON DELETE CASCADE, keyword TEXT NOT NULL, reply TEXT NOT NULL, UNIQUE(dialog_id,keyword))",
            ):
                self.conn.execute(
                    statement.replace("CREATE TABLE ", "CREATE TABLE IF NOT EXISTS ").replace(
                        "CREATE INDEX ", "CREATE INDEX IF NOT EXISTS "
                    )
                )
            self.conn.execute(
                "UPDATE users SET dm_started=1 WHERE user_id IN (SELECT chat_id FROM ui_panels WHERE connection_id='')"
            )
            if "referral_locked" not in user_columns:
                self.conn.execute("UPDATE users SET referral_locked=1")
            self.conn.execute("PRAGMA user_version=8")

    def mark_bot_dm(self, user_id):
        self.conn.execute("UPDATE users SET dm_started=1 WHERE user_id=?", (user_id,))

    def ban_user(self, actor, target, enabled, reason=""):
        with self.atomic():
            if not self.get_user(target):
                raise ValueError("Пользователь ещё не зарегистрирован в боте.")
            self.conn.execute(
                "UPDATE users SET banned=?,ban_reason=? WHERE user_id=?",
                (int(enabled), reason[:200] if enabled else "", target),
            )
            if enabled:
                self.conn.execute(
                    "UPDATE scheduled_messages SET state='cancelled' WHERE owner_id=? AND state='pending'",
                    (target,),
                )
            self.audit(actor, "user_ban" if enabled else "user_unban", str(target))

    def grant_plus(self, actor, target, days):
        if days not in {7, 30, 90, 365, 0}:
            raise ValueError("Выберите 7, 30, 90, 365 дней или бессрочный доступ.")
        with self.atomic():
            if not self.get_user(target):
                raise ValueError("Пользователь не найден.")
            self.conn.execute(
                "INSERT INTO plus_grants(user_id,days,created_at) VALUES(?,?,?)",
                (target, days, int(time.time())),
            )
            self._recalculate(target)
            self.audit(actor, "plus_grant", f'{target}: {days or "forever"}')

    def revoke_plus(self, actor, target):
        with self.atomic():
            self.conn.execute("UPDATE plus_grants SET revoked=1 WHERE user_id=?", (target,))
            self.conn.execute("UPDATE payments SET access_revoked=1 WHERE user_id=?", (target,))
            self.conn.execute("UPDATE users SET premium_until=0,legacy_until=0 WHERE user_id=?", (target,))
            self.conn.execute(
                "UPDATE scheduled_messages SET state='cancelled' WHERE owner_id=? AND state='pending'",
                (target,),
            )
            self.audit(actor, "plus_revoke", str(target))

    def prepare_admin_action(self, actor, action, payload):
        token = secrets.token_hex(8)
        self.conn.execute(
            "INSERT INTO admin_actions(token,actor,action,payload,created_at) VALUES(?,?,?,?,?)",
            (token, actor, action, json.dumps(payload), int(time.time())),
        )
        self.conn.execute("DELETE FROM admin_actions WHERE created_at<?", (int(time.time()) - 86400,))
        return token

    def admin_action(self, actor, token):
        return self.conn.execute(
            "SELECT * FROM admin_actions WHERE token=? AND actor=? AND used=0 AND created_at>?",
            (token, actor, int(time.time()) - 600),
        ).fetchone()

    def new_broadcast(self, actor, audience, body):
        if audience not in {"all", "free", "plus"} or not body.strip() or len(body) > 3000:
            raise ValueError("Аудитория: all, free или plus. Текст: 1–3000 символов.")
        return self.conn.execute(
            "INSERT INTO broadcasts(actor,audience,body,created_at) VALUES(?,?,?,?)",
            (actor, audience, body, int(time.time())),
        ).lastrowid

    def broadcast(self, identifier):
        return self.conn.execute("SELECT * FROM broadcasts WHERE id=?", (identifier,)).fetchone()

    def broadcast_counts(self, identifier):
        return {
            r["state"]: r["n"]
            for r in self.conn.execute(
                "SELECT state,COUNT(*) n FROM broadcast_recipients WHERE job_id=? GROUP BY state",
                (identifier,),
            )
        }

    def queue_broadcast(self, actor, identifier, recipients):
        with self.atomic():
            changed = self.conn.execute(
                "UPDATE broadcasts SET state='queued' WHERE id=? AND actor=? AND state='draft'",
                (identifier, actor),
            ).rowcount
            if not changed:
                return False
            self.conn.executemany(
                "INSERT OR IGNORE INTO broadcast_recipients(job_id,user_id) VALUES(?,?)",
                ((identifier, uid) for uid in recipients),
            )
            self.audit(actor, "broadcast_queued", str(identifier))
            return True

    def queue_message(self, owner, dialog, body, due):
        if not body.strip() or len(body) > 3000:
            raise ValueError("Текст сообщения: 1–3000 символов.")
        if (
            self.conn.execute(
                "SELECT COUNT(*) FROM scheduled_messages WHERE owner_id=? AND state='pending'", (owner,)
            ).fetchone()[0]
            >= 50
        ):
            raise ValueError("В очереди может быть до 50 сообщений.")
        row = self.dialog(owner, dialog)
        if not row:
            raise ValueError("Диалог недоступен.")
        return self.conn.execute(
            "INSERT INTO scheduled_messages(owner_id,dialog_id,body,due_at) VALUES(?,?,?,?)",
            (owner, dialog, body, due),
        ).lastrowid

    def add_rule(self, owner, dialog, keyword, reply):
        if not self.dialog(owner, dialog):
            raise ValueError("Диалог недоступен.")
        keyword = keyword.strip().casefold()
        if not 1 <= len(keyword) <= 80 or not 1 <= len(reply) <= 1000:
            raise ValueError("Ключ: 1–80 символов; ответ: 1–1000.")
        existing = self.conn.execute(
            "SELECT id FROM reply_rules WHERE dialog_id=? AND keyword=?", (dialog, keyword)
        ).fetchone()
        if (
            not existing
            and self.conn.execute("SELECT COUNT(*) FROM reply_rules WHERE dialog_id=?", (dialog,)).fetchone()[
                0
            ]
            >= 20
        ):
            raise ValueError("До 20 правил на диалог.")
        self.conn.execute(
            "INSERT INTO reply_rules(owner_id,dialog_id,keyword,reply) VALUES(?,?,?,?) ON CONFLICT(dialog_id,keyword) DO UPDATE SET reply=excluded.reply",
            (owner, dialog, keyword, reply),
        )
