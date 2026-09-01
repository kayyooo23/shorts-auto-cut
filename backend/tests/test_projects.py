def _seed_video_with_moment(db, user):
    from app.models import Video, Moment, VideoStatus, MomentStatus

    video = Video(owner_id=user.id, filename="episode_04.mp4", filepath="/tmp/x.mp4", status=VideoStatus.READY)
    db.add(video); db.flush()
    moment = Moment(video_id=video.id, start=0, end=10, status=MomentStatus.PENDING, hook_line="Момент с признанием")
    db.add(moment); db.commit()
    return video.id, moment.id


def test_create_project_for_whole_video(client, register_and_login):
    from app.models import User
    from app.database import SessionLocal

    headers, _tokens, email = register_and_login()
    db = SessionLocal()
    user = db.query(User).filter(User.email == email).first()
    video_id, _moment_id = _seed_video_with_moment(db, user)
    db.close()

    r = client.post(
        "/projects",
        json={"video_id": video_id, "title": "Разбор 4 серии", "note": "Вернуться после работы, доделать субтитры"},
        headers=headers,
    )
    assert r.status_code == 201
    data = r.json()
    assert data["title"] == "Разбор 4 серии"
    assert data["note"] == "Вернуться после работы, доделать субтитры"
    assert data["moment_id"] is None
    assert data["video"]["filename"] == "episode_04.mp4"


def test_create_project_for_specific_moment(client, register_and_login):
    from app.models import User
    from app.database import SessionLocal

    headers, _tokens, email = register_and_login()
    db = SessionLocal()
    user = db.query(User).filter(User.email == email).first()
    video_id, moment_id = _seed_video_with_moment(db, user)
    db.close()

    r = client.post("/projects", json={"video_id": video_id, "moment_id": moment_id}, headers=headers)
    assert r.status_code == 201
    data = r.json()
    assert data["moment_id"] == moment_id
    assert data["moment"]["hook_line"] == "Момент с признанием"


def test_create_project_rejects_other_users_video(client, register_and_login):
    from app.models import User
    from app.database import SessionLocal

    headers_a, _tokens_a, _email_a = register_and_login()
    headers_b, _tokens_b, email_b = register_and_login()

    db = SessionLocal()
    user_b = db.query(User).filter(User.email == email_b).first()
    video_id, _moment_id = _seed_video_with_moment(db, user_b)
    db.close()

    r = client.post("/projects", json={"video_id": video_id}, headers=headers_a)
    assert r.status_code == 404


def test_create_project_rejects_moment_from_different_video(client, register_and_login):
    from app.models import User, Video, Moment, VideoStatus, MomentStatus
    from app.database import SessionLocal

    headers, _tokens, email = register_and_login()
    db = SessionLocal()
    user = db.query(User).filter(User.email == email).first()

    video1_id, _ = _seed_video_with_moment(db, user)
    video2 = Video(owner_id=user.id, filename="other.mp4", filepath="/tmp/y.mp4", status=VideoStatus.READY)
    db.add(video2); db.flush()
    moment2 = Moment(video_id=video2.id, start=0, end=5, status=MomentStatus.PENDING)
    db.add(moment2); db.commit()
    moment2_id = moment2.id
    db.close()

    # момент из video2, но video_id указываем от video1 — несоответствие
    r = client.post("/projects", json={"video_id": video1_id, "moment_id": moment2_id}, headers=headers)
    assert r.status_code == 404


def test_list_projects_ordered_by_recently_updated(client, register_and_login):
    from app.models import User
    from app.database import SessionLocal

    headers, _tokens, email = register_and_login()
    db = SessionLocal()
    user = db.query(User).filter(User.email == email).first()
    video_id, _moment_id = _seed_video_with_moment(db, user)
    db.close()

    r1 = client.post("/projects", json={"video_id": video_id, "title": "Первый"}, headers=headers)
    r2 = client.post("/projects", json={"video_id": video_id, "title": "Второй"}, headers=headers)

    r = client.get("/projects", headers=headers)
    assert r.status_code == 200
    titles = [p["title"] for p in r.json()]
    assert titles[0] == "Второй"  # создан позже — должен быть первым

    # обновление заметки у первого поднимает его наверх по updated_at
    client.patch(f"/projects/{r1.json()['id']}", json={"note": "новая заметка"}, headers=headers)
    r_after = client.get("/projects", headers=headers)
    assert r_after.json()[0]["title"] == "Первый"


def test_projects_isolated_between_users(client, register_and_login):
    from app.models import User
    from app.database import SessionLocal

    headers_a, _tokens_a, email_a = register_and_login()
    headers_b, _tokens_b, _email_b = register_and_login()

    db = SessionLocal()
    user_a = db.query(User).filter(User.email == email_a).first()
    video_id, _moment_id = _seed_video_with_moment(db, user_a)
    db.close()

    client.post("/projects", json={"video_id": video_id, "title": "Проект A"}, headers=headers_a)

    r_b = client.get("/projects", headers=headers_b)
    assert r_b.json() == []


def test_update_project_note(client, register_and_login):
    from app.models import User
    from app.database import SessionLocal

    headers, _tokens, email = register_and_login()
    db = SessionLocal()
    user = db.query(User).filter(User.email == email).first()
    video_id, _moment_id = _seed_video_with_moment(db, user)
    db.close()

    r = client.post("/projects", json={"video_id": video_id}, headers=headers)
    project_id = r.json()["id"]

    r2 = client.patch(f"/projects/{project_id}", json={"note": "обновлённая заметка себе"}, headers=headers)
    assert r2.status_code == 200
    assert r2.json()["note"] == "обновлённая заметка себе"


def test_cannot_update_other_users_project(client, register_and_login):
    from app.models import User
    from app.database import SessionLocal

    headers_a, _tokens_a, email_a = register_and_login()
    headers_b, _tokens_b, _email_b = register_and_login()

    db = SessionLocal()
    user_a = db.query(User).filter(User.email == email_a).first()
    video_id, _moment_id = _seed_video_with_moment(db, user_a)
    db.close()

    r = client.post("/projects", json={"video_id": video_id}, headers=headers_a)
    project_id = r.json()["id"]

    r2 = client.patch(f"/projects/{project_id}", json={"note": "чужая правка"}, headers=headers_b)
    assert r2.status_code == 404


def test_delete_project(client, register_and_login):
    from app.models import User
    from app.database import SessionLocal

    headers, _tokens, email = register_and_login()
    db = SessionLocal()
    user = db.query(User).filter(User.email == email).first()
    video_id, _moment_id = _seed_video_with_moment(db, user)
    db.close()

    r = client.post("/projects", json={"video_id": video_id}, headers=headers)
    project_id = r.json()["id"]

    r2 = client.delete(f"/projects/{project_id}", headers=headers)
    assert r2.status_code == 200

    r3 = client.get("/projects", headers=headers)
    assert r3.json() == []


def test_get_single_project(client, register_and_login):
    from app.models import User
    from app.database import SessionLocal

    headers, _tokens, email = register_and_login()
    db = SessionLocal()
    user = db.query(User).filter(User.email == email).first()
    video_id, _moment_id = _seed_video_with_moment(db, user)
    db.close()

    r = client.post("/projects", json={"video_id": video_id, "note": "заметка"}, headers=headers)
    project_id = r.json()["id"]

    r2 = client.get(f"/projects/{project_id}", headers=headers)
    assert r2.status_code == 200
    assert r2.json()["note"] == "заметка"
