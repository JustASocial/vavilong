@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
if not exist ".venv\Scripts\python.exe" (
  echo [i] Создаю виртуальное окружение...
  py -3 -m venv .venv
  ".venv\Scripts\python.exe" -m pip install --upgrade pip
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
)
echo [i] Запуск Vavilong Tools...
".venv\Scripts\python.exe" -m app
pause
