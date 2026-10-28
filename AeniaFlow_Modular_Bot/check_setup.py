"""Offline check: does not contact Telegram, spend Stars or start the bot."""

from __future__ import annotations
import importlib.util
import shutil
import sys
from pathlib import Path
from aeniaflow import __version__


def main():
    print(f"AeniaFlow {__version__} · проверка установки")
    ffmpeg = shutil.which("ffmpeg")
    errors = []
    if sys.version_info < (3, 11):
        errors.append("Нужен Python 3.11 или новее.")
    for package in ("aiogram", "dotenv", "PIL", "openai", "gtts", "tzdata", "imageio_ffmpeg"):
        installed = importlib.util.find_spec(package) is not None
        print(f'{"OK" if installed else "НЕТ"} · {package}')
        if not installed:
            errors.append(f"Не установлен пакет {package}.")
    if importlib.util.find_spec("dotenv"):
        try:
            from config import settings, ENV_FILE
            from aeniaflow.core.ffmpeg import ffmpeg_binary, probe_ffmpeg

            ffmpeg = ffmpeg_binary()
            probe = probe_ffmpeg(ffmpeg)
            print("FFmpeg: " + probe["detail"])
            if not probe["ready"]:
                errors.append(
                    "Не готовы кодеки FFmpeg. Повторите pip install -r requirements.txt или задайте FFMPEG_PATH."
                )

            print(f"Настройки: {ENV_FILE}")
            settings.validate()
            print("OK · формат BOT_TOKEN (сетевой запрос не выполнялся)")
            print(
                "OK · продажи Stars"
                if settings.support_username
                else "НАСТРОИТЬ · SUPPORT_USERNAME: продажи пока закрыты"
            )
            print(
                f"OK · администраторов: {len(settings.admin_ids | settings.initial_admin_ids | settings.owner_ids)}; у каждого Plus без оплаты"
                if settings.admin_ids | settings.initial_admin_ids | settings.owner_ids
                else "НАСТРОИТЬ · ADMIN_IDS пуст: права администратора и бесплатный Plus пока никому не выданы"
            )
            if len(settings.admin_ids | settings.initial_admin_ids | settings.owner_ids) == 1:
                print(
                    "НАСТРОИТЬ · указан один администратор. Добавить администратора можно через .AdminMenu."
                )
            print(
                f"ПРОВЕРИТЬ В TELEGRAM · канал {settings.news_channel or '@AeniaFlow'}: бот должен быть его администратором. "
                "Канал можно изменить через .AdminMenu. Бесплатным пользователям нужна подписка; Plus и администраторы освобождены."
            )
            print(
                "OK · ИИ"
                if settings.openai_api_key and settings.openai_api_key.lower() != "none"
                else "ОПЦИЯ · ИИ не подключён"
            )
        except ValueError as exc:
            errors.append(str(exc))
    print(
        f"OK · FFmpeg: {ffmpeg}"
        if ffmpeg
        else "ОПЦИЯ · FFmpeg не установлен; укажите FFMPEG_PATH или готовую программу в bin/. Инструкция: FFMPEG_SETUP.md"
    )
    assets = Path(__file__).resolve().parent / "assets"
    for name in ("home.png", "dialogs.png", "plus.png", "connect.png"):
        if not (assets / name).is_file():
            errors.append(f"Нет обложки assets/{name}. Распакуйте проект целиком.")
    for error in errors:
        print("ОШИБКА · " + error)
    if errors:
        return 1
    print("Базовая проверка пройдена. Запуск: python main.py")
    print("Права Telegram по сети не проверялись. Настройка BotFather и хостинга: HOSTING_SETUP.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
