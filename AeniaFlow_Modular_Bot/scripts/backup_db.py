"""Create a consistent SQLite backup without copying live WAL files by hand."""

from __future__ import annotations
import argparse
from contextlib import closing
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import settings


def backup(source: Path, destination: Path):
    source, destination = source.resolve(), destination.resolve()
    if not source.is_file():
        raise ValueError("Исходная база не найдена.")
    if source == destination or destination.exists():
        raise ValueError("Выберите новый путь для резервной копии; существующие файлы не перезаписываются.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(dir=destination.parent, suffix=".sqlite3.tmp")
    os.close(descriptor)
    try:
        with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as origin:
            with closing(sqlite3.connect(name)) as target:
                origin.backup(target)
                if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise RuntimeError("Проверка целостности копии не пройдена.")
        os.replace(name, destination)
    finally:
        Path(name).unlink(missing_ok=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    arguments = parser.parse_args()
    try:
        backup(Path(settings.database_path), arguments.destination)
    except (ValueError, sqlite3.Error) as exc:
        raise SystemExit(str(exc)) from None
    print(f"Резервная копия готова: {arguments.destination}")
