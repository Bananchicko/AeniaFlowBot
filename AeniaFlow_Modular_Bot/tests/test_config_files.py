"""Startup regressions for existing settings on Windows and empty host overrides."""

import os
from pathlib import Path
import subprocess
import sys

import pytest
from aeniaflow.core.config_files import load_environment

TOKEN = "123456:" + "A" * 35


@pytest.fixture(autouse=True)
def restore_loaded_environment(monkeypatch):
    for name in ("BOT_TOKEN", "ADMIN_IDS"):
        monkeypatch.setenv(name, os.environ.get(name, ""))


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig", "utf-16"])
@pytest.mark.parametrize("filename", [".env", ".env.txt"])
def test_loads_existing_token_without_rewriting_any_bytes(tmp_path, monkeypatch, encoding, filename):
    monkeypatch.delenv("AENIA_ENV_FILE", raising=False)
    monkeypatch.delenv("BOT_TOKEN", raising=False)
    monkeypatch.delenv("ADMIN_IDS", raising=False)
    path = tmp_path / filename
    path.write_text(f'BOT_TOKEN="{TOKEN}"\nADMIN_IDS=8285233133.,123456789\n', encoding=encoding)
    before = path.read_bytes()
    assert load_environment(tmp_path) == path
    assert os.environ["BOT_TOKEN"] == TOKEN
    assert os.environ["ADMIN_IDS"] == "8285233133.,123456789"
    assert path.read_bytes() == before


@pytest.mark.parametrize("host", ["", "   ", "987654:" + "B" * 35])
def test_empty_host_token_does_not_mask_file_but_real_override_wins(tmp_path, monkeypatch, host):
    monkeypatch.delenv("AENIA_ENV_FILE", raising=False)
    monkeypatch.setenv("BOT_TOKEN", host)
    (tmp_path / ".env").write_text("BOT_TOKEN=" + TOKEN)
    load_environment(tmp_path)
    assert os.environ["BOT_TOKEN"] == (host if host.strip() else TOKEN)


def test_explicit_config_path_and_canonical_env_take_precedence(tmp_path, monkeypatch):
    monkeypatch.delenv("BOT_TOKEN", raising=False)
    monkeypatch.delenv("AENIA_ENV_FILE", raising=False)
    (tmp_path / ".env").write_text("BOT_TOKEN=" + TOKEN)
    (tmp_path / ".env.txt").write_text("BOT_TOKEN=ignored")
    assert load_environment(tmp_path) == tmp_path / ".env"
    assert os.environ["BOT_TOKEN"] == TOKEN
    chosen = tmp_path / "custom.env"
    chosen.write_text("BOT_TOKEN=" + TOKEN)
    monkeypatch.setenv("AENIA_ENV_FILE", "custom.env")
    assert load_environment(tmp_path) == chosen


def test_missing_or_badly_encoded_settings_never_dump_the_file(tmp_path, monkeypatch):
    monkeypatch.delenv("AENIA_ENV_FILE", raising=False)
    assert load_environment(tmp_path) == tmp_path / ".env"
    (tmp_path / ".env").write_bytes(b"BOT_TOKEN=do-not-print-this\xff")
    with pytest.raises(ValueError) as result:
        load_environment(tmp_path)
    assert "do-not-print-this" not in str(result.value)
    assert "UTF-8" in str(result.value)


@pytest.mark.parametrize("filename,encoding", [(".env", "utf-8-sig"), (".env.txt", "utf-16")])
def test_real_config_import_uses_file_from_project_not_working_directory(tmp_path, filename, encoding):
    project = Path(__file__).resolve().parents[1]
    config = tmp_path / filename
    config.write_text(f"BOT_TOKEN={TOKEN}\nADMIN_IDS=8285233133.,123456789\n", encoding=encoding)
    env = {**os.environ, "AENIA_ENV_FILE": str(config), "BOT_TOKEN": "", "PYTHONPATH": str(project)}
    env.pop("ADMIN_IDS", None)
    run = subprocess.run(
        [
            sys.executable,
            "-c",
            "from config import settings; settings.validate(); assert len(settings.admin_ids)==2; print('OK')",
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert run.returncode == 0 and run.stdout.strip() == "OK"
    assert TOKEN not in run.stdout + run.stderr
