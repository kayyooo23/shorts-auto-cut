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
import sys

os.environ["RUNNER_MODE"] = "local"

import uvicorn  # noqa: E402

from app.main import app  # noqa: E402
from app import config  # noqa: E402


def _log_startup_diagnostics() -> None:
    """
    Печатает в stdout (видно в консоли desktop-приложения) эффективные
    значения ключевых настроек — RUNNER_MODE и пути к ffmpeg/ffprobe чаще
    всего оказываются виновниками "видео зависло в обработке навсегда" в
    desktop-сборке, если переменная окружения не долетела или бинарник
    не нашёлся рядом с .exe. Без этой строчки диагностировать такое можно
    было только через пошаговую отладку самой сборки.
    """
    print(f"[startup] RUNNER_MODE={config.RUNNER_MODE}", file=sys.stderr)
    print(f"[startup] BASE_DIR={config.BASE_DIR}", file=sys.stderr)
    print(f"[startup] EXTERNAL_RESOURCE_DIR={config.EXTERNAL_RESOURCE_DIR}", file=sys.stderr)
    print(f"[startup] DATA_DIR={config.DATA_DIR}", file=sys.stderr)
    print(f"[startup] FFMPEG_PATH={config.FFMPEG_PATH} (exists={os.path.exists(config.FFMPEG_PATH)})", file=sys.stderr)
    print(f"[startup] FFPROBE_PATH={config.FFPROBE_PATH} (exists={os.path.exists(config.FFPROBE_PATH)})", file=sys.stderr)


def main() -> None:
    _log_startup_diagnostics()
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")


if __name__ == "__main__":
    main()
