@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set "PYTHONUTF8=1"
title AeniaFlow 2.8
echo AeniaFlow 2.8 - запуск
echo.
if not exist main.py (
  echo Распакуйте весь архив в обычную папку и запустите этот файл из неё.
  pause
  exit /b 1
)
if not exist .env if not exist .env.txt if not defined BOT_TOKEN (
  echo Не найден файл настроек .env из архива.
  echo Распакуйте архив целиком или перенесите свою .env из прежней папки бота.
  pause
  exit /b 1
)
set "AENIA_PYTHON=py -3"
where py >nul 2>nul
if errorlevel 1 (
  where python >nul 2>nul
  if errorlevel 1 (
    echo Установите Python 3.11 или новее и включите Add Python to PATH.
    pause
    exit /b 1
  )
  set "AENIA_PYTHON=python"
)
%AENIA_PYTHON% -c "import sys; sys.exit(not sys.version_info >= (3,11))"
if errorlevel 1 (
  echo Требуется Python 3.11 или новее.
  pause
  exit /b 1
)
if not exist .venv\Scripts\python.exe %AENIA_PYTHON% -m venv .venv
if errorlevel 1 goto failed
echo Проверка зависимостей...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto failed
".venv\Scripts\python.exe" check_setup.py
if errorlevel 1 goto failed
echo.
echo Настройки прочитаны. Запускаю бота. Остановка - Ctrl+C.
".venv\Scripts\python.exe" main.py
if errorlevel 1 goto failed
exit /b 0
:failed
echo.
echo Запуск остановлен. Причина показана выше; настройки не изменены.
pause
exit /b 1
