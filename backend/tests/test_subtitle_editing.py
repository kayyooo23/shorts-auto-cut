def _seed_moment_with_subtitles(db, user):
    from app.models import Video, Moment, Subtitle, VideoStatus, MomentStatus

    video = Video(owner_id=user.id, filename="e.mp4", filepath="/tmp/x.mp4", status=VideoStatus.READY)
    db.add(video); db.flush()
    moment = Moment(video_id=video.id, start=10.0, end=40.0, status=MomentStatus.PENDING)
    db.add(moment); db.flush()
    db.add(Subtitle(moment_id=moment.id, start=0.0, end=2.0, text="Первая", order_index=0))
    db.add(Subtitle(moment_id=moment.id, start=5.0, end=7.0, text="Вторая", order_index=1))
    db.commit()
    return video.id, moment.id


# ---------- Создание субтитров ----------

def test_create_subtitle(client, register_and_login):
    from app.models import User
    from app.database import SessionLocal

    headers, _tokens, email = register_and_login()
    db = SessionLocal()
    user = db.query(User).filter(User.email == email).first()
    _video_id, moment_id = _seed_moment_with_subtitles(db, user)
    db.close()

    r = client.post(
        f"/moments/{moment_id}/subtitles",
        json={"start": 2.5, "end": 4.5, "text": "Новая реплика"},
        headers=headers,
    )
    assert r.status_code == 201
    assert r.json()["text"] == "Новая реплика"


def test_create_subtitle_inserts_at_correct_chronological_position(client, register_and_login):
    """Новая реплика между существующими должна получить order_index,
    отражающий её место по времени, а существующие после неё — сдвинуться."""
    from app.models import User, Subtitle
    from app.database import SessionLocal

    headers, _tokens, email = register_and_login()
    db = SessionLocal()
    user = db.query(User).filter(User.email == email).first()
    _video_id, moment_id = _seed_moment_with_subtitles(db, user)
    db.close()

    # существующие: [0.0-2.0 idx0, 5.0-7.0 idx1]; вставляем 2.5-4.5 -> должна встать idx1
    r = client.post(
        f"/moments/{moment_id}/subtitles",
        json={"start": 2.5, "end": 4.5, "text": "Между"},
        headers=headers,
    )
    assert r.json()["order_index"] == 1

    db = SessionLocal()
    subs = sorted(db.query(Subtitle).filter(Subtitle.moment_id == moment_id).all(), key=lambda s: s.order_index)
    texts_in_order = [s.text for s in subs]
    assert texts_in_order == ["Первая", "Между", "Вторая"]
    db.close()


def test_create_subtitle_requires_ownership(client, register_and_login):
    from app.models import User
    from app.database import SessionLocal

    _headers_a, _tokens_a, email_a = register_and_login()
    headers_b, _tokens_b, _email_b = register_and_login()

    db = SessionLocal()
    user_a = db.query(User).filter(User.email == email_a).first()
    _video_id, moment_id = _seed_moment_with_subtitles(db, user_a)
    db.close()

    r = client.post(
        f"/moments/{moment_id}/subtitles",
        json={"start": 0, "end": 1, "text": "x"},
        headers=headers_b,
    )
    assert r.status_code == 404


# ---------- Удаление субтитров ----------

def test_delete_subtitle(client, register_and_login):
    from app.models import User
    from app.database import SessionLocal

    headers, _tokens, email = register_and_login()
    db = SessionLocal()
    user = db.query(User).filter(User.email == email).first()
    _video_id, moment_id = _seed_moment_with_subtitles(db, user)
    db.close()

    r = client.get(f"/videos/{_video_id}", headers=headers)
    subtitle_id = r.json()["moments"][0]["subtitles"][0]["id"]

    r2 = client.delete(f"/subtitles/{subtitle_id}", headers=headers)
    assert r2.status_code == 200

    r3 = client.get(f"/videos/{_video_id}", headers=headers)
    remaining = r3.json()["moments"][0]["subtitles"]
    assert len(remaining) == 1
    assert remaining[0]["text"] == "Вторая"


def test_delete_other_users_subtitle_rejected(client, register_and_login):
    from app.models import User
    from app.database import SessionLocal

    headers_a, _tokens_a, email_a = register_and_login()
    headers_b, _tokens_b, _email_b = register_and_login()

    db = SessionLocal()
    user_a = db.query(User).filter(User.email == email_a).first()
    video_id, _moment_id = _seed_moment_with_subtitles(db, user_a)
    db.close()

    r = client.get(f"/videos/{video_id}", headers=headers_a)
    subtitle_id = r.json()["moments"][0]["subtitles"][0]["id"]

    r2 = client.delete(f"/subtitles/{subtitle_id}", headers=headers_b)
    assert r2.status_code == 404


# ---------- Правка таймкодов момента ----------

def test_update_moment_start_end(client, register_and_login):
    from app.models import User
    from app.database import SessionLocal

    headers, _tokens, email = register_and_login()
    db = SessionLocal()
    user = db.query(User).filter(User.email == email).first()
    _video_id, moment_id = _seed_moment_with_subtitles(db, user)
    db.close()

    r = client.patch(f"/moments/{moment_id}", json={"start": 12.0, "end": 38.0}, headers=headers)
    assert r.status_code == 200
    assert r.json()["start"] == 12.0
    assert r.json()["end"] == 38.0
