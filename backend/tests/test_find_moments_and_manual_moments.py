"""
Поиск моментов через ИИ и ручное создание момента — оба теперь отдельные
действия по требованию пользователя, а не автоматический шаг сразу после
транскрипции (см. app/tasks.py::_process_video_core и
POST /videos/{id}/find-moments, POST /videos/{id}/moments в app/main.py).
Ключевое инвариант: редактор должен быть полностью рабочим сразу после
транскрипции, независимо от того, найдены ли моменты вообще.
"""

import json

from app.database import SessionLocal
from app.models import User, Video, VideoStatus


def _make_transcribed_video(email: str, duration: float = 60.0, transcript=None) -> str:
    db = SessionLocal()
    user = db.query(User).filter(User.email == email).first()
    video = Video(
        owner_id=user.id,
        filename="e.mp4",
        filepath="/fake/path.mp4",
        duration_seconds=duration,
        status=VideoStatus.READY,
    )
    if transcript is not None:
        import tempfile
        path = tempfile.NamedTemporaryFile(suffix=".json", delete=False).name
        with open(path, "w", encoding="utf-8") as f:
            json.dump(transcript, f)
        video.transcript_path = path
    db.add(video)
    db.commit()
    video_id = video.id
    db.close()
    return video_id


# ---------- POST /videos/{id}/moments (ручное создание) ----------

def test_create_manual_moment_succeeds_without_ai(client, register_and_login):
    headers, _tokens, email = register_and_login()
    video_id = _make_transcribed_video(email)

    r = client.post(f"/videos/{video_id}/moments", json={"start": 2.0, "end": 8.5}, headers=headers)
    assert r.status_code == 201
    body = r.json()
    assert body["start"] == 2.0
    assert body["end"] == 8.5
    assert body["status"] == "pending"
    assert body["reason"] is None
    assert body["hook_line"] is None
    assert body["subtitles"] == []


def test_create_manual_moment_rejects_end_before_start(client, register_and_login):
    headers, _tokens, email = register_and_login()
    video_id = _make_transcribed_video(email)

    r = client.post(f"/videos/{video_id}/moments", json={"start": 10.0, "end": 5.0}, headers=headers)
    assert r.status_code == 422


def test_create_manual_moment_rejects_negative_start(client, register_and_login):
    headers, _tokens, email = register_and_login()
    video_id = _make_transcribed_video(email)

    r = client.post(f"/videos/{video_id}/moments", json={"start": -1.0, "end": 5.0}, headers=headers)
    assert r.status_code == 400


def test_create_manual_moment_rejects_beyond_video_duration(client, register_and_login):
    headers, _tokens, email = register_and_login()
    video_id = _make_transcribed_video(email, duration=10.0)

    r = client.post(f"/videos/{video_id}/moments", json={"start": 5.0, "end": 20.0}, headers=headers)
    assert r.status_code == 400


def test_create_manual_moment_requires_ownership(client, register_and_login):
    headers1, _tokens1, email1 = register_and_login()
    headers2, _tokens2, _email2 = register_and_login()
    video_id = _make_transcribed_video(email1)

    r = client.post(f"/videos/{video_id}/moments", json={"start": 0.0, "end": 5.0}, headers=headers2)
    assert r.status_code == 404


# ---------- POST /videos/{id}/find-moments ----------

def test_find_moments_requires_transcript(client, register_and_login):
    """Видео без transcript_path (ещё не транскрибировано) — явная 400,
    а не попытка звать Claude с пустым транскриптом."""
    headers, _tokens, email = register_and_login()
    video_id = _make_transcribed_video(email, transcript=None)

    r = client.post(f"/videos/{video_id}/find-moments", headers=headers)
    assert r.status_code == 400
    assert "транскрибировано" in r.json()["detail"]


def test_find_moments_fails_fast_without_api_key(client, register_and_login, monkeypatch):
    """Ключ не задан — проверка ДО вызова API, понятная ошибка сразу
    (тот же текст, что фронтенд уже умеет показывать со ссылкой в Настройки)."""
    monkeypatch.setattr("app.config.get_anthropic_api_key", lambda: "")

    headers, _tokens, email = register_and_login()
    video_id = _make_transcribed_video(email, transcript=[{"start": 0.0, "end": 2.0, "text": "привет"}])

    r = client.post(f"/videos/{video_id}/find-moments", headers=headers)
    assert r.status_code == 400
    assert "API ключ не задан" in r.json()["detail"]


def test_find_moments_creates_moments_and_subtitles_on_success(client, register_and_login, monkeypatch):
    import app.main as main_module
    monkeypatch.setattr("app.config.get_anthropic_api_key", lambda: "sk-ant-fake-for-test")
    monkeypatch.setattr(
        main_module, "find_moments",
        lambda transcript, count: [{"start": 1.0, "end": 4.0, "reason": "цепляет", "hook_line": "Вот это да"}],
    )

    headers, _tokens, email = register_and_login()
    transcript = [
        {"start": 0.5, "end": 2.0, "text": "первая реплика"},
        {"start": 2.5, "end": 3.8, "text": "вторая реплика"},
    ]
    video_id = _make_transcribed_video(email, transcript=transcript)

    r = client.post(f"/videos/{video_id}/find-moments", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert len(body["moments"]) == 1
    moment = body["moments"][0]
    assert moment["reason"] == "цепляет"
    assert moment["hook_line"] == "Вот это да"
    assert moment["status"] == "pending"
    assert len(moment["subtitles"]) == 2  # обе реплики транскрипта попадают в диапазон 1.0-4.0


def test_find_moments_can_be_retried_after_setting_key(client, register_and_login, monkeypatch):
    """Сценарий из задачи: сначала нет ключа (400), потом ключ появился —
    повторный вызов должен сработать и добавить моменты, ничего не сломав."""
    import app.main as main_module

    headers, _tokens, email = register_and_login()
    video_id = _make_transcribed_video(email, transcript=[{"start": 0.0, "end": 2.0, "text": "текст"}])

    monkeypatch.setattr("app.config.get_anthropic_api_key", lambda: "")
    r1 = client.post(f"/videos/{video_id}/find-moments", headers=headers)
    assert r1.status_code == 400

    monkeypatch.setattr("app.config.get_anthropic_api_key", lambda: "sk-ant-now-set")
    monkeypatch.setattr(
        main_module, "find_moments",
        lambda transcript, count: [{"start": 0.0, "end": 2.0, "reason": None, "hook_line": None}],
    )
    r2 = client.post(f"/videos/{video_id}/find-moments", headers=headers)
    assert r2.status_code == 200
    assert len(r2.json()["moments"]) == 1
