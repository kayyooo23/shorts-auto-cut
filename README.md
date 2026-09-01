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

## Быстрый старт

См. [backend/README.md](backend/README.md) — там описан запуск Redis,
Celery worker/Beat и FastAPI. Для фронтенда:

```bash
cd frontend
npm install
npm run dev
```
