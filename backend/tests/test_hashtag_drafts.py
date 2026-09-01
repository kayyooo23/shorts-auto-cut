def _make_video_moment_account(db, user, platform, output_path=None):
    from app.models import Video, Moment, SocialAccount, VideoStatus, MomentStatus

    video = Video(owner_id=user.id, filename="e.mp4", filepath="/tmp/x.mp4", status=VideoStatus.READY)
    db.add(video); db.flush()
    moment = Moment(video_id=video.id, start=0, end=10, status=MomentStatus.APPROVED, output_path=output_path)
    db.add(moment); db.flush()
    account = SocialAccount(owner_id=user.id, platform=platform, platform_account_id="acc1", access_token="x")
    db.add(account); db.flush()
    db.commit()
    return moment.id, account.id


def test_create_and_list_hashtag_drafts(client, register_and_login):
    headers, _tokens, _email = register_and_login()

    r = client.post("/hashtag-drafts", json={"name": "Юмор", "hashtags": "#юмор #смешно #сериал"}, headers=headers)
    assert r.status_code == 201
    assert r.json()["name"] == "Юмор"

    r2 = client.get("/hashtag-drafts", headers=headers)
    assert r2.status_code == 200
    assert len(r2.json()) == 1
    assert r2.json()[0]["hashtags"] == "#юмор #смешно #сериал"


def test_hashtag_drafts_isolated_between_users(client, register_and_login):
    headers_a, _tokens_a, _email_a = register_and_login()
    headers_b, _tokens_b, _email_b = register_and_login()

    client.post("/hashtag-drafts", json={"name": "A's draft", "hashtags": "#a"}, headers=headers_a)

    r = client.get("/hashtag-drafts", headers=headers_b)
    assert r.json() == []


def test_delete_hashtag_draft(client, register_and_login):
    headers, _tokens, _email = register_and_login()
    r = client.post("/hashtag-drafts", json={"name": "Temp", "hashtags": "#temp"}, headers=headers)
    draft_id = r.json()["id"]

    r2 = client.delete(f"/hashtag-drafts/{draft_id}", headers=headers)
    assert r2.status_code == 200

    r3 = client.get("/hashtag-drafts", headers=headers)
    assert r3.json() == []


def test_cannot_delete_other_users_draft(client, register_and_login):
    headers_a, _tokens_a, _email_a = register_and_login()
    headers_b, _tokens_b, _email_b = register_and_login()

    r = client.post("/hashtag-drafts", json={"name": "A's draft", "hashtags": "#a"}, headers=headers_a)
    draft_id = r.json()["id"]

    r2 = client.delete(f"/hashtag-drafts/{draft_id}", headers=headers_b)
    assert r2.status_code == 404


def test_publish_with_hashtags_stores_on_target(client, register_and_login):
    from app.models import User, Platform
    from app.database import SessionLocal

    headers, _tokens, email = register_and_login()
    db = SessionLocal()
    user = db.query(User).filter(User.email == email).first()
    moment_id, account_id = _make_video_moment_account(db, user, Platform.YOUTUBE, output_path="/tmp/rendered.mp4")
    db.close()

    r = client.post(
        f"/moments/{moment_id}/publish",
        json={"social_account_ids": [account_id], "hashtags": "#юмор #сериал"},
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json()[0]["hashtags"] == "#юмор #сериал"


def test_publish_target_task_combines_hashtags_into_description(register_and_login, monkeypatch):
    """Хештеги должны попадать в итоговое описание, отправляемое на платформу,
    даже если поле description пустое."""
    from app.models import User, Platform, PublishTarget, PublishStatus
    from app.database import SessionLocal
    from app.tasks import publish_target
    from app.publishers.base import UploadResult
    import app.publishers.youtube as yt_module

    captured = {}

    def fake_upload(self, video_path, title, description):
        captured["description"] = description
        return UploadResult(remote_id="x", remote_url="https://youtube.com/shorts/x")

    monkeypatch.setattr(yt_module.YouTubePublisher, "upload", fake_upload)

    _headers, _tokens, email = register_and_login()
    db = SessionLocal()
    user = db.query(User).filter(User.email == email).first()
    moment_id, account_id = _make_video_moment_account(db, user, Platform.YOUTUBE, output_path="/tmp/rendered.mp4")

    target = PublishTarget(
        moment_id=moment_id, social_account_id=account_id, platform=Platform.YOUTUBE,
        status=PublishStatus.QUEUED, description="Смешной момент из сериала",
        hashtags="#юмор #сериал #shorts",
    )
    db.add(target); db.commit()
    target_id = target.id
    db.close()

    publish_target.run(target_id)

    assert "Смешной момент из сериала" in captured["description"]
    assert "#юмор #сериал #shorts" in captured["description"]


def test_publish_target_task_uses_hashtags_alone_when_no_description(register_and_login, monkeypatch):
    from app.models import User, Platform, PublishTarget, PublishStatus
    from app.database import SessionLocal
    from app.tasks import publish_target
    from app.publishers.base import UploadResult
    import app.publishers.youtube as yt_module

    captured = {}

    def fake_upload(self, video_path, title, description):
        captured["description"] = description
        return UploadResult(remote_id="x", remote_url="https://youtube.com/shorts/x")

    monkeypatch.setattr(yt_module.YouTubePublisher, "upload", fake_upload)

    _headers, _tokens, email = register_and_login()
    db = SessionLocal()
    user = db.query(User).filter(User.email == email).first()
    moment_id, account_id = _make_video_moment_account(db, user, Platform.YOUTUBE, output_path="/tmp/rendered.mp4")

    target = PublishTarget(
        moment_id=moment_id, social_account_id=account_id, platform=Platform.YOUTUBE,
        status=PublishStatus.QUEUED, description=None, hashtags="#юмор",
    )
    db.add(target); db.commit()
    target_id = target.id
    db.close()

    publish_target.run(target_id)

    assert captured["description"].strip() == "#юмор"
