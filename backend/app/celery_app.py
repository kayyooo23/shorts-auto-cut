from celery import Celery

from app.config import CELERY_BROKER_URL, CELERY_RESULT_BACKEND

celery_app = Celery(
    "shorts_app",
    broker=CELERY_BROKER_URL,
    backend=CELERY_RESULT_BACKEND,
    include=["app.tasks"],
)

celery_app.conf.update(
    task_track_started=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    # обработка видео может занимать долго — не хотим, чтобы воркер
    # считался "зависшим" раньше времени
    task_time_limit=60 * 60,  # 1 час жёсткий лимит
    task_soft_time_limit=55 * 60,
    # Отложенная публикация: раз в минуту проверяем, кого пора публиковать
    # (PublishTarget с scheduled_at <= now). См. app/tasks.py::dispatch_scheduled_publishes.
    # Требует отдельного процесса: celery -A app.celery_app beat
    beat_schedule={
        "dispatch-scheduled-publishes": {
            "task": "app.tasks.dispatch_scheduled_publishes",
            "schedule": 60.0,
        },
    },
)
