"""Load the user's existing settings without rewriting or replacing the file."""

from __future__ import annotations

import io
import os
from pathlib import Path

from dotenv import dotenv_values


def load_environment(base_dir: Path) -> Path:
    selected = os.getenv("AENIA_ENV_FILE", "").strip()
    path = Path(selected).expanduser() if selected else base_dir / ".env"
    if not path.is_absolute():
        path = base_dir / path
    if not selected and not path.is_file() and (base_dir / ".env.txt").is_file():
        path = base_dir / ".env.txt"
    if not path.is_file():
        return path
    try:
        raw = path.read_bytes()
        encoding = "utf-16" if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
        text = raw.decode(encoding)
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"Не удалось прочитать настройки: {path}. Сохраните файл в UTF-8.") from exc
    values = dotenv_values(stream=io.StringIO(text))
    for key, value in values.items():
        if value is None:
            continue
        # Blank hosting fields must not erase the working token or admin list.
        # Non-empty environment overrides keep their usual precedence.
        if key not in os.environ or key in {"BOT_TOKEN", "ADMIN_IDS"} and not os.environ[key].strip():
            os.environ[key] = value
    return path
