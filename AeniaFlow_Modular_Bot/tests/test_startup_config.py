"""Regression for ADMIN_IDS copied with punctuation and direct `python main.py`."""

import os
from pathlib import Path
import subprocess
import sys

import pytest

from config import Settings, parse_admin_ids


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("", set()),
        ("8285233133.", {8285233133}),
        (" 8285233133., 123456789. ", {8285233133, 123456789}),
        ("8285233133; 123456789", {8285233133, 123456789}),
        ("8285233133\n123456789", {8285233133, 123456789}),
        ("8285233133, 8285233133,", {8285233133}),
    ],
)
def test_admin_ids_support_copy_paste_and_two_admins(monkeypatch, raw, expected):
    monkeypatch.setenv("ADMIN_IDS", raw)
    assert Settings().admin_ids == frozenset(expected)


@pytest.mark.parametrize("raw", ["@username", "8285233133.123", "8285233133oops", "0", "-100123", str(2**63)])
def test_invalid_admin_ids_are_not_silently_turned_into_other_users(raw):
    with pytest.raises(ValueError, match="ADMIN_IDS: неверный ID"):
        parse_admin_ids(raw)


@pytest.mark.parametrize(
    "script,admin_ids,expected",
    [
        ("main.py", "8285233133.", "BOT_TOKEN"),
        ("main.py", "8285233133.,123456789", "BOT_TOKEN"),
        ("main.py", "@wrong", "ADMIN_IDS: неверный ID"),
        ("check_setup.py", "@wrong", "ADMIN_IDS: неверный ID"),
    ],
)
def test_direct_start_reports_config_errors_without_traceback(script, admin_ids, expected):
    # An empty token stops startup before any Telegram call or database opening.
    env = {**os.environ, "ADMIN_IDS": admin_ids, "BOT_TOKEN": "", "PYTHONIOENCODING": "utf-8"}
    result = subprocess.run(
        [sys.executable, script],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=20,
    )
    output = result.stdout + result.stderr
    assert result.returncode == 1
    assert expected in output
    assert "Traceback" not in output
    assert "invalid literal for int()" not in output
