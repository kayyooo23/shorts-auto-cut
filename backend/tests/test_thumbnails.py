import subprocess


def _seed_video_moment(db, user, filepath):
    from app.models import Video, Moment, VideoStatus, MomentStatus

    video = Video(owner_id=user.id, filename="e.mp4", filepath=filepath, status=VideoStatus.READY)
    db.add(video); db.flush()
    moment = Moment(video_id=video.id, start=2.0, end=6.0, status=MomentStatus.PENDING)
    db.add(moment); db.commit()
    return video.id, moment.id


def test_get_moment_thumbnail(client, register_and_login, tmp_path):
    from app.models import User
    from app.database import SessionLocal

    real_video = tmp_path / "real.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=size=320x240:duration=8:rate=10", "-c:v", "libx264", str(real_video)],
        capture_output=True, check=True,
    )

    headers, tokens, email = register_and_login()
    db = SessionLocal()
    user = db.query(User).filter(User.email == email).first()
    _video_id, moment_id = _seed_video_moment(db, user, str(real_video))
    db.close()

    r = client.get(f"/moments/{moment_id}/thumbnail?token={tokens['access_token']}")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/jpeg"
    assert len(r.content) > 0


def test_moment_thumbnail_is_cached(client, register_and_login, tmp_path):
    """Повторный запрос той же миниатюры не должен пересоздавать файл —
    проверяем, что путь на диске идентичен между двумя запросами."""
    import re
    from app.models import User
    from app.database import SessionLocal
    from app.config import OUTPUTS_DIR

    real_video = tmp_path / "real.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=size=320x240:duration=8:rate=10", "-c:v", "libx264", str(real_video)],
        capture_output=True, check=True,
    )

    headers, tokens, email = register_and_login()
    db = SessionLocal()
    user = db.query(User).filter(User.email == email).first()
    _video_id, moment_id = _seed_video_moment(db, user, str(real_video))
    db.close()

    from pipeline.thumbnail import get_or_create_thumbnail
    path1 = get_or_create_thumbnail(str(real_video), 2.0)
    mtime1 = __import__("os").path.getmtime(path1)

    path2 = get_or_create_thumbnail(str(real_video), 2.0)
    mtime2 = __import__("os").path.getmtime(path2)

    assert path1 == path2
    assert mtime1 == mtime2  # файл не пересоздавался


def test_get_clip_thumbnail(client, register_and_login, tmp_path):
    from app.models import User
    from app.database import SessionLocal

    real_video = tmp_path / "real.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=size=320x240:duration=8:rate=10", "-c:v", "libx264", str(real_video)],
        capture_output=True, check=True,
    )
    pip_video = tmp_path / "pip.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=lime:size=200x150:duration=4", "-c:v", "libx264", str(pip_video)],
        capture_output=True, check=True,
    )

    headers, tokens, email = register_and_login()
    db = SessionLocal()
    user = db.query(User).filter(User.email == email).first()
    _video_id, moment_id = _seed_video_moment(db, user, str(real_video))
    db.close()

    r = client.post(f"/moments/{moment_id}/tracks", json={"type": "video"}, headers=headers)
    track_id = r.json()["id"]
    with open(pip_video, "rb") as f:
        r2 = client.post(f"/tracks/{track_id}/clips", files={"file": ("pip.mp4", f, "video/mp4")}, headers=headers)
    clip_id = r2.json()["id"]

    r3 = client.get(f"/clips/{clip_id}/thumbnail?token={tokens['access_token']}")
    assert r3.status_code == 200
    assert r3.headers["content-type"] == "image/jpeg"


def test_thumbnail_requires_ownership(client, register_and_login, tmp_path):
    from app.models import User
    from app.database import SessionLocal

    real_video = tmp_path / "real.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=size=320x240:duration=8:rate=10", "-c:v", "libx264", str(real_video)],
        capture_output=True, check=True,
    )

    _headers_a, _tokens_a, email_a = register_and_login()
    _headers_b, tokens_b, _email_b = register_and_login()

    db = SessionLocal()
    user_a = db.query(User).filter(User.email == email_a).first()
    _video_id, moment_id = _seed_video_moment(db, user_a, str(real_video))
    db.close()

    r = client.get(f"/moments/{moment_id}/thumbnail?token={tokens_b['access_token']}")
    assert r.status_code == 404


def test_thumbnail_without_token_rejected(client, register_and_login, tmp_path):
    from app.models import User
    from app.database import SessionLocal

    real_video = tmp_path / "real.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=size=320x240:duration=8:rate=10", "-c:v", "libx264", str(real_video)],
        capture_output=True, check=True,
    )

    _headers, _tokens, email = register_and_login()
    db = SessionLocal()
    user = db.query(User).filter(User.email == email).first()
    _video_id, moment_id = _seed_video_moment(db, user, str(real_video))
    db.close()

    r = client.get(f"/moments/{moment_id}/thumbnail")
    assert r.status_code == 401


# ---------- Миниатюра видео целиком (для списка "Мои видео") ----------

def test_get_video_thumbnail(client, register_and_login, tmp_path):
    from app.models import User, Video, VideoStatus
    from app.database import SessionLocal

    real_video = tmp_path / "real.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=size=320x240:duration=10:rate=10", "-c:v", "libx264", str(real_video)],
        capture_output=True, check=True,
    )

    headers, tokens, email = register_and_login()
    db = SessionLocal()
    user = db.query(User).filter(User.email == email).first()
    video = Video(owner_id=user.id, filename="e.mp4", filepath=str(real_video), status=VideoStatus.READY, duration_seconds=10.0)
    db.add(video); db.commit()
    video_id = video.id
    db.close()

    r = client.get(f"/videos/{video_id}/thumbnail?token={tokens['access_token']}")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/jpeg"
    assert len(r.content) > 0


def test_video_thumbnail_works_before_processing_complete(client, register_and_login, tmp_path):
    """Миниатюра видео должна работать сразу после загрузки, не дожидаясь
    окончания транскрипции/поиска моментов — нужен только сам файл."""
    from app.models import User, Video, VideoStatus
    from app.database import SessionLocal

    real_video = tmp_path / "real.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=size=320x240:duration=6:rate=10", "-c:v", "libx264", str(real_video)],
        capture_output=True, check=True,
    )

    headers, tokens, email = register_and_login()
    db = SessionLocal()
    user = db.query(User).filter(User.email == email).first()
    # статус UPLOADED — обработка ещё не началась, duration_seconds ещё нет
    video = Video(owner_id=user.id, filename="e.mp4", filepath=str(real_video), status=VideoStatus.UPLOADED)
    db.add(video); db.commit()
    video_id = video.id
    db.close()

    r = client.get(f"/videos/{video_id}/thumbnail?token={tokens['access_token']}")
    assert r.status_code == 200


def test_video_thumbnail_requires_ownership(client, register_and_login, tmp_path):
    from app.models import User, Video, VideoStatus
    from app.database import SessionLocal

    real_video = tmp_path / "real.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=size=320x240:duration=6:rate=10", "-c:v", "libx264", str(real_video)],
        capture_output=True, check=True,
    )

    _headers_a, _tokens_a, email_a = register_and_login()
    _headers_b, tokens_b, _email_b = register_and_login()

    db = SessionLocal()
    user_a = db.query(User).filter(User.email == email_a).first()
    video = Video(owner_id=user_a.id, filename="e.mp4", filepath=str(real_video), status=VideoStatus.READY)
    db.add(video); db.commit()
    video_id = video.id
    db.close()

    r = client.get(f"/videos/{video_id}/thumbnail?token={tokens_b['access_token']}")
    assert r.status_code == 404
