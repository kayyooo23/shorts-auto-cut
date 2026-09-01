# Shorts Auto-Cut

Автонарезка видео на shorts с автопубликацией. Загружаешь видео → бэкенд
транскрибирует и находит удачные моменты → фронтенд даёт отредактировать
субтитры/баннер и поставить ролик в очередь на публикацию.

Подробности о запуске и архитектуре бэкенда — в [backend/README.md](backend/README.md).

## Структура репозитория

```
backend/    — FastAPI + Celery API, пайплайн нарезки видео
frontend/   — React-интерфейс (Vite)
```

## Desktop-версия (Windows .msi)

Backend умеет работать без Redis/Celery/Docker (`RUNNER_MODE=local`, см.
[backend/app/job_runner.py](backend/app/job_runner.py)) — на этом собран
Windows-инсталлятор через Tauri, который поднимает backend как sidecar-
процесс рядом с фронтендом.

Требуется один раз: Rust (`rustup`), Tauri CLI (`npm install` в frontend/
уже ставит `@tauri-apps/cli`), Visual Studio Build Tools (компонент
"Desktop development with C++").

```powershell
# 1. Собрать backend в .exe + разложить sidecar-бинарники для Tauri
cd backend
python -m venv .venv && .venv\Scripts\pip install -r requirements.txt
powershell -ExecutionPolicy Bypass -File scripts\download_ffmpeg.ps1   # один раз
powershell -ExecutionPolicy Bypass -File scripts\build_exe.ps1

# 2. Собрать .msi
cd ..\frontend
npm install
npm run tauri build
```

Готовый `.msi` — в `frontend/src-tauri/target/release/bundle/msi/`.
Пользовательские данные (БД, загрузки, секреты, Anthropic API ключ)
хранятся в `%APPDATA%\ShortsAutoCut`, не в папке установки.

## Быстрый старт

См. [backend/README.md](backend/README.md) — там описан запуск Redis,
Celery worker/Beat и FastAPI. Для фронтенда:

```bash
cd frontend
npm install
npm run dev
```
