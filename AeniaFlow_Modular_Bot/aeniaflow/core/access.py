"""Administrator privileges and purchased access are separate from billing records."""

from config import settings
from aeniaflow.core.runtime import db


def is_owner(user_id: int) -> bool:
    if user_id in settings.owner_ids:
        return True
    override = db.admin_override(user_id)
    return override if override is not None else user_id in settings.admin_ids | settings.initial_admin_ids


def admin_ids():
    candidates = set(settings.admin_ids | settings.initial_admin_ids | settings.owner_ids)
    candidates.update(row[0] for row in db.conn.execute("SELECT user_id FROM bot_admins"))
    return sorted(user_id for user_id in candidates if is_owner(user_id))


def has_plus(user_id: int) -> bool:
    return is_owner(user_id) or db.is_premium(user_id)


def rank(user_id):
    return 2 if user_id in settings.owner_ids else 1 if is_owner(user_id) else 0


def protected_from_mute(actor, target):
    level = rank(target)
    return ("Владелец" if level == 2 else "Администратор") if level > rank(actor) else None
