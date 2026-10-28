#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -f .env ] && [ ! -f .env.txt ] && [ -z "${BOT_TOKEN:-}" ]; then
  echo 'Не найден файл настроек. Распакуйте архив целиком или перенесите свою .env из прежней папки бота.'
  exit 1
fi
if [ ! -d .venv ]; then python3 -m venv .venv; fi
source .venv/bin/activate
python -m pip install --disable-pip-version-check -r requirements.txt
python check_setup.py
exec python main.py
