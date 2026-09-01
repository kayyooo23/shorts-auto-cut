"""
Точка входа для desktop-сборки (PyInstaller).

Обычный запуск в разработке идёт через `uvicorn app.main:app` (CLI, см.
start_all.bat) — в собранном .exe такого CLI нет, поэтому сервер здесь
поднимается программно через uvicorn.run().

RUNNER_MODE выставляется в "local" ДО импорта app.main (а значит и до
app.config) — desktop-сборка всегда работает в locale-режиме (без Redis/
Celery), даже если переменная окружения в системе выставлена иначе.
"""

import os

os.environ["RUNNER_MODE"] = "local"

import uvicorn  # noqa: E402

from app.main import app  # noqa: E402


def main() -> None:
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")


if __name__ == "__main__":
    main()
