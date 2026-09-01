import io


def _seed_video_moment(db, user, filepath="/tmp/x.mp4"):
    from app.models import Video, Moment, VideoStatus, MomentStatus

    video = Video(owner_id=user.id, filename="e.mp4", filepath=filepath, status=VideoStatus.READY)
    db.add(video); db.flush()
    moment = Moment(video_id=video.id, start=0.0, end=5.0, status=MomentStatus.PENDING)
    db.add(moment); db.commit()
    return video.id, moment.id


def test_get_video_file_via_query_token(client, register_and_login, tmp_path):
    """Ключевой сценарий: <video> в браузере не может слать заголовок
    Authorization — токен должен приниматься через query-параметр."""
    import subprocess
    from app.models import User
    from app.database import SessionLocal

    real_video = tmp_path / "real.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=size=320x240:duration=2:rate=10", "-c:v", "libx264", str(real_video)],
        capture_output=True, check=True,
    )

    headers, tokens, email = register_and_login()
    db = SessionLocal()
    user = db.query(User).filter(User.email == email).first()
    video_id, _moment_id = _seed_video_moment(db, user, filepath=str(real_video))
    db.close()

    # БЕЗ заголовка Authorization — токен только в query, как это сделает <video src="...">
    r = client.get(f"/videos/{video_id}/file?token={tokens['access_token']}")
    assert r.status_code == 200
    assert r.headers["content-type"] == "video/mp4"
    assert len(r.content) > 0


def test_get_video_file_via_header_still_works(client, register_and_login, tmp_path):
    """Обратная совместимость: обычный заголовок Authorization тоже работает
    (например, если фронтенд когда-нибудь захочет использовать fetch())."""
    import subprocess
    from app.models import User
    from app.database import SessionLocal

    real_video = tmp_path / "real.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=size=320x240:duration=1:rate=10", "-c:v", "libx264", str(real_video)],
        capture_output=True, check=True,
    )

    headers, _tokens, email = register_and_login()
    db = SessionLocal()
    user = db.query(User).filter(User.email == email).first()
    video_id, _moment_id = _seed_video_moment(db, user, filepath=str(real_video))
    db.close()

    r = client.get(f"/videos/{video_id}/file", headers=headers)
    assert r.status_code == 200


def test_get_video_file_without_any_token_rejected(client, register_and_login, tmp_path):
    from app.models import User
    from app.database import SessionLocal

    _headers, _tokens, email = register_and_login()
    db = SessionLocal()
    user = db.query(User).filter(User.email == email).first()
    video_id, _moment_id = _seed_video_moment(db, user)
    db.close()

    r = client.get(f"/videos/{video_id}/file")
    assert r.status_code == 401


def test_get_video_file_requires_ownership(client, register_and_login, tmp_path):
    import subprocess
    from app.models import User
    from app.database import SessionLocal

    real_video = tmp_path / "real.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=size=320x240:duration=1:rate=10", "-c:v", "libx264", str(real_video)],
        capture_output=True, check=True,
    )

    _headers_a, _tokens_a, email_a = register_and_login()
    _headers_b, tokens_b, _email_b = register_and_login()

    db = SessionLocal()
    user_a = db.query(User).filter(User.email == email_a).first()
    video_id, _moment_id = _seed_video_moment(db, user_a, filepath=str(real_video))
    db.close()

    # у пользователя B есть валидный токен, но видео не его
    r = client.get(f"/videos/{video_id}/file?token={tokens_b['access_token']}")
    assert r.status_code == 404


def test_get_video_file_invalid_token_rejected(client, register_and_login):
    from app.models import User
    from app.database import SessionLocal

    _headers, _tokens, email = register_and_login()
    db = SessionLocal()
    user = db.query(User).filter(User.email == email).first()
    video_id, _moment_id = _seed_video_moment(db, user)
    db.close()

    r = client.get(f"/videos/{video_id}/file?token=not-a-real-jwt")
    assert r.status_code == 401


# ---------- Отдача баннера ----------

def _fake_png_bytes():
    return bytes.fromhex(
        "89504e470d0a1a0a0000000d4948445200000001000000010802000000907753"
        "de0000000c4944415478da6360000002000100"
        "0d0a2db40000000049454e44ae426082"
    )


def test_get_banner_file(client, register_and_login):
    from app.models import User
    from app.database import SessionLocal

    headers, tokens, email = register_and_login()
    db = SessionLocal()
    user = db.query(User).filter(User.email == email).first()
    _video_id, moment_id = _seed_video_moment(db, user)
    db.close()

    client.post(
        f"/moments/{moment_id}/banner",
        files={"file": ("b.png", io.BytesIO(_fake_png_bytes()), "image/png")},
        headers=headers,
    )

    r = client.get(f"/moments/{moment_id}/banner/file?token={tokens['access_token']}")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"


def test_get_banner_file_404_when_no_banner(client, register_and_login):
    from app.models import User
    from app.database import SessionLocal

    headers, tokens, email = register_and_login()
    db = SessionLocal()
    user = db.query(User).filter(User.email == email).first()
    _video_id, moment_id = _seed_video_moment(db, user)
    db.close()

    r = client.get(f"/moments/{moment_id}/banner/file?token={tokens['access_token']}")
    assert r.status_code == 404
