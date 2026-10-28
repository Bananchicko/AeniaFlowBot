from __future__ import annotations
from collections import OrderedDict
from config import BASE_DIR, settings
from aeniaflow.core.database import Database

LEGAL = BASE_DIR / "legal"


class LazyDatabase:
    """Avoid opening/migrating a database just to import modules or run setup checks."""

    instance: Database | None = None

    def __getattr__(self, name):
        if self.instance is None:
            self.instance = Database(settings.database_path)
        return getattr(self.instance, name)

    def close(self):
        if self.instance is not None:
            self.instance.close()
            self.instance = None


class BoundedCache(OrderedDict):
    def __init__(self, limit=10000):
        super().__init__()
        self.limit = limit

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        self.move_to_end(key)
        while len(self) > self.limit:
            self.popitem(last=False)


db = LazyDatabase()
command_seen = BoundedCache()
processed_messages = BoundedCache()
business_notices = BoundedCache(limit=2048)
# Compatibility while games migrate to durable state.
tictactoe_games = BoundedCache()
wordle_games = BoundedCache()
last_autoreply = BoundedCache()
