"""
Проверяет RUNNER_MODE=local: задачи реально выполняются в фоновом потоке
пула (не в Celery, без брокера) и приводят к тем же изменениям в БД, что
и Celery-режим. Тесты меняют app.config.RUNNER_MODE через monkeypatch на
время теста и опрашивают БД в цикле (задача асинхронна — нет .get()
как у Celery-результата, только реальное ожидание).
"""

import subprocess
import time

import pytest


@pytest.fixture(scope="module")
def source_video(tmp_path_factory):
    path = tmp_path_factory.mktemp("local_mode_src") / "source.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=size=640x480:duration=5:rate=15",
         "-c:v", "libx264", str(path)],
        capture_output=True, check=True,
    )
    return str(path)


def _wait_until(predicate, timeout=15, interval=0.2):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


@pytest.fixture()
def local_mode(monkeypatch):
    """Переключает job_runner в локальный режим на время теста."""
    import app.config as config_module
    import app.job_runner as job_runner_module
    monkeypatch.setattr(config_module, "RUNNER_MODE", "local")
    monkeypatch.setattr(job_runner_module, "RUNNER_MODE", "local")
    yield


def test_dispatch_runs_locally_without_celery(local_mode, register_and_login, source_video):
    """POST /moments/{id}/render в локальном режиме должен реально
    отрендерить файл через ffmpeg в фоновом потоке — без Celery-воркера,
    без Redis, без .delay()."""
    from app.models import User, Video, Moment, VideoStatus, MomentStatus
    from app.database import SessionLocal

    headers, _tokens, email = register_and_login()
    db = SessionLocal()
    user = db.query(User).filter(User.email == email).first()
    video = Video(owner_id=user.id, filename="e.mp4", filepath=source_video, status=VideoStatus.READY)
    db.add(video); db.flush()
    moment = Moment(video_id=video.id, start=0, end=2, status=MomentStatus.APPROVED)
    db.add(moment); db.flush()
    moment_id = moment.id
    db.commit()
    db.close()

    from app.job_runner import dispatch
    from app.tasks import render_moment_task
    dispatch(render_moment_task, moment_id)  # напрямую, минуя HTTP-эндпоинт — тест самого job_runner

    def _rendered():
        db2 = SessionLocal()
        m = db2.query(Moment).filter(Moment.id == moment_id).first()
        result = m.status == MomentStatus.RENDERED
        db2.close()
        return result

    assert _wait_until(_rendered, timeout=20), "Момент не отрендерился за отведённое время в локальном режиме"

    db = SessionLocal()
    m = db.query(Moment).filter(Moment.id == moment_id).first()
    import os
    assert os.path.exists(m.output_path)
    db.close()


def test_local_dispatch_unknown_task_raises(local_mode):
    """Если для задачи нет зарегистрированной локальной реализации —
    должна быть явная ошибка при попытке диспетчеризации, а не тихий no-op."""
    from app.job_runner import dispatch

    class FakeTask:
        name = "app.tasks.definitely_not_registered"

        def delay(self, *args):
            pass

    with pytest.raises(RuntimeError):
        from app.job_runner import _dispatch_local
        _dispatch_local(FakeTask.name)


def test_celery_mode_still_uses_delay_by_default(monkeypatch):
    """Регрессия: без local_mode fixture (обычный режим celery) dispatch()
    должен по-прежнему вызывать task.delay(), а не локальный executor."""
    from app.job_runner import dispatch

    called = []

    class FakeTask:
        name = "app.tasks.fake"

        def delay(self, *args):
            called.append(args)

    dispatch(FakeTask(), "arg1", "arg2")
    assert called == [("arg1", "arg2")]


def test_publish_target_runs_locally(local_mode, register_and_login, monkeypatch, source_video):
    from app.models import User, Video, Moment, SocialAccount, PublishTarget, VideoStatus, MomentStatus, Platform, PublishStatus
    from app.database import SessionLocal
    from app.publishers.base import UploadResult
    import app.publishers.youtube as yt_module

    monkeypatch.setattr(
        yt_module.YouTubePublisher, "upload",
        lambda self, video_path, title, description: UploadResult(remote_id="local1", remote_url="https://youtube.com/shorts/local1"),
    )

    _headers, _tokens, email = register_and_login()
    db = SessionLocal()
    user = db.query(User).filter(User.email == email).first()
    video = Video(owner_id=user.id, filename="e.mp4", filepath=source_video, status=VideoStatus.READY)
    db.add(video); db.flush()
    moment = Moment(video_id=video.id, start=0, end=2, status=MomentStatus.RENDERED, output_path=source_video)
    db.add(moment); db.flush()
    account = SocialAccount(owner_id=user.id, platform=Platform.YOUTUBE, platform_account_id="acc1", access_token="x")
    db.add(account); db.flush()
    target = PublishTarget(moment_id=moment.id, social_account_id=account.id, platform=Platform.YOUTUBE, status=PublishStatus.QUEUED)
    db.add(target); db.commit()
    target_id = target.id
    db.close()

    from app.job_runner import dispatch
    from app.tasks import publish_target
    dispatch(publish_target, target_id)

    def _published():
        db2 = SessionLocal()
        t = db2.query(PublishTarget).filter(PublishTarget.id == target_id).first()
        result = t.status == PublishStatus.PUBLISHED
        db2.close()
        return result

    assert _wait_until(_published, timeout=15), "Публикация не завершилась в локальном режиме"


def test_upload_marks_video_failed_if_dispatch_raises_synchronously(client, register_and_login, source_video, monkeypatch):
    """
    Баг из продакшена: если dispatch() падает СИНХРОННО прямо в обработчике
    /videos/upload (например, RUNNER_MODE каким-то образом не долетел до
    "local" в desktop-сборке и код пытается достучаться до
    несуществующего Celery-брокера, или задача не зарегистрирована для
    локального режима) — видео уже создано в БД (committed) ДО вызова
    dispatch(), и без обработки такой ошибки статус остаётся "uploaded"
    НАВСЕГДА: пользователь видит бесконечное "В очереди на обработку" без
    единого намёка на ошибку. Эндпоинт должен ловить это и переводить
    видео в failed с понятным error_message, а не ронять запрос как 500
    и терять единственную ссылку на созданную запись.
    """
    import app.main as main_module

    def _boom(task, *args):
        raise RuntimeError("Нет локальной реализации для задачи — тестовая имитация сбоя dispatch")

    monkeypatch.setattr(main_module, "dispatch", _boom)

    headers, _tokens, _email = register_and_login()
    with open(source_video, "rb") as f:
        r = client.post("/videos/upload", files={"file": ("e.mp4", f, "video/mp4")}, headers=headers)

    assert r.status_code == 200  # не 500 — ответ есть, видео не потеряно
    body = r.json()["video"]
    assert body["status"] == "failed"
    assert "очередь" in body["error_message"].lower()

    r2 = client.get(f"/videos/{body['id']}", headers=headers)
    assert r2.json()["status"] == "failed"


def test_dispatch_raises_immediately_on_invalid_runner_mode(monkeypatch):
    """
    Если RUNNER_MODE не "local" и не "celery" (опечатка, будущая ошибка
    конфигурации) — dispatch() должен явно упасть сразу же, а не молча
    попытаться уйти в несуществующий Celery-брокер. Тихий уход в никуда —
    именно то, из-за чего видео зависало в статусе "в очереди" навсегда:
    без ошибки и без единой попытки её показать пользователю.
    """
    import app.job_runner as job_runner_module

    monkeypatch.setattr(job_runner_module, "RUNNER_MODE", "definitely-not-a-real-mode")

    with pytest.raises(RuntimeError, match="Некорректный RUNNER_MODE"):
        job_runner_module.dispatch(object())
