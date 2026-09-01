import pytest


def _seed_moment_with_subtitles(db, user, subtitles_texts, hook_line="Момент", reason=None):
    from app.models import Video, Moment, Subtitle, VideoStatus, MomentStatus

    video = Video(owner_id=user.id, filename="e.mp4", filepath="/tmp/x.mp4", status=VideoStatus.READY)
    db.add(video); db.flush()
    moment = Moment(video_id=video.id, start=0, end=10, status=MomentStatus.PENDING, hook_line=hook_line, reason=reason)
    db.add(moment); db.flush()
    for idx, text in enumerate(subtitles_texts):
        db.add(Subtitle(moment_id=moment.id, start=idx, end=idx + 1, text=text, order_index=idx))
    db.commit()
    return moment.id


def test_suggest_hashtags_returns_list(client, register_and_login, monkeypatch):
    import app.main as main_module

    monkeypatch.setattr(
        main_module, "suggest_hashtags",
        lambda text: ["#юмор", "#сериал", "#shorts"],
    )

    headers, _tokens, email = register_and_login()
    from app.database import SessionLocal
    from app.models import User
    db = SessionLocal()
    user = db.query(User).filter(User.email == email).first()
    moment_id = _seed_moment_with_subtitles(db, user, ["Ты серьёзно сейчас это сказал?", "Да, и я не жалею"])
    db.close()

    r = client.post(f"/moments/{moment_id}/suggest-hashtags", headers=headers)
    assert r.status_code == 200
    assert r.json() == ["#юмор", "#сериал", "#shorts"]


def test_suggest_hashtags_passes_subtitle_content(client, register_and_login, monkeypatch):
    """Проверяем, что реальный текст субтитров/hook_line доходит до функции
    подбора — не просто заглушка, которая игнорирует контент."""
    import app.main as main_module

    captured = {}

    def fake_suggest(text):
        captured["text"] = text
        return ["#тест"]

    monkeypatch.setattr(main_module, "suggest_hashtags", fake_suggest)

    headers, _tokens, email = register_and_login()
    from app.database import SessionLocal
    from app.models import User
    db = SessionLocal()
    user = db.query(User).filter(User.email == email).first()
    moment_id = _seed_moment_with_subtitles(
        db, user, ["Уникальная реплика раз", "Уникальная реплика два"],
        hook_line="Особенный хук", reason="Потому что смешно",
    )
    db.close()

    client.post(f"/moments/{moment_id}/suggest-hashtags", headers=headers)

    assert "Уникальная реплика раз" in captured["text"]
    assert "Особенный хук" in captured["text"]
    assert "Потому что смешно" in captured["text"]


def test_suggest_hashtags_requires_ownership(client, register_and_login, monkeypatch):
    import app.main as main_module
    monkeypatch.setattr(main_module, "suggest_hashtags", lambda text: ["#x"])

    _headers_a, _tokens_a, email_a = register_and_login()
    headers_b, _tokens_b, _email_b = register_and_login()

    from app.database import SessionLocal
    from app.models import User
    db = SessionLocal()
    user_a = db.query(User).filter(User.email == email_a).first()
    moment_id = _seed_moment_with_subtitles(db, user_a, ["текст"])
    db.close()

    r = client.post(f"/moments/{moment_id}/suggest-hashtags", headers=headers_b)
    assert r.status_code == 404


def test_suggest_hashtags_empty_content_rejected(client, register_and_login, monkeypatch):
    import app.main as main_module
    monkeypatch.setattr(main_module, "suggest_hashtags", lambda text: ["#x"])

    headers, _tokens, email = register_and_login()
    from app.database import SessionLocal
    from app.models import User, Video, Moment, VideoStatus, MomentStatus
    db = SessionLocal()
    user = db.query(User).filter(User.email == email).first()
    video = Video(owner_id=user.id, filename="e.mp4", filepath="/tmp/x.mp4", status=VideoStatus.READY)
    db.add(video); db.flush()
    # момент без субтитров, без hook_line, без reason — нечего анализировать
    moment = Moment(video_id=video.id, start=0, end=10, status=MomentStatus.PENDING)
    db.add(moment); db.commit()
    moment_id = moment.id
    db.close()

    r = client.post(f"/moments/{moment_id}/suggest-hashtags", headers=headers)
    assert r.status_code == 400


def test_suggest_hashtags_claude_error_returns_502(client, register_and_login, monkeypatch):
    import app.main as main_module

    def failing_suggest(text):
        raise RuntimeError("API недоступен")

    monkeypatch.setattr(main_module, "suggest_hashtags", failing_suggest)

    headers, _tokens, email = register_and_login()
    from app.database import SessionLocal
    from app.models import User
    db = SessionLocal()
    user = db.query(User).filter(User.email == email).first()
    moment_id = _seed_moment_with_subtitles(db, user, ["текст"])
    db.close()

    r = client.post(f"/moments/{moment_id}/suggest-hashtags", headers=headers)
    assert r.status_code == 502
