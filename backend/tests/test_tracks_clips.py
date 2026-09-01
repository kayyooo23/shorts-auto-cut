import io
import subprocess


def _seed_moment(db, user, duration=5.0):
    from app.models import Video, Moment, VideoStatus, MomentStatus

    video = Video(owner_id=user.id, filename="e.mp4", filepath="/tmp/x.mp4", status=VideoStatus.READY)
    db.add(video); db.flush()
    moment = Moment(video_id=video.id, start=0.0, end=duration, status=MomentStatus.PENDING)
    db.add(moment); db.commit()
    return video.id, moment.id


def _make_test_audio(tmp_path, name, duration, frequency=880):
    path = tmp_path / name
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", f"sine=frequency={frequency}:duration={duration}", "-c:a", "mp3", str(path)],
        capture_output=True, check=True,
    )
    return str(path)


def _make_test_video(tmp_path, name, duration, with_audio=True, frequency=440):
    path = tmp_path / name
    cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i", f"testsrc=size=320x240:duration={duration}:rate=15"]
    if with_audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency={frequency}:duration={duration}", "-c:a", "aac", "-shortest"]
    cmd += ["-c:v", "libx264", str(path)]
    subprocess.run(cmd, capture_output=True, check=True)
    return str(path)


# ---------- Создание/удаление дорожек ----------

def test_create_audio_track(client, register_and_login):
    from app.models import User
    from app.database import SessionLocal

    headers, _tokens, email = register_and_login()
    db = SessionLocal()
    user = db.query(User).filter(User.email == email).first()
    _video_id, moment_id = _seed_moment(db, user)
    db.close()

    r = client.post(f"/moments/{moment_id}/tracks", json={"type": "audio", "name": "Музыка"}, headers=headers)
    assert r.status_code == 201
    assert r.json()["type"] == "audio"
    assert r.json()["name"] == "Музыка"
    assert r.json()["clips"] == []


def test_create_video_track(client, register_and_login):
    from app.models import User
    from app.database import SessionLocal

    headers, _tokens, email = register_and_login()
    db = SessionLocal()
    user = db.query(User).filter(User.email == email).first()
    _video_id, moment_id = _seed_moment(db, user)
    db.close()

    r = client.post(f"/moments/{moment_id}/tracks", json={"type": "video"}, headers=headers)
    assert r.status_code == 201
    assert r.json()["type"] == "video"


def test_create_track_invalid_type_rejected(client, register_and_login):
    from app.models import User
    from app.database import SessionLocal

    headers, _tokens, email = register_and_login()
    db = SessionLocal()
    user = db.query(User).filter(User.email == email).first()
    _video_id, moment_id = _seed_moment(db, user)
    db.close()

    r = client.post(f"/moments/{moment_id}/tracks", json={"type": "banana"}, headers=headers)
    assert r.status_code == 400


def test_multiple_tracks_get_incrementing_order(client, register_and_login):
    from app.models import User
    from app.database import SessionLocal

    headers, _tokens, email = register_and_login()
    db = SessionLocal()
    user = db.query(User).filter(User.email == email).first()
    _video_id, moment_id = _seed_moment(db, user)
    db.close()

    r1 = client.post(f"/moments/{moment_id}/tracks", json={"type": "audio"}, headers=headers)
    r2 = client.post(f"/moments/{moment_id}/tracks", json={"type": "video"}, headers=headers)
    r3 = client.post(f"/moments/{moment_id}/tracks", json={"type": "audio"}, headers=headers)

    assert [r1.json()["order_index"], r2.json()["order_index"], r3.json()["order_index"]] == [0, 1, 2]


def test_delete_track_requires_ownership(client, register_and_login):
    from app.models import User
    from app.database import SessionLocal

    headers_a, _tokens_a, email_a = register_and_login()
    headers_b, _tokens_b, _email_b = register_and_login()

    db = SessionLocal()
    user_a = db.query(User).filter(User.email == email_a).first()
    _video_id, moment_id = _seed_moment(db, user_a)
    db.close()

    r = client.post(f"/moments/{moment_id}/tracks", json={"type": "audio"}, headers=headers_a)
    track_id = r.json()["id"]

    r2 = client.delete(f"/tracks/{track_id}", headers=headers_b)
    assert r2.status_code == 404


def test_delete_track_removes_clips_too(client, register_and_login, tmp_path):
    import os
    from app.models import User
    from app.database import SessionLocal

    headers, _tokens, email = register_and_login()
    db = SessionLocal()
    user = db.query(User).filter(User.email == email).first()
    _video_id, moment_id = _seed_moment(db, user)
    db.close()

    r = client.post(f"/moments/{moment_id}/tracks", json={"type": "audio"}, headers=headers)
    track_id = r.json()["id"]

    audio_path = _make_test_audio(tmp_path, "m.mp3", 3)
    with open(audio_path, "rb") as f:
        r2 = client.post(f"/tracks/{track_id}/clips", files={"file": ("m.mp3", f, "audio/mpeg")}, headers=headers)
    clip_file_path = r2.json()["file_path"]
    assert os.path.exists(clip_file_path)

    r3 = client.delete(f"/tracks/{track_id}", headers=headers)
    assert r3.status_code == 200
    assert not os.path.exists(clip_file_path)


# ---------- Загрузка клипов ----------

def test_upload_audio_clip_defaults(client, register_and_login, tmp_path):
    """Клип короче момента — по умолчанию должен занимать себя целиком,
    от начала момента."""
    from app.models import User
    from app.database import SessionLocal

    headers, _tokens, email = register_and_login()
    db = SessionLocal()
    user = db.query(User).filter(User.email == email).first()
    _video_id, moment_id = _seed_moment(db, user, duration=10.0)
    db.close()

    r = client.post(f"/moments/{moment_id}/tracks", json={"type": "audio"}, headers=headers)
    track_id = r.json()["id"]

    audio_path = _make_test_audio(tmp_path, "m.mp3", 4)
    with open(audio_path, "rb") as f:
        r2 = client.post(f"/tracks/{track_id}/clips", files={"file": ("m.mp3", f, "audio/mpeg")}, headers=headers)

    assert r2.status_code == 201
    data = r2.json()
    assert abs(data["source_duration"] - 4.0) < 0.2
    assert data["position_start"] == 0.0
    assert abs(data["position_end"] - 4.0) < 0.2
    assert data["trim_start"] == 0.0


def test_upload_clip_clamped_to_moment_duration(client, register_and_login, tmp_path):
    """Файл длиннее момента — дефолтная обрезка не должна вылезать за
    пределы длительности момента."""
    from app.models import User
    from app.database import SessionLocal

    headers, _tokens, email = register_and_login()
    db = SessionLocal()
    user = db.query(User).filter(User.email == email).first()
    _video_id, moment_id = _seed_moment(db, user, duration=3.0)
    db.close()

    r = client.post(f"/moments/{moment_id}/tracks", json={"type": "audio"}, headers=headers)
    track_id = r.json()["id"]

    audio_path = _make_test_audio(tmp_path, "long.mp3", 10)
    with open(audio_path, "rb") as f:
        r2 = client.post(f"/tracks/{track_id}/clips", files={"file": ("long.mp3", f, "audio/mpeg")}, headers=headers)

    assert r2.json()["position_end"] == 3.0


def test_upload_clip_bad_extension_rejected(client, register_and_login):
    from app.models import User
    from app.database import SessionLocal

    headers, _tokens, email = register_and_login()
    db = SessionLocal()
    user = db.query(User).filter(User.email == email).first()
    _video_id, moment_id = _seed_moment(db, user)
    db.close()

    r = client.post(f"/moments/{moment_id}/tracks", json={"type": "video"}, headers=headers)
    track_id = r.json()["id"]

    r2 = client.post(
        f"/tracks/{track_id}/clips",
        files={"file": ("bad.exe", io.BytesIO(b"not media"), "application/octet-stream")},
        headers=headers,
    )
    assert r2.status_code == 400


def test_upload_video_clip_to_video_track(client, register_and_login, tmp_path):
    from app.models import User
    from app.database import SessionLocal

    headers, _tokens, email = register_and_login()
    db = SessionLocal()
    user = db.query(User).filter(User.email == email).first()
    _video_id, moment_id = _seed_moment(db, user, duration=6.0)
    db.close()

    r = client.post(f"/moments/{moment_id}/tracks", json={"type": "video"}, headers=headers)
    track_id = r.json()["id"]

    clip_video = _make_test_video(tmp_path, "pip.mp4", 4, with_audio=False)
    with open(clip_video, "rb") as f:
        r2 = client.post(f"/tracks/{track_id}/clips", files={"file": ("pip.mp4", f, "video/mp4")}, headers=headers)

    assert r2.status_code == 201
    assert r2.json()["pip_width"] == 0.35  # дефолт из модели


# ---------- Правка клипов ----------

def test_update_clip_position_and_trim(client, register_and_login, tmp_path):
    from app.models import User
    from app.database import SessionLocal

    headers, _tokens, email = register_and_login()
    db = SessionLocal()
    user = db.query(User).filter(User.email == email).first()
    _video_id, moment_id = _seed_moment(db, user, duration=10.0)
    db.close()

    r = client.post(f"/moments/{moment_id}/tracks", json={"type": "audio"}, headers=headers)
    track_id = r.json()["id"]
    audio_path = _make_test_audio(tmp_path, "m.mp3", 8)
    with open(audio_path, "rb") as f:
        r2 = client.post(f"/tracks/{track_id}/clips", files={"file": ("m.mp3", f, "audio/mpeg")}, headers=headers)
    clip_id = r2.json()["id"]

    r3 = client.patch(
        f"/clips/{clip_id}",
        json={"position_start": 2.0, "position_end": 6.0, "trim_start": 1.0, "trim_end": 5.0, "volume": 0.3},
        headers=headers,
    )
    assert r3.status_code == 200
    assert r3.json()["position_start"] == 2.0
    assert r3.json()["volume"] == 0.3


def test_update_clip_pip_position(client, register_and_login, tmp_path):
    from app.models import User
    from app.database import SessionLocal

    headers, _tokens, email = register_and_login()
    db = SessionLocal()
    user = db.query(User).filter(User.email == email).first()
    _video_id, moment_id = _seed_moment(db, user, duration=6.0)
    db.close()

    r = client.post(f"/moments/{moment_id}/tracks", json={"type": "video"}, headers=headers)
    track_id = r.json()["id"]
    clip_video = _make_test_video(tmp_path, "pip.mp4", 3, with_audio=False)
    with open(clip_video, "rb") as f:
        r2 = client.post(f"/tracks/{track_id}/clips", files={"file": ("pip.mp4", f, "video/mp4")}, headers=headers)
    clip_id = r2.json()["id"]

    r3 = client.patch(f"/clips/{clip_id}", json={"pip_x": 0.05, "pip_y": 0.05, "pip_width": 0.5, "pip_height": 0.5}, headers=headers)
    assert r3.status_code == 200
    assert r3.json()["pip_width"] == 0.5


def test_delete_clip(client, register_and_login, tmp_path):
    import os
    from app.models import User
    from app.database import SessionLocal

    headers, _tokens, email = register_and_login()
    db = SessionLocal()
    user = db.query(User).filter(User.email == email).first()
    _video_id, moment_id = _seed_moment(db, user)
    db.close()

    r = client.post(f"/moments/{moment_id}/tracks", json={"type": "audio"}, headers=headers)
    track_id = r.json()["id"]
    audio_path = _make_test_audio(tmp_path, "m.mp3", 3)
    with open(audio_path, "rb") as f:
        r2 = client.post(f"/tracks/{track_id}/clips", files={"file": ("m.mp3", f, "audio/mpeg")}, headers=headers)
    clip_id = r2.json()["id"]
    file_path = r2.json()["file_path"]

    r3 = client.delete(f"/clips/{clip_id}", headers=headers)
    assert r3.status_code == 200
    assert not os.path.exists(file_path)


def test_clip_operations_require_ownership(client, register_and_login, tmp_path):
    from app.models import User
    from app.database import SessionLocal

    headers_a, _tokens_a, email_a = register_and_login()
    headers_b, _tokens_b, _email_b = register_and_login()

    db = SessionLocal()
    user_a = db.query(User).filter(User.email == email_a).first()
    _video_id, moment_id = _seed_moment(db, user_a)
    db.close()

    r = client.post(f"/moments/{moment_id}/tracks", json={"type": "audio"}, headers=headers_a)
    track_id = r.json()["id"]
    audio_path = _make_test_audio(tmp_path, "m.mp3", 3)
    with open(audio_path, "rb") as f:
        r2 = client.post(f"/tracks/{track_id}/clips", files={"file": ("m.mp3", f, "audio/mpeg")}, headers=headers_a)
    clip_id = r2.json()["id"]

    r3 = client.patch(f"/clips/{clip_id}", json={"volume": 0.1}, headers=headers_b)
    assert r3.status_code == 404

    r4 = client.delete(f"/clips/{clip_id}", headers=headers_b)
    assert r4.status_code == 404


# ---------- Момент отдаёт дорожки в GET ----------

def test_moment_includes_tracks_in_response(client, register_and_login, tmp_path):
    from app.models import User
    from app.database import SessionLocal

    headers, _tokens, email = register_and_login()
    db = SessionLocal()
    user = db.query(User).filter(User.email == email).first()
    video_id, moment_id = _seed_moment(db, user)
    db.close()

    r = client.post(f"/moments/{moment_id}/tracks", json={"type": "audio", "name": "Фон"}, headers=headers)
    track_id = r.json()["id"]
    audio_path = _make_test_audio(tmp_path, "m.mp3", 3)
    with open(audio_path, "rb") as f:
        client.post(f"/tracks/{track_id}/clips", files={"file": ("m.mp3", f, "audio/mpeg")}, headers=headers)

    r2 = client.get(f"/videos/{video_id}", headers=headers)
    moment_data = r2.json()["moments"][0]
    assert len(moment_data["tracks"]) == 1
    assert moment_data["tracks"][0]["name"] == "Фон"
    assert len(moment_data["tracks"][0]["clips"]) == 1


# ---------- Реальный многодорожечный рендер (не мок — настоящий ffmpeg) ----------

def _spectral_peak(data, sr, center_sample, target_freq, tolerance=15):
    """Амплитуда заданной частоты в окрестности сэмпла center_sample."""
    import numpy as np
    chunk = data[center_sample - 4096:center_sample + 4096].astype(float)
    if len(chunk) < 8192:
        return 0.0
    spectrum = np.abs(np.fft.rfft(chunk))
    freqs = np.fft.rfftfreq(len(chunk), 1 / sr)
    mask = (freqs > target_freq - tolerance) & (freqs < target_freq + tolerance)
    return spectrum[mask].max() if mask.any() else 0.0


def test_render_with_multiple_video_and_audio_tracks(register_and_login, tmp_path):
    """
    Сквозной тест: 1 базовое видео (звук 440Hz) + 1 видео-дорожка (PIP,
    видна только в окне 1-4с) + 2 аудио-дорожки (880Hz играет 0-5с, 1320Hz
    играет только с 2-5с). Проверяет РЕАЛЬНЫМ ffprobe/спектральным анализом
    (не просто "рендер не упал"):
      - итоговая длительность равна длительности момента;
      - PIP-видео видно внутри своего временного окна и исчезает после него;
      - все три звуковых источника корректно смешиваются со сдвигом по времени.
    """
    import subprocess
    import wave
    import numpy as np
    from app.models import User, Video, Moment, Track, Clip, VideoStatus, MomentStatus, TrackType
    from app.database import SessionLocal
    from app.tasks import render_moment_task

    base = tmp_path / "base.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=size=640x480:duration=6:rate=15",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=6",
         "-c:v", "libx264", "-c:a", "aac", "-shortest", str(base)],
        capture_output=True, check=True,
    )
    audio1 = tmp_path / "a1.mp3"
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=880:duration=6", "-c:a", "mp3", str(audio1)], capture_output=True, check=True)
    audio2 = tmp_path / "a2.mp3"
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=1320:duration=6", "-c:a", "mp3", str(audio2)], capture_output=True, check=True)
    pip_video = tmp_path / "pip.mp4"
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=lime:size=320x240:duration=6", "-c:v", "libx264", str(pip_video)], capture_output=True, check=True)

    _headers, _tokens, email = register_and_login()
    db = SessionLocal()
    user = db.query(User).filter(User.email == email).first()
    video = Video(owner_id=user.id, filename="e.mp4", filepath=str(base), status=VideoStatus.READY)
    db.add(video); db.flush()
    moment = Moment(video_id=video.id, start=0.0, end=5.0, status=MomentStatus.APPROVED)
    db.add(moment); db.flush()

    video_track = Track(moment_id=moment.id, type=TrackType.VIDEO, order_index=0)
    db.add(video_track); db.flush()
    db.add(Clip(
        track_id=video_track.id, file_path=str(pip_video), source_duration=6.0,
        trim_start=0.0, trim_end=3.0, position_start=1.0, position_end=4.0,
        pip_x=0.05, pip_y=0.05, pip_width=0.3, pip_height=0.3,
    ))

    audio_track1 = Track(moment_id=moment.id, type=TrackType.AUDIO, order_index=1)
    db.add(audio_track1); db.flush()
    db.add(Clip(track_id=audio_track1.id, file_path=str(audio1), source_duration=6.0, trim_start=0.0, trim_end=5.0, position_start=0.0, position_end=5.0, volume=0.4))

    audio_track2 = Track(moment_id=moment.id, type=TrackType.AUDIO, order_index=2)
    db.add(audio_track2); db.flush()
    db.add(Clip(track_id=audio_track2.id, file_path=str(audio2), source_duration=6.0, trim_start=0.0, trim_end=3.0, position_start=2.0, position_end=5.0, volume=0.3))

    moment_id = moment.id
    db.commit()
    db.close()

    render_moment_task.run(moment_id)

    db = SessionLocal()
    m = db.query(Moment).filter(Moment.id == moment_id).first()
    assert m.status == MomentStatus.RENDERED
    output_path = m.output_path
    db.close()

    # 1. Длительность равна длительности момента (5с), несмотря на 6-секундные исходники
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", output_path],
        capture_output=True, text=True,
    )
    assert abs(float(result.stdout.strip()) - 5.0) < 0.3

    # 2. PIP виден в кадре на 2-й секунде (внутри окна 1-4с) — проверяем
    # наличие ярко-зелёного пикселя в углу, где должен быть PIP
    frame_path = tmp_path / "frame_2s.png"
    subprocess.run(["ffmpeg", "-y", "-ss", "2", "-i", output_path, "-frames:v", "1", str(frame_path)], capture_output=True, check=True)
    from PIL import Image
    img = Image.open(frame_path).convert("RGB")
    # pip_x=0.05,pip_y=0.05 на кадре 1080x1920 — точка внутри PIP-прямоугольника
    sample_pixel = img.getpixel((200, 200))
    r, g, b = sample_pixel
    assert g > 150 and r < 100 and b < 100, f"Ожидался зелёный PIP-пиксель, получено {sample_pixel}"

    # 3. PIP-а больше НЕТ в кадре после его окна (после 4-й секунды)
    frame_path_after = tmp_path / "frame_4_7s.png"
    subprocess.run(["ffmpeg", "-y", "-ss", "4.7", "-i", output_path, "-frames:v", "1", str(frame_path_after)], capture_output=True, check=True)
    img_after = Image.open(frame_path_after).convert("RGB")
    sample_after = img_after.getpixel((200, 200))
    assert sample_after != sample_pixel or sample_after[1] < 150, "PIP не должен быть виден после своего временного окна"

    # 4. Спектральный анализ звука: на 1-й секунде трек2 (1320Hz) ещё не звучит,
    # на 3-й секунде звучат уже все три источника одновременно
    wav_path = tmp_path / "out_audio.wav"
    subprocess.run(["ffmpeg", "-y", "-i", output_path, "-vn", "-acodec", "pcm_s16le", str(wav_path)], capture_output=True, check=True)
    wf = wave.open(str(wav_path), "rb")
    sr = wf.getframerate()
    data = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16)
    if wf.getnchannels() == 2:
        data = data[::2]

    p1320_at_1s = _spectral_peak(data, sr, int(1.0 * sr), 1320)
    p440_at_3s = _spectral_peak(data, sr, int(3.0 * sr), 440)
    p880_at_3s = _spectral_peak(data, sr, int(3.0 * sr), 880)
    p1320_at_3s = _spectral_peak(data, sr, int(3.0 * sr), 1320)

    assert p1320_at_1s < 100_000, "Трек 1320Hz не должен звучать на 1-й секунде (начинается со 2-й)"
    assert p440_at_3s > 500_000, "Оригинальный звук (440Hz) должен звучать на 3-й секунде"
    assert p880_at_3s > 500_000, "Аудио-трек 1 (880Hz) должен звучать на 3-й секунде"
    assert p1320_at_3s > 500_000, "Аудио-трек 2 (1320Hz) должен звучать на 3-й секунде"
