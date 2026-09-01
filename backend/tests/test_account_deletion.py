def test_delete_account_requires_correct_password(client, register_and_login):
    headers, _tokens, _email = register_and_login(password="correctpass123")

    r = client.request("DELETE", "/auth/me", json={"current_password": "wrongpass"}, headers=headers)
    assert r.status_code == 400


def test_delete_account_requires_auth(client):
    r = client.request("DELETE", "/auth/me", json={"current_password": "whatever"})
    assert r.status_code == 401


def test_delete_own_account_removes_user(client, register_and_login):
    from app.models import User
    from app.database import SessionLocal

    headers, _tokens, email = register_and_login(password="correctpass123")

    r = client.request("DELETE", "/auth/me", json={"current_password": "correctpass123"}, headers=headers)
    assert r.status_code == 200

    db = SessionLocal()
    user = db.query(User).filter(User.email == email).first()
    assert user is None
    db.close()


def test_deleted_account_cannot_login_again(client, register_and_login):
    headers, _tokens, email = register_and_login(password="correctpass123")
    client.request("DELETE", "/auth/me", json={"current_password": "correctpass123"}, headers=headers)

    r = client.post("/auth/login", json={"email": email, "password": "correctpass123"})
    assert r.status_code == 401


def test_delete_account_cascades_through_full_data_tree(client, register_and_login, tmp_path):
    """
    Реальная проверка того самого бага, который был найден и исправлен:
    User.videos не имел cascade="all, delete-orphan". Строим ПОЛНОЕ дерево
    данных — видео, момент, субтитр, дорожку, клип, соцаккаунт, черновик
    хештегов, проект — и проверяем, что удаление пользователя не падает
    с ошибкой внешнего ключа (SQLite теперь реально проверяет FK, как
    Postgres в проде — см. app/database.py) и не оставляет ни одной
    осиротевшей строки.
    """
    import subprocess
    from app.models import (
        User, Video, Moment, Subtitle, Track, Clip, SocialAccount,
        HashtagDraft, Project, VideoStatus, MomentStatus, TrackType, Platform,
    )
    from app.database import SessionLocal

    real_video = tmp_path / "real.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=size=320x240:duration=5:rate=10", "-c:v", "libx264", str(real_video)],
        capture_output=True, check=True,
    )
    audio_file = tmp_path / "audio.mp3"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=3", "-c:a", "mp3", str(audio_file)],
        capture_output=True, check=True,
    )

    headers, _tokens, email = register_and_login(password="correctpass123")

    db = SessionLocal()
    user = db.query(User).filter(User.email == email).first()

    video = Video(owner_id=user.id, filename="e.mp4", filepath=str(real_video), status=VideoStatus.READY)
    db.add(video); db.flush()

    moment = Moment(video_id=video.id, start=0.0, end=4.0, status=MomentStatus.PENDING)
    db.add(moment); db.flush()

    db.add(Subtitle(moment_id=moment.id, start=0.0, end=1.0, text="Реплика", order_index=0))

    track = Track(moment_id=moment.id, type=TrackType.AUDIO, order_index=0)
    db.add(track); db.flush()
    db.add(Clip(track_id=track.id, file_path=str(audio_file), source_duration=3.0, position_start=0.0, position_end=3.0, trim_start=0.0, trim_end=3.0))

    social_account = SocialAccount(owner_id=user.id, platform=Platform.YOUTUBE, platform_account_id="chan1", access_token="fake")
    db.add(social_account)

    db.add(HashtagDraft(user_id=user.id, name="Юмор", hashtags="#юмор"))
    db.add(Project(user_id=user.id, video_id=video.id, title="Мой проект"))

    db.commit()
    user_id, video_id, moment_id, track_id = user.id, video.id, moment.id, track.id
    db.close()

    # Удаляем аккаунт через реальный API-запрос
    r = client.request("DELETE", "/auth/me", json={"current_password": "correctpass123"}, headers=headers)
    assert r.status_code == 200, r.text

    # Проверяем КАЖДЫЙ уровень дерева — ничего не должно остаться сиротой
    db = SessionLocal()
    assert db.query(User).filter(User.id == user_id).first() is None
    assert db.query(Video).filter(Video.id == video_id).first() is None
    assert db.query(Moment).filter(Moment.id == moment_id).first() is None
    assert db.query(Subtitle).filter(Subtitle.moment_id == moment_id).first() is None
    assert db.query(Track).filter(Track.id == track_id).first() is None
    assert db.query(Clip).filter(Clip.track_id == track_id).first() is None
    assert db.query(SocialAccount).filter(SocialAccount.owner_id == user_id).first() is None
    assert db.query(HashtagDraft).filter(HashtagDraft.user_id == user_id).first() is None
    assert db.query(Project).filter(Project.user_id == user_id).first() is None
    db.close()
