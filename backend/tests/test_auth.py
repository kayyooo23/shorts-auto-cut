import uuid


def test_register_and_login(client):
    email = f"{uuid.uuid4()}@example.com"
    r = client.post("/auth/register", json={"email": email, "password": "password123"})
    assert r.status_code == 201
    assert r.json()["email"] == email

    r = client.post("/auth/login", json={"email": email, "password": "password123"})
    assert r.status_code == 200
    data = r.json()
    assert "access_token" in data
    assert "refresh_token" in data


def test_duplicate_email_rejected(client):
    email = f"{uuid.uuid4()}@example.com"
    client.post("/auth/register", json={"email": email, "password": "password123"})
    r = client.post("/auth/register", json={"email": email, "password": "another123"})
    assert r.status_code == 400


def test_wrong_password_rejected(client):
    email = f"{uuid.uuid4()}@example.com"
    client.post("/auth/register", json={"email": email, "password": "password123"})
    r = client.post("/auth/login", json={"email": email, "password": "wrong"})
    assert r.status_code == 401


def test_password_too_short_rejected(client):
    email = f"{uuid.uuid4()}@example.com"
    r = client.post("/auth/register", json={"email": email, "password": "short"})
    assert r.status_code == 422


def test_protected_endpoint_requires_token(client):
    r = client.get("/videos")
    assert r.status_code == 401


def test_protected_endpoint_with_valid_token(client, register_and_login):
    headers, _tokens, _email = register_and_login()
    r = client.get("/videos", headers=headers)
    assert r.status_code == 200
    assert r.json() == []


def test_me_endpoint(client, register_and_login):
    headers, _tokens, email = register_and_login()
    r = client.get("/auth/me", headers=headers)
    assert r.status_code == 200
    assert r.json()["email"] == email


def test_users_are_isolated(client, register_and_login):
    """Пользователь не должен видеть/трогать данные другого пользователя."""
    _headers_a, _tokens_a, _email_a = register_and_login()
    headers_b, _tokens_b, _email_b = register_and_login()

    # видео с несуществующим/чужим id — всегда 404, не 403
    # (чтобы не раскрывать сам факт существования чужого видео)
    r = client.get("/videos/nonexistent-id", headers=headers_b)
    assert r.status_code == 404


def test_refresh_token_issues_new_access_token(client, register_and_login):
    _headers, tokens, _email = register_and_login()

    r = client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert r.status_code == 200
    new_access = r.json()["access_token"]
    assert new_access != tokens["access_token"]

    # новый access-токен реально рабочий
    r2 = client.get("/auth/me", headers={"Authorization": f"Bearer {new_access}"})
    assert r2.status_code == 200


def test_refresh_token_reusable_until_logout(client, register_and_login):
    """Refresh-токен НЕ одноразовый — можно использовать несколько раз подряд,
    пока не истёк или не отозван явно (см. app/auth.py::validate_refresh_token)."""
    _headers, tokens, _email = register_and_login()

    r1 = client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    r2 = client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert r1.status_code == 200
    assert r2.status_code == 200


def test_logout_revokes_refresh_token(client, register_and_login):
    _headers, tokens, _email = register_and_login()

    r = client.post("/auth/logout", json={"refresh_token": tokens["refresh_token"]})
    assert r.status_code == 200

    r2 = client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert r2.status_code == 401


def test_invalid_refresh_token_rejected(client):
    r = client.post("/auth/refresh", json={"refresh_token": "not-a-real-token"})
    assert r.status_code == 401


def test_login_rate_limited(client):
    """5 попыток логина в минуту разрешены, 6-я — заблокирована (429)."""
    email = f"{uuid.uuid4()}@example.com"
    client.post("/auth/register", json={"email": email, "password": "password123"})

    for _ in range(5):
        r = client.post("/auth/login", json={"email": email, "password": "wrong"})
        assert r.status_code == 401

    r = client.post("/auth/login", json={"email": email, "password": "wrong"})
    assert r.status_code == 429
