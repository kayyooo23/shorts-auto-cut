"""
Единая точка постановки фоновых задач в очередь — прячет разницу между
двумя режимами работы приложения:

- "celery" (RUNNER_MODE=celery, по умолчанию) — задача уходит через Redis
  на отдельный воркер-процесс. Нужен для облачного SaaS с несколькими
  пользователями одновременно.
- "local" (RUNNER_MODE=local) — задача выполняется в пуле потоков внутри
  ТОГО ЖЕ процесса, без Redis/Celery/Docker. Используется в desktop-версии
  (Tauri-приложение на компьютере одного пользователя).

Остальной код (app/main.py) вызывает только dispatch(task, *args) и не
знает, какой режим активен — переключение целиком в переменной окружения
RUNNER_MODE (app/config.py).
"""

import logging
from concurrent.futures import ThreadPoolExecutor

from app.config import RUNNER_MODE

logger = logging.getLogger(__name__)

# Небольшой пул потоков — desktop-режим на одном компьютере не нуждается
# в высокой параллельности; несколько потоков нужны, чтобы, например,
# рендер одного момента не блокировал транскрипцию другого видео.
_local_executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="local-job")

# Реестр: имя Celery-задачи -> обычная Python-функция с той же бизнес-логикой,
# без Celery-специфичной обвязки (self, retry, брокер). Заполняется в
# app/tasks.py через register_local() при импорте модуля.
_LOCAL_IMPLEMENTATIONS: dict = {}


def register_local(task_name: str):
    """Декоратор: регистрирует функцию как локальную реализацию Celery-задачи task_name."""
    def _decorator(fn):
        _LOCAL_IMPLEMENTATIONS[task_name] = fn
        return fn
    return _decorator


def dispatch(task, *args) -> None:
    """
    task — объект Celery-задачи (у него есть .name и .delay()).
    В режиме "celery" вызывает task.delay(*args) как обычно.
    В режиме "local" ищет зарегистрированную реализацию по task.name и
    запускает её в фоновом потоке немедленно, без Redis.

    RUNNER_MODE уже валидируется при загрузке app/config.py (там же
    выбирается дефолт с учётом sys.frozen — desktop-сборка не зависит от
    того, долетела ли переменная окружения). Проверка здесь — намеренная
    вторая линия защиты: если RUNNER_MODE всё же оказался не "local" и не
    "celery" (например, кто-то подменил его через monkeypatch мимо
    config.py), лучше упасть здесь явно и сразу, чем молча уйти в
    несуществующий Celery-брокер — тогда видео просто зависло бы в
    статусе "в очереди" НАВСЕГДА, без единой ошибки и без нагрузки на
    CPU/сеть (задача физически никогда не запускалась).
    """
    if RUNNER_MODE == "local":
        _dispatch_local(task.name, *args)
    elif RUNNER_MODE == "celery":
        task.delay(*args)
    else:
        raise RuntimeError(
            f"Некорректный RUNNER_MODE={RUNNER_MODE!r} в job_runner.dispatch() — "
            "допустимы только 'local' или 'celery'. Задача НЕ поставлена в очередь."
        )


def _dispatch_local(task_name: str, *args) -> None:
    impl = _LOCAL_IMPLEMENTATIONS.get(task_name)
    if impl is None:
        raise RuntimeError(
            f"Нет локальной реализации для задачи '{task_name}' — "
            f"проверь, что она зарегистрирована через register_local() в app/tasks.py"
        )

    def _run():
        try:
            impl(*args)
        except Exception:
            # Ошибки самой бизнес-логики уже записываются в БД (статус
            # FAILED + error_message) внутри impl — здесь только страховка,
            # чтобы исключение в фоновом потоке не терялось молча.
            logger.exception("Локальная задача '%s' завершилась с ошибкой: args=%s", task_name, args)

    _local_executor.submit(_run)


def shutdown_local_executor(wait: bool = True) -> None:
    """Для аккуратного завершения приложения (используется при остановке desktop-версии)."""
    _local_executor.shutdown(wait=wait)
