"""Configuration only: importing this module never contacts Telegram."""

from __future__ import annotations

import os
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse
from aeniaflow.core.config_files import load_environment

BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = load_environment(BASE_DIR)


def deployment_ids(key):
    path = BASE_DIR / "owner_config.json"
    if not path.exists():
        return frozenset()
    values = json.loads(path.read_text(encoding="utf-8")).get(key, [])
    if not isinstance(values, list) or any(
        type(value) is not int or not 0 < value < 2**63 for value in values
    ):
        raise ValueError("owner_config.json: требуются положительные числовые ID.")
    return frozenset(values)


def env_int(name: str, default: int, low: int, high: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise ValueError(f"{name}: требуется целое число.") from exc
    if not low <= value <= high:
        raise ValueError(f"{name}: допустимый диапазон {low}–{high}.")
    return value


def normalize_channel(value: str) -> str | int:
    value = value.strip()
    if not value:
        return ""
    if re.fullmatch(r"-100\d+", value):
        return int(value)
    if value.startswith(("https://t.me/", "http://t.me/", "t.me/")):
        value = urlparse(value if "://" in value else "https://" + value).path.strip("/")
    value = value.lstrip("@")
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{3,31}", value):
        raise ValueError("NEWS_CHANNEL: укажите @username, публичную ссылку или ID -100…")
    return "@" + value


def database_path() -> str:
    value = Path(os.getenv("DATABASE_PATH", "data/aeniaflow.sqlite3")).expanduser()
    return str(value if value.is_absolute() else BASE_DIR / value)


def parse_admin_ids(value: str) -> frozenset[int]:
    """Accept pasted ID lists without guessing digits from usernames or malformed IDs."""
    result = set()
    tokens = [token for token in re.split(r"[,;\s]+", value.strip()) if token]
    for position, token in enumerate(tokens, start=1):
        # A sentence-ending dot is harmless; an internal dot is not a separator.
        match = re.fullmatch(r"([0-9]{1,19})\.?", token)
        if not match or not 0 < int(match.group(1)) <= 2**63 - 1:
            raise ValueError(
                f"ADMIN_IDS: неверный ID №{position}. Укажите положительные числовые "
                "Telegram ID через запятую, например 111111111,222222222. "
                "Username и текст вместо ID не подходят."
            )
        result.add(int(match.group(1)))
    return frozenset(result)


@dataclass(frozen=True)
class Settings:
    bot_token: str = field(default_factory=lambda: os.getenv("BOT_TOKEN", "").strip(), repr=False)
    news_channel: str | int = field(default_factory=lambda: normalize_channel(os.getenv("NEWS_CHANNEL", "")))
    news_channel_url: str = field(
        default_factory=lambda: os.getenv("NEWS_CHANNEL_URL", "https://t.me/AeniaFlow").strip()
    )
    support_username: str = field(
        default_factory=lambda: (os.getenv("SUPPORT_USERNAME", "").strip().lstrip("@") or "alcLua")
    )
    admin_ids: frozenset[int] = field(default_factory=lambda: parse_admin_ids(os.getenv("ADMIN_IDS", "")))
    owner_ids: frozenset[int] = field(default_factory=lambda: deployment_ids("owner_ids"))
    initial_admin_ids: frozenset[int] = field(default_factory=lambda: deployment_ids("admin_ids"))
    openai_api_key: str = field(default_factory=lambda: os.getenv("OPENAI_API_KEY", "").strip(), repr=False)
    openai_model: str = field(default_factory=lambda: os.getenv("OPENAI_MODEL", "gpt-4.1-mini").strip())
    database_path: str = field(default_factory=database_path)
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO").upper())
    day_stars: int = field(default_factory=lambda: env_int("STARS_DAY", 5, 1, 10000))
    three_days_stars: int = field(default_factory=lambda: env_int("STARS_THREE_DAYS", 10, 1, 10000))
    week_stars: int = field(default_factory=lambda: env_int("STARS_WEEK", 20, 1, 10000))
    fortnight_stars: int = field(default_factory=lambda: env_int("STARS_FORTNIGHT", 30, 1, 10000))
    halfyear_stars: int = field(default_factory=lambda: env_int("STARS_HALFYEAR", 200, 1, 10000))
    month_stars: int = field(default_factory=lambda: env_int("STARS_MONTH", 50, 1, 10000))
    quarter_stars: int = field(default_factory=lambda: env_int("STARS_QUARTER", 100, 1, 10000))
    year_stars: int = field(default_factory=lambda: env_int("STARS_YEAR", 400, 1, 10000))
    ai_daily_limit: int = field(default_factory=lambda: env_int("AI_DAILY_LIMIT", 40, 1, 10000))
    max_download_mb: int = field(default_factory=lambda: env_int("MAX_DOWNLOAD_MB", 20, 1, 20))
    command_cooldown: int = field(default_factory=lambda: env_int("COMMAND_COOLDOWN", 0, 0, 60))

    def validate(self) -> None:
        if not re.fullmatch(r"\d+:[A-Za-z0-9_-]{30,}", self.bot_token):
            reason = "не задан" if not self.bot_token else "записан в неверном формате"
            raise ValueError(
                f"BOT_TOKEN {reason}. Файл настроек: {ENV_FILE}. "
                "Восстановите свою .env из прежней папки бота. "
                "Непустая переменная окружения BOT_TOKEN имеет приоритет над файлом. "
                "Действующий токен менять не требуется."
            )
        if self.support_username and not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{3,31}", self.support_username):
            raise ValueError("SUPPORT_USERNAME: укажите username поддержки без ссылки.")
        if any(x <= 0 for x in self.admin_ids):
            raise ValueError("ADMIN_IDS: требуются положительные числовые Telegram ID.")
        if self.news_channel_url and not self.news_channel_url.startswith("https://t.me/"):
            raise ValueError("NEWS_CHANNEL_URL должен начинаться с https://t.me/.")


settings = Settings()
