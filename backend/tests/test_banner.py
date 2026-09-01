import io


def _seed_moment(db, user):
    from app.models import Video, Moment, VideoStatus, MomentStatus

    video = Video(owner_id=user.id, filename="e.mp4", filepath="/tmp/x.mp4", status=VideoStatus.READY)
    db.add(video); db.flush()
    moment = Moment(video_id=video.id, start=0.0, end=5.0, status=MomentStatus.PENDING)
    db.add(moment); db.commit()
    return moment.id


def _fake_png_bytes():
    # Реальный минимальный валидный PNG (1x1 пиксель) — не просто случайные байты
    return bytes.fromhex(
        "89504e470d0a1a0a0000000d4948445200000001000000010802000000907753"
        "de0000000c4944415478da6360000002000100"
        "0d0a2db40000000049454e44ae426082"
    )


# ---------- Загрузка баннера ----------

def test_upload_banner(client, register_and_login):
    from app.models import User
    from app.database import SessionLocal

    headers, _tokens, email = register_and_login()
    db = SessionLocal()
    user = db.query(User).filter(User.email == email).first()
    moment_id = _seed_moment(db, user)
    db.close()

    r = client.post(
        f"/moments/{moment_id}/banner",
        files={"file": ("banner.png", io.BytesIO(_fake_png_bytes()), "image/png")},
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["banner_path"] is not None
    assert r.json()["banner_path"].endswith(".png")


def test_upload_banner_rejects_bad_extension(client, register_and_login):
    from app.models import User
    from app.database import SessionLocal

    headers, _tokens, email = register_and_login()
    db = SessionLocal()
    user = db.query(User).filter(User.email == email).first()
    moment_id = _seed_moment(db, user)
    db.close()

    r = client.post(
        f"/moments/{moment_id}/banner",
        files={"file": ("banner.exe", io.BytesIO(b"not an image"), "application/octet-stream")},
        headers=headers,
    )
    assert r.status_code == 400


def test_upload_banner_replaces_previous_file(client, register_and_login):
    """Повторная загрузка баннера С ДРУГИМ расширением должна удалить с
    диска предыдущий файл, не оставляя мусор. (Если расширение то же —
    путь совпадает, и это просто перезапись, не отдельный случай.)"""
    import os
    from app.models import User
    from app.database import SessionLocal

    headers, _tokens, email = register_and_login()
    db = SessionLocal()
    user = db.query(User).filter(User.email == email).first()
    moment_id = _seed_moment(db, user)
    db.close()

    r1 = client.post(
        f"/moments/{moment_id}/banner",
        files={"file": ("first.png", io.BytesIO(_fake_png_bytes()), "image/png")},
        headers=headers,
    )
    first_path = r1.json()["banner_path"]
    assert os.path.exists(first_path)
    assert first_path.endswith(".png")

    r2 = client.post(
        f"/moments/{moment_id}/banner",
        files={"file": ("second.jpg", io.BytesIO(_fake_png_bytes()), "image/jpeg")},
        headers=headers,
    )
    second_path = r2.json()["banner_path"]
    assert second_path.endswith(".jpg")

    assert not os.path.exists(first_path)  # старый .png реально удалён
    assert os.path.exists(second_path)


def test_delete_banner(client, register_and_login):
    import os
    from app.models import User
    from app.database import SessionLocal

    headers, _tokens, email = register_and_login()
    db = SessionLocal()
    user = db.query(User).filter(User.email == email).first()
    moment_id = _seed_moment(db, user)
    db.close()

    r1 = client.post(
        f"/moments/{moment_id}/banner",
        files={"file": ("b.png", io.BytesIO(_fake_png_bytes()), "image/png")},
        headers=headers,
    )
    path = r1.json()["banner_path"]

    r2 = client.delete(f"/moments/{moment_id}/banner", headers=headers)
    assert r2.status_code == 200
    assert r2.json()["banner_path"] is None
    assert not os.path.exists(path)


def test_banner_upload_requires_ownership(client, register_and_login):
    from app.models import User
    from app.database import SessionLocal

    _headers_a, _tokens_a, email_a = register_and_login()
    headers_b, _tokens_b, _email_b = register_and_login()

    db = SessionLocal()
    user_a = db.query(User).filter(User.email == email_a).first()
    moment_id = _seed_moment(db, user_a)
    db.close()

    r = client.post(
        f"/moments/{moment_id}/banner",
        files={"file": ("b.png", io.BytesIO(_fake_png_bytes()), "image/png")},
        headers=headers_b,
    )
    assert r.status_code == 404

