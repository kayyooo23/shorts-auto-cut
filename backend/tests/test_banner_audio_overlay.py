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


# ---------- Загрузка аудио-оверлея ----------

def test_upload_audio_overlay(client, register_and_login, tmp_path):
    import subprocess
    from app.models import User
    from app.database import SessionLocal

    audio_file = tmp_path / "music.mp3"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=880:duration=8", "-c:a", "mp3", str(audio_file)],
        capture_output=True, check=True,
    )

    headers, _tokens, email = register_and_login()
    db = SessionLocal()
    user = db.query(User).filter(User.email == email).first()
    moment_id = _seed_moment(db, user)  # момент длиной 5 секунд (0.0-5.0)
    db.close()

    with open(audio_file, "rb") as f:
        r = client.post(
            f"/moments/{moment_id}/audio",
            files={"file": ("music.mp3", f, "audio/mpeg")},
            headers=headers,
        )
    assert r.status_code == 200
    data = r.json()
    assert data["audio_path"] is not None
    assert data["audio_trim_start"] == 0.0
    # аудио длиннее момента (8с > 5с) — обрезка по умолчанию должна быть
    # ограничена длительностью МОМЕНТА, а не всего файла
    assert data["audio_trim_end"] == 5.0


def test_upload_audio_overlay_shorter_than_moment(client, register_and_login, tmp_path):
    """Если аудио короче момента — обрезка по умолчанию не должна
    выдумывать несуществующие секунды."""
    import subprocess
    from app.models import User
    from app.database import SessionLocal

    audio_file = tmp_path / "short.mp3"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=880:duration=2", "-c:a", "mp3", str(audio_file)],
        capture_output=True, check=True,
    )

    headers, _tokens, email = register_and_login()
    db = SessionLocal()
    user = db.query(User).filter(User.email == email).first()
    moment_id = _seed_moment(db, user)  # момент длиной 5 секунд
    db.close()

    with open(audio_file, "rb") as f:
        r = client.post(
            f"/moments/{moment_id}/audio",
            files={"file": ("short.mp3", f, "audio/mpeg")},
            headers=headers,
        )
    assert r.status_code == 200
    assert abs(r.json()["audio_trim_end"] - 2.0) < 0.2


def test_upload_audio_rejects_bad_extension(client, register_and_login):
    from app.models import User
    from app.database import SessionLocal

    headers, _tokens, email = register_and_login()
    db = SessionLocal()
    user = db.query(User).filter(User.email == email).first()
    moment_id = _seed_moment(db, user)
    db.close()

    r = client.post(
        f"/moments/{moment_id}/audio",
        files={"file": ("track.exe", io.BytesIO(b"not audio"), "application/octet-stream")},
        headers=headers,
    )
    assert r.status_code == 400


def test_delete_audio_overlay(client, register_and_login, tmp_path):
    import os
    import subprocess
    from app.models import User
    from app.database import SessionLocal

    audio_file = tmp_path / "music.mp3"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=880:duration=3", "-c:a", "mp3", str(audio_file)],
        capture_output=True, check=True,
    )

    headers, _tokens, email = register_and_login()
    db = SessionLocal()
    user = db.query(User).filter(User.email == email).first()
    moment_id = _seed_moment(db, user)
    db.close()

    with open(audio_file, "rb") as f:
        r1 = client.post(
            f"/moments/{moment_id}/audio",
            files={"file": ("music.mp3", f, "audio/mpeg")},
            headers=headers,
        )
    path = r1.json()["audio_path"]

    r2 = client.delete(f"/moments/{moment_id}/audio", headers=headers)
    assert r2.status_code == 200
    assert r2.json()["audio_path"] is None
    assert r2.json()["audio_trim_start"] is None
    assert not os.path.exists(path)


def test_update_audio_trim_via_patch(client, register_and_login, tmp_path):
    import subprocess
    from app.models import User
    from app.database import SessionLocal

    audio_file = tmp_path / "music.mp3"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=880:duration=8", "-c:a", "mp3", str(audio_file)],
        capture_output=True, check=True,
    )

    headers, _tokens, email = register_and_login()
    db = SessionLocal()
    user = db.query(User).filter(User.email == email).first()
    moment_id = _seed_moment(db, user)
    db.close()

    with open(audio_file, "rb") as f:
        client.post(f"/moments/{moment_id}/audio", files={"file": ("m.mp3", f, "audio/mpeg")}, headers=headers)

    r = client.patch(
        f"/moments/{moment_id}",
        json={"audio_trim_start": 2.0, "audio_trim_end": 6.0, "audio_volume": 0.4},
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["audio_trim_start"] == 2.0
    assert r.json()["audio_trim_end"] == 6.0
    assert r.json()["audio_volume"] == 0.4


# ---------- Интеграция с реальным рендером ----------

def test_render_task_includes_audio_overlay(register_and_login, tmp_path):
    """Сквозной тест: загружаем аудио-оверлей через API, одобряем момент,
    запускаем РЕАЛЬНУЮ задачу рендера (настоящий ffmpeg) и проверяем, что
    итоговый файл содержит звуковую дорожку — не просто что рендер не упал."""
    import subprocess
    from app.models import User, Video, Moment, VideoStatus, MomentStatus
    from app.database import SessionLocal
    from app.tasks import render_moment_task

    source = tmp_path / "source.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=size=640x480:duration=5:rate=15",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=5",
         "-c:v", "libx264", "-c:a", "aac", "-shortest", str(source)],
        capture_output=True, check=True,
    )
    overlay = tmp_path / "overlay.mp3"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=880:duration=5", "-c:a", "mp3", str(overlay)],
        capture_output=True, check=True,
    )

    _headers, _tokens, email = register_and_login()
    db = SessionLocal()
    user = db.query(User).filter(User.email == email).first()
    video = Video(owner_id=user.id, filename="e.mp4", filepath=str(source), status=VideoStatus.READY)
    db.add(video); db.flush()
    moment = Moment(video_id=video.id, start=0.0, end=3.0, status=MomentStatus.APPROVED)
    db.add(moment); db.flush()
    moment.audio_path = str(overlay)
    moment.audio_trim_start = 0.0
    moment.audio_trim_end = 3.0
    moment.audio_volume = 0.6
    moment_id = moment.id
    db.commit()
    db.close()

    render_moment_task.run(moment_id)

    db = SessionLocal()
    m = db.query(Moment).filter(Moment.id == moment_id).first()
    assert m.status == MomentStatus.RENDERED
    output_path = m.output_path
    db.close()

    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=codec_type",
         "-of", "csv=p=0", output_path],
        capture_output=True, text=True,
    )
    assert "audio" in result.stdout
