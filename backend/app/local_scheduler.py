"""
Замена Celery Beat для RUNNER_MODE=local (desktop): фоновый поток, который
раз в минуту вызывает dispatch_scheduled_publishes — ту же функцию, что в
облачном режиме дёргает настоящий Celery Beat. Логика отложенной публикации
(app/tasks.py::_dispatch_scheduled_publishes_core) идентична в обоих режимах,
здесь только другой "будильник".

Запускается один раз при старте приложения (см. main.py), если активен
локальный режим — в Celery-режиме этот поток не нужен вообще, там время
проверки настроено в app/celery_app.py::beat_schedule.
"""

import logging
import threading

logger = logging.getLogger(__name__)

_stop_event = threading.Event()
_thread: threading.Thread | None = None


def _loop(interval_seconds: int):
    # Локальный импорт — чтобы избежать циклического импорта на старте
    # приложения (tasks.py импортирует celery_app, main.py импортирует и
    # tasks, и этот модуль).
    from app.tasks import _dispatch_scheduled_publishes_core

    while not _stop_event.wait(timeout=interval_seconds):
        try:
            _dispatch_scheduled_publishes_core()
        except Exception:
            logger.exception("Локальный планировщик: ошибка в dispatch_scheduled_publishes")


def start(interval_seconds: int = 60) -> None:
    global _thread
    if _thread is not None and _thread.is_alive():
        return  # уже запущен — например, при --reload в uvicorn
    _stop_event.clear()
    _thread = threading.Thread(target=_loop, args=(interval_seconds,), daemon=True, name="local-scheduler")
    _thread.start()


def stop() -> None:
    _stop_event.set()
    if _thread is not None:
        _thread.join(timeout=5)
