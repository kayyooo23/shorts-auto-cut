"""
Внешние вызовы к YouTube/TikTok/Instagram API мокаются — тесты проверяют
НАШУ логику (проверки владения, статусов, обработку ошибок), а не то,
что сами платформы работают.
"""

import pytest


def _make_video_moment_account(db, user, platform, output_path=None):
    from app.models import Video, Moment, SocialAccount, VideoStatus, MomentStatus

    video = Video(owner_id=user.id, filename="e.mp4", filepath="/tmp/x.mp4", status=VideoStatus.READY)
    db.add(video); db.flush()
    moment = Moment(video_id=video.id, start=0, end=10, status=MomentStatus.APPROVED, output_path=output_path)
    db.add(moment); db.flush()
    account = SocialAccount(owner_id=user.id, platform=platform, platform_account_id="acc1", access_token="secret-token")
    db.add(account); db.flush()
    db.commit()
    return moment.id, account.id


def test_publish_without_render_rejected(client, register_and_login):
    from app.models import User, Platform
    from app.database import SessionLocal

    headers, _tokens, email = register_and_login()
    db = SessionLocal()
    user = db.query(User).filter(User.email == email).first()
    moment_id, account_id = _make_video_moment_account(db, user, Platform.YOUTUBE, output_path=None)
    db.close()

    r = client.post(f"/moments/{moment_id}/publish", json={"social_account_ids": [account_id]}, headers=headers)
    assert r.status_code == 400


def test_publish_with_unknown_account_rejected(client, register_and_login):
    from app.models import User, Platform
    from app.database import SessionLocal

    headers, _tokens, email = register_and_login()
    db = SessionLocal()
    user = db.query(User).filter(User.email == email).first()
    moment_id, _account_id = _make_video_moment_account(db, user, Platform.YOUTUBE, output_path="/tmp/rendered.mp4")
    db.close()

    r = client.post(f"/moments/{moment_id}/publish", json={"social_account_ids": ["nonexistent"]}, headers=headers)
    assert r.status_code == 404


def test_publish_with_other_users_account_rejected(client, register_and_login):
    """Нельзя опубликовать свой момент через чужой подключённый аккаунт."""
    from app.models import User, Platform
    from app.database import SessionLocal

    headers_a, _tokens_a, email_a = register_and_login()
    _headers_b, _tokens_b, email_b = register_and_login()

    db = SessionLocal()
    user_a = db.query(User).filter(User.email == email_a).first()
    user_b = db.query(User).filter(User.email == email_b).first()

    moment_id, _ = _make_video_moment_account(db, user_a, Platform.YOUTUBE, output_path="/tmp/rendered.mp4")
    _, account_id_b = _make_video_moment_account(db, user_b, Platform.YOUTUBE, output_path="/tmp/rendered.mp4")
    db.close()

    r = client.post(f"/moments/{moment_id}/publish", json={"social_account_ids": [account_id_b]}, headers=headers_a)
    assert r.status_code == 404


def test_publish_target_task_success_with_mocked_publisher(register_and_login, monkeypatch):
    from app.models import User, Platform, PublishTarget, PublishStatus
    from app.database import SessionLocal
    from app.tasks import publish_target
    from app.publishers.base import UploadResult
    import app.publishers.youtube as yt_module

    monkeypatch.setattr(
        yt_module.YouTubePublisher, "upload",
        lambda self, video_path, title, description: UploadResult(remote_id="yt123", remote_url="https://youtube.com/shorts/yt123"),
    )

    _headers, _tokens, email = register_and_login()
    db = SessionLocal()
    user = db.query(User).filter(User.email == email).first()
    moment_id, account_id = _make_video_moment_account(db, user, Platform.YOUTUBE, output_path="/tmp/rendered.mp4")

    target = PublishTarget(moment_id=moment_id, social_account_id=account_id, platform=Platform.YOUTUBE, status=PublishStatus.QUEUED)
    db.add(target); db.commit()
    target_id = target.id
    db.close()

    publish_target.run(target_id)

    db = SessionLocal()
    t = db.query(PublishTarget).filter(PublishTarget.id == target_id).first()
    assert t.status == PublishStatus.PUBLISHED
    assert t.remote_url == "https://youtube.com/shorts/yt123"
    db.close()


def test_publish_target_task_failure_sets_error_message(register_and_login, monkeypatch):
    from app.models import User, Platform, PublishTarget, PublishStatus
    from app.database import SessionLocal
    from app.tasks import publish_target
    from app.publishers.base import PublishError
    import app.publishers.youtube as yt_module

    def _fail(self, video_path, title, description):
        raise PublishError("платформа временно недоступна")

    monkeypatch.setattr(yt_module.YouTubePublisher, "upload", _fail)

    _headers, _tokens, email = register_and_login()
    db = SessionLocal()
    user = db.query(User).filter(User.email == email).first()
    moment_id, account_id = _make_video_moment_account(db, user, Platform.YOUTUBE, output_path="/tmp/rendered.mp4")

    target = PublishTarget(moment_id=moment_id, social_account_id=account_id, platform=Platform.YOUTUBE, status=PublishStatus.QUEUED)
    db.add(target); db.commit()
    target_id = target.id
    db.close()

    with pytest.raises(Exception):  # Celery retry поднимает исключение при вызове .run() без брокера
        publish_target.run(target_id)

    db = SessionLocal()
    t = db.query(PublishTarget).filter(PublishTarget.id == target_id).first()
    assert t.status == PublishStatus.FAILED
    assert "недоступна" in t.error_message
    db.close()


def test_disabled_platform_connect_rejected(client, register_and_login):
    """TikTok/Instagram выключены по умолчанию (PLATFORM_ENABLED) — connect
    должен явно отказывать, а не тихо генерировать нерабочую ссылку."""
    headers, _tokens, _email = register_and_login()
    r = client.get("/social-accounts/tiktok/connect", headers=headers)
    assert r.status_code == 503


def test_enabled_platform_connect_returns_url(client, register_and_login):
    headers, _tokens, _email = register_and_login()
    r = client.get("/social-accounts/youtube/connect", headers=headers)
    assert r.status_code == 200
    assert "accounts.google.com" in r.json()["authorize_url"]


def test_oauth_callback_redirects_to_frontend_not_backend(client, register_and_login, monkeypatch):
    """Регрессия: редирект после подключения аккаунта должен вести на
    FRONTEND_BASE_URL и реальный роут /accounts — раньше здесь была строка
    вида APP_BASE_URL.replace('8000','3000'), которая указывала на
    несуществующий порт и несуществующий путь /settings/accounts."""
    from app import oauth as oauth_module
    import app.main as main_module

    headers, _tokens, _email = register_and_login()
    r = client.get("/social-accounts/youtube/connect", headers=headers)
    authorize_url = r.json()["authorize_url"]
    import urllib.parse
    state = urllib.parse.parse_qs(urllib.parse.urlparse(authorize_url).query)["state"][0]

    monkeypatch.setattr(
        oauth_module, "exchange_code",
        lambda platform, code: {
            "access_token": "tok", "refresh_token": None, "expires_at": None,
            "platform_account_id": "chan1", "platform_username": "Мой канал",
        },
    )

    r2 = client.get(
        f"/social-accounts/youtube/callback?code=fake&state={state}",
        headers=headers, follow_redirects=False,
    )
    assert r2.status_code in (302, 307)
    location = r2.headers["location"]
    assert location.startswith(main_module.FRONTEND_BASE_URL)
    assert "/accounts" in location
    assert ":3000" not in location
    assert "/settings/accounts" not in location


def test_platforms_endpoint_reports_enabled_flags(client):
    r = client.get("/platforms")
    assert r.status_code == 200
    data = {item["platform"]: item["enabled"] for item in r.json()}
    assert data["youtube"] is True
    assert data["tiktok"] is False
    assert data["instagram"] is False


# ---------- Отложенная публикация по расписанию ----------

def test_scheduled_publish_creates_queued_target_without_immediate_dispatch(client, register_and_login, monkeypatch):
    """POST /moments/{id}/publish с scheduled_at в будущем НЕ должен сразу
    отправлять задачу в очередь — она ждёт своего времени."""
    from datetime import datetime, timedelta
    from app.models import User, Platform
    from app.database import SessionLocal
    import app.tasks as tasks_module

    dispatched = []
    monkeypatch.setattr(tasks_module.publish_target, "delay", lambda tid: dispatched.append(tid))

    headers, _tokens, email = register_and_login()
    db = SessionLocal()
    user = db.query(User).filter(User.email == email).first()
    moment_id, account_id = _make_video_moment_account(db, user, Platform.YOUTUBE, output_path="/tmp/rendered.mp4")
    db.close()

    future = (datetime.utcnow() + timedelta(hours=2)).isoformat()
    r = client.post(
        f"/moments/{moment_id}/publish",
        json={"social_account_ids": [account_id], "scheduled_at": future},
        headers=headers,
    )
    assert r.status_code == 200
    assert dispatched == []  # ничего не отправлено немедленно


def test_dispatch_scheduled_publishes_picks_up_due_targets(register_and_login, monkeypatch):
    from datetime import datetime, timedelta
    from app.models import User, Platform, PublishTarget, PublishStatus
    from app.database import SessionLocal
    from app.tasks import dispatch_scheduled_publishes
    import app.tasks as tasks_module

    dispatched = []
    monkeypatch.setattr(tasks_module.publish_target, "delay", lambda tid: dispatched.append(tid))

    _headers, _tokens, email = register_and_login()
    db = SessionLocal()
    user = db.query(User).filter(User.email == email).first()
    moment_id, account_id = _make_video_moment_account(db, user, Platform.YOUTUBE, output_path="/tmp/rendered.mp4")

    # таргет "просрочен" — время публикации уже прошло
    due = PublishTarget(
        moment_id=moment_id, social_account_id=account_id, platform=Platform.YOUTUBE,
        status=PublishStatus.QUEUED, scheduled_at=datetime.utcnow() - timedelta(minutes=5),
    )
    db.add(due); db.commit()
    due_id = due.id
    db.close()

    result = dispatch_scheduled_publishes.run()

    assert result["dispatched"] == 1
    assert dispatched == [due_id]

    db = SessionLocal()
    t = db.query(PublishTarget).filter(PublishTarget.id == due_id).first()
    assert t.status == PublishStatus.PUBLISHING
    db.close()


def test_dispatch_scheduled_publishes_ignores_future_targets(register_and_login, monkeypatch):
    from datetime import datetime, timedelta
    from app.models import User, Platform, PublishTarget, PublishStatus
    from app.database import SessionLocal
    from app.tasks import dispatch_scheduled_publishes
    import app.tasks as tasks_module

    dispatched = []
    monkeypatch.setattr(tasks_module.publish_target, "delay", lambda tid: dispatched.append(tid))

    _headers, _tokens, email = register_and_login()
    db = SessionLocal()
    user = db.query(User).filter(User.email == email).first()
    moment_id, account_id = _make_video_moment_account(db, user, Platform.YOUTUBE, output_path="/tmp/rendered.mp4")

    future = PublishTarget(
        moment_id=moment_id, social_account_id=account_id, platform=Platform.YOUTUBE,
        status=PublishStatus.QUEUED, scheduled_at=datetime.utcnow() + timedelta(hours=1),
    )
    db.add(future); db.commit()
    future_id = future.id
    db.close()

    result = dispatch_scheduled_publishes.run()

    assert result["dispatched"] == 0
    assert dispatched == []

    db = SessionLocal()
    t = db.query(PublishTarget).filter(PublishTarget.id == future_id).first()
    assert t.status == PublishStatus.QUEUED  # не тронут
    db.close()


def test_dispatch_scheduled_publishes_does_not_double_dispatch(register_and_login, monkeypatch):
    """Второй тик Beat не должен повторно отправить уже отправленный таргет
    (защита через смену статуса на PUBLISHING в той же транзакции)."""
    from datetime import datetime, timedelta
    from app.models import User, Platform, PublishTarget, PublishStatus
    from app.database import SessionLocal
    from app.tasks import dispatch_scheduled_publishes
    import app.tasks as tasks_module

    dispatched = []
    monkeypatch.setattr(tasks_module.publish_target, "delay", lambda tid: dispatched.append(tid))

    _headers, _tokens, email = register_and_login()
    db = SessionLocal()
    user = db.query(User).filter(User.email == email).first()
    moment_id, account_id = _make_video_moment_account(db, user, Platform.YOUTUBE, output_path="/tmp/rendered.mp4")

    due = PublishTarget(
        moment_id=moment_id, social_account_id=account_id, platform=Platform.YOUTUBE,
        status=PublishStatus.QUEUED, scheduled_at=datetime.utcnow() - timedelta(minutes=1),
    )
    db.add(due); db.commit()
    db.close()

    dispatch_scheduled_publishes.run()  # первый тик — забирает таргет
    dispatch_scheduled_publishes.run()  # второй тик (имитация следующей минуты)

    assert len(dispatched) == 1  # отправлен ровно один раз, не дважды
