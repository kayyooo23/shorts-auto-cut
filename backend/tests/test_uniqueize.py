"""
Тесты уникализации гоняются реальным ffmpeg — это единственный надёжный
способ убедиться, что цепочка фильтров (rotate -> crop -> scale -> hflip
-> eq -> noise -> setpts/atempo/rubberband) реально валидна и не ломается
на конкретных версиях ffmpeg/libavfilter.
"""

import hashlib
import subprocess

import pytest

from pipeline.uniqueize import apply_uniqueization, UniqueizeError


@pytest.fixture(scope="module")
def source_video(tmp_path_factory):
    path = tmp_path_factory.mktemp("uniqueize_src") / "source.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=size=640x480:duration=5:rate=15",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=5",
         "-c:v", "libx264", "-c:a", "aac", "-shortest", str(path)],
        capture_output=True, check=True,
    )
    return str(path)


def _md5(path: str) -> str:
    return hashlib.md5(open(path, "rb").read()).hexdigest()


def test_uniqueization_produces_valid_playable_file(tmp_path, source_video):
    output_path = str(tmp_path / "out.mp4")
    params = apply_uniqueization(source_video, output_path, seed=1)

    assert isinstance(params, dict)
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", output_path],
        capture_output=True, text=True,
    )
    duration = float(result.stdout.strip())
    assert duration > 0


def test_same_seed_is_deterministic(tmp_path, source_video):
    out1 = str(tmp_path / "a.mp4")
    out2 = str(tmp_path / "b.mp4")
    apply_uniqueization(source_video, out1, seed=42)
    apply_uniqueization(source_video, out2, seed=42)
    assert _md5(out1) == _md5(out2)


def test_different_seeds_produce_different_files(tmp_path, source_video):
    out1 = str(tmp_path / "a.mp4")
    out2 = str(tmp_path / "b.mp4")
    apply_uniqueization(source_video, out1, seed=1)
    apply_uniqueization(source_video, out2, seed=2)
    assert _md5(out1) != _md5(out2)


def test_output_differs_from_source(tmp_path, source_video):
    output_path = str(tmp_path / "out.mp4")
    apply_uniqueization(source_video, output_path, seed=7)
    assert _md5(output_path) != _md5(source_video)


def test_random_calls_without_seed_are_not_identical(tmp_path, source_video):
    """Без явного seed каждый вызов должен использовать новые случайные
    параметры — иначе вся фича не имеет смысла для нескольких аккаунтов."""
    out1 = str(tmp_path / "a.mp4")
    out2 = str(tmp_path / "b.mp4")
    apply_uniqueization(source_video, out1)
    apply_uniqueization(source_video, out2)
    assert _md5(out1) != _md5(out2)


def test_invalid_source_raises(tmp_path):
    with pytest.raises(UniqueizeError):
        apply_uniqueization("/nonexistent/video.mp4", str(tmp_path / "out.mp4"))


def test_metadata_stripped(tmp_path, source_video):
    """strip_metadata=True (по умолчанию) должен убирать метаданные
    контейнера — проверяем реальным ffprobe, а не полагаемся на факт
    отсутствия ошибки."""
    # добавляем в исходник заметные метаданные, чтобы было что проверять
    tagged_source = str(tmp_path / "tagged.mp4")
    subprocess.run(
        ["ffmpeg", "-y", "-i", source_video, "-c", "copy",
         "-metadata", "comment=SECRET_MARKER_12345", tagged_source],
        capture_output=True, check=True,
    )

    output_path = str(tmp_path / "out.mp4")
    apply_uniqueization(tagged_source, output_path, seed=3, strip_metadata=True)

    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format_tags=comment",
         "-of", "default=noprint_wrappers=1:nokey=1", output_path],
        capture_output=True, text=True,
    )
    assert "SECRET_MARKER_12345" not in result.stdout


# ---------- Интеграция с публикацией ----------

def test_publish_target_uses_uniqueized_copy_when_requested(register_and_login, monkeypatch, source_video):
    from app.models import User, Platform, PublishTarget, PublishStatus, Video, Moment, SocialAccount, VideoStatus, MomentStatus
    from app.database import SessionLocal
    from app.tasks import publish_target
    from app.publishers.base import UploadResult
    import app.publishers.youtube as yt_module

    captured_paths = []
    monkeypatch.setattr(
        yt_module.YouTubePublisher, "upload",
        lambda self, video_path, title, description: (captured_paths.append(video_path) or UploadResult(remote_id="x", remote_url="https://youtube.com/shorts/x")),
    )

    _headers, _tokens, email = register_and_login()
    db = SessionLocal()
    user = db.query(User).filter(User.email == email).first()
    video = Video(owner_id=user.id, filename="e.mp4", filepath=source_video, status=VideoStatus.READY)
    db.add(video); db.flush()
    moment = Moment(video_id=video.id, start=0, end=3, status=MomentStatus.RENDERED, output_path=source_video)
    db.add(moment); db.flush()
    account = SocialAccount(owner_id=user.id, platform=Platform.YOUTUBE, platform_account_id="acc1", access_token="x")
    db.add(account); db.flush()
    target = PublishTarget(
        moment_id=moment.id, social_account_id=account.id, platform=Platform.YOUTUBE,
        status=PublishStatus.QUEUED, uniqueize=True,
    )
    db.add(target); db.commit()
    target_id = target.id
    db.close()

    publish_target.run(target_id)

    assert len(captured_paths) == 1
    uploaded_path = captured_paths[0]
    assert uploaded_path != source_video  # загружен НЕ исходный рендер, а уникализированная копия
    assert "_unique" in uploaded_path

    import os
    # временный файл должен быть удалён после публикации (успешной или нет)
    assert not os.path.exists(uploaded_path)


def test_publish_target_uses_original_when_not_requested(register_and_login, monkeypatch, source_video):
    from app.models import User, Platform, PublishTarget, PublishStatus, Video, Moment, SocialAccount, VideoStatus, MomentStatus
    from app.database import SessionLocal
    from app.tasks import publish_target
    from app.publishers.base import UploadResult
    import app.publishers.youtube as yt_module

    captured_paths = []
    monkeypatch.setattr(
        yt_module.YouTubePublisher, "upload",
        lambda self, video_path, title, description: (captured_paths.append(video_path) or UploadResult(remote_id="x", remote_url="https://youtube.com/shorts/x")),
    )

    _headers, _tokens, email = register_and_login()
    db = SessionLocal()
    user = db.query(User).filter(User.email == email).first()
    video = Video(owner_id=user.id, filename="e.mp4", filepath=source_video, status=VideoStatus.READY)
    db.add(video); db.flush()
    moment = Moment(video_id=video.id, start=0, end=3, status=MomentStatus.RENDERED, output_path=source_video)
    db.add(moment); db.flush()
    account = SocialAccount(owner_id=user.id, platform=Platform.YOUTUBE, platform_account_id="acc1", access_token="x")
    db.add(account); db.flush()
    target = PublishTarget(
        moment_id=moment.id, social_account_id=account.id, platform=Platform.YOUTUBE,
        status=PublishStatus.QUEUED, uniqueize=False,
    )
    db.add(target); db.commit()
    target_id = target.id
    db.close()

    publish_target.run(target_id)

    assert captured_paths == [source_video]  # загружен исходный рендер как есть


def test_publish_endpoint_accepts_uniqueize_flag(client, register_and_login, source_video):
    from app.models import User, Platform, Video, Moment, SocialAccount, VideoStatus, MomentStatus
    from app.database import SessionLocal

    headers, _tokens, email = register_and_login()
    db = SessionLocal()
    user = db.query(User).filter(User.email == email).first()
    video = Video(owner_id=user.id, filename="e.mp4", filepath=source_video, status=VideoStatus.READY)
    db.add(video); db.flush()
    moment = Moment(video_id=video.id, start=0, end=3, status=MomentStatus.RENDERED, output_path=source_video)
    db.add(moment); db.flush()
    account = SocialAccount(owner_id=user.id, platform=Platform.YOUTUBE, platform_account_id="acc1", access_token="x")
    db.add(account); db.flush()
    moment_id, account_id = moment.id, account.id
    db.commit()
    db.close()

    r = client.post(
        f"/moments/{moment_id}/publish",
        json={"social_account_ids": [account_id], "uniqueize": True},
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json()[0]["uniqueize"] is True


# ---------- Дневная квота уникализации (считается ЗА НАРЕЗКУ, не за аккаунт) ----------

def _setup_moment_with_accounts(db, user, n_accounts, source_video):
    """Один момент + N подключённых YouTube-аккаунтов — чтобы проверить,
    что квота не растёт от количества выбранных аккаунтов в одном вызове."""
    from app.models import Video, Moment, SocialAccount, VideoStatus, MomentStatus, Platform

    video = Video(owner_id=user.id, filename="e.mp4", filepath=source_video, status=VideoStatus.READY)
    db.add(video); db.flush()
    moment = Moment(video_id=video.id, start=0, end=3, status=MomentStatus.RENDERED, output_path=source_video)
    db.add(moment); db.flush()

    account_ids = []
    for i in range(n_accounts):
        acc = SocialAccount(owner_id=user.id, platform=Platform.YOUTUBE, platform_account_id=f"acc{i}", access_token="x")
        db.add(acc); db.flush()
        account_ids.append(acc.id)

    db.commit()
    return moment.id, account_ids


def test_free_tier_uniqueize_daily_limit(client, register_and_login, source_video):
    from app.models import User
    from app.database import SessionLocal

    headers, _tokens, email = register_and_login()
    db = SessionLocal()
    user = db.query(User).filter(User.email == email).first()

    # free = 2 бесплатных уникализации в день — используем обе
    for _ in range(2):
        moment_id, account_ids = _setup_moment_with_accounts(db, user, 1, source_video)
        r = client.post(
            f"/moments/{moment_id}/publish",
            json={"social_account_ids": account_ids, "uniqueize": True},
            headers=headers,
        )
        assert r.status_code == 200, r.text

    # 3-я — квота исчерпана
    moment_id, account_ids = _setup_moment_with_accounts(db, user, 1, source_video)
    r = client.post(
        f"/moments/{moment_id}/publish",
        json={"social_account_ids": account_ids, "uniqueize": True},
        headers=headers,
    )
    assert r.status_code == 402
    db.close()


def test_uniqueize_quota_counts_per_moment_not_per_account(client, register_and_login, source_video):
    """Публикация ОДНОЙ нарезки сразу на 5 аккаунтов должна списать
    ОДНУ единицу дневной квоты, а не пять."""
    from app.models import User
    from app.database import SessionLocal

    headers, _tokens, email = register_and_login()
    db = SessionLocal()
    user = db.query(User).filter(User.email == email).first()

    moment_id, account_ids = _setup_moment_with_accounts(db, user, 5, source_video)
    r = client.post(
        f"/moments/{moment_id}/publish",
        json={"social_account_ids": account_ids, "uniqueize": True},
        headers=headers,
    )
    assert r.status_code == 200
    assert len(r.json()) == 5  # 5 PublishTarget создано

    me = client.get("/billing/me", headers=headers).json()
    assert me["uniqueize_used_today"] == 1  # но квота списалась только один раз
    db.close()


def test_tier2_has_higher_uniqueize_limit(client, register_and_login, source_video):
    from app.models import User
    from app.database import SessionLocal

    headers, _tokens, email = register_and_login()
    client.post("/billing/dev/set-tier", json={"tier": "tier2"}, headers=headers)

    db = SessionLocal()
    user = db.query(User).filter(User.email == email).first()

    for _ in range(5):  # tier2 = 5 бесплатных уникализаций/день
        moment_id, account_ids = _setup_moment_with_accounts(db, user, 1, source_video)
        r = client.post(
            f"/moments/{moment_id}/publish",
            json={"social_account_ids": account_ids, "uniqueize": True},
            headers=headers,
        )
        assert r.status_code == 200, r.text

    moment_id, account_ids = _setup_moment_with_accounts(db, user, 1, source_video)
    r = client.post(
        f"/moments/{moment_id}/publish",
        json={"social_account_ids": account_ids, "uniqueize": True},
        headers=headers,
    )
    assert r.status_code == 402
    db.close()


def test_publishing_without_uniqueize_does_not_consume_quota(client, register_and_login, source_video):
    from app.models import User
    from app.database import SessionLocal

    headers, _tokens, email = register_and_login()
    db = SessionLocal()
    user = db.query(User).filter(User.email == email).first()

    for _ in range(10):  # намного больше дневного лимита free=2
        moment_id, account_ids = _setup_moment_with_accounts(db, user, 1, source_video)
        r = client.post(
            f"/moments/{moment_id}/publish",
            json={"social_account_ids": account_ids, "uniqueize": False},
            headers=headers,
        )
        assert r.status_code == 200

    me = client.get("/billing/me", headers=headers).json()
    assert me["uniqueize_used_today"] == 0
    db.close()


def test_uniqueize_quota_exceeded_creates_no_side_effects(client, register_and_login, source_video):
    """При отказе по квоте не должно оставаться ни PublishTarget, ни
    записи UniqueizeUsage — запрос должен быть полностью атомарным."""
    from app.models import User, PublishTarget
    from app.database import SessionLocal

    headers, _tokens, email = register_and_login()
    db = SessionLocal()
    user = db.query(User).filter(User.email == email).first()

    for _ in range(2):  # исчерпываем free-квоту
        moment_id, account_ids = _setup_moment_with_accounts(db, user, 1, source_video)
        client.post(
            f"/moments/{moment_id}/publish",
            json={"social_account_ids": account_ids, "uniqueize": True},
            headers=headers,
        )

    moment_id, account_ids = _setup_moment_with_accounts(db, user, 1, source_video)
    r = client.post(
        f"/moments/{moment_id}/publish",
        json={"social_account_ids": account_ids, "uniqueize": True},
        headers=headers,
    )
    assert r.status_code == 402

    targets_for_this_moment = db.query(PublishTarget).filter(PublishTarget.moment_id == moment_id).count()
    assert targets_for_this_moment == 0  # ничего не создалось для этого отказанного момента
    db.close()


def test_billing_me_reports_uniqueize_quota(client, register_and_login):
    headers, _tokens, _email = register_and_login()
    me = client.get("/billing/me", headers=headers).json()
    assert me["uniqueize_used_today"] == 0
    assert me["uniqueize_daily_limit"] == 2  # free tier
