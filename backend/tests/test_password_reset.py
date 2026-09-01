"""
Тесты смены и восстановления пароля. dev_reset_token в ответе
/auth/forgot-password существует только вне продакшена (ENVIRONMENT=development
в тестах) — именно так тестируем полный флоу без настоящего email-провайдера.
"""


def test_change_password_success(client, register_and_login):
    headers, _tokens, email = register_and_login(password="oldpassword123")

    r = client.post(
        "/auth/change-password",
        json={"current_password": "oldpassword123", "new_password": "newpassword456"},
        headers=headers,
    )
    assert r.status_code == 200

    # старый пароль больше не работает
    r2 = client.post("/auth/login", json={"email": email, "password": "oldpassword123"})
    assert r2.status_code == 401

    # новый пароль работает
    r3 = client.post("/auth/login", json={"email": email, "password": "newpassword456"})
    assert r3.status_code == 200


def test_change_password_wrong_current_rejected(client, register_and_login):
    headers, _tokens, _email = register_and_login(password="oldpassword123")

    r = client.post(
        "/auth/change-password",
        json={"current_password": "wrongpassword", "new_password": "newpassword456"},
        headers=headers,
    )
    assert r.status_code == 400


def test_change_password_too_short_rejected(client, register_and_login):
    headers, _tokens, _email = register_and_login(password="oldpassword123")

    r = client.post(
        "/auth/change-password",
        json={"current_password": "oldpassword123", "new_password": "short"},
        headers=headers,
    )
    assert r.status_code == 422


def test_change_password_requires_auth(client):
    r = client.post(
        "/auth/change-password",
        json={"current_password": "x", "new_password": "newpassword456"},
    )
    assert r.status_code == 401


def test_change_password_revokes_existing_refresh_tokens(client, register_and_login):
    headers, tokens, _email = register_and_login(password="oldpassword123")

    old_refresh_token = tokens["refresh_token"]

    client.post(
        "/auth/change-password",
        json={"current_password": "oldpassword123", "new_password": "newpassword456"},
        headers=headers,
    )

    r = client.post("/auth/refresh", json={"refresh_token": old_refresh_token})
    assert r.status_code == 401


def test_forgot_password_returns_generic_message_for_unknown_email(client):
    r = client.post("/auth/forgot-password", json={"email": "nobody-here@example.com"})
    assert r.status_code == 200
    assert "dev_reset_token" not in r.json() or r.json()["dev_reset_token"] is None
    assert "существует" in r.json()["message"]


def test_forgot_password_does_not_reveal_existing_account_differently(client, register_and_login):
    """Ответ на существующий и несуществующий email не должен отличаться
    по содержимому message — иначе это user enumeration."""
    _headers, _tokens, email = register_and_login()

    r_known = client.post("/auth/forgot-password", json={"email": email})
    r_unknown = client.post("/auth/forgot-password", json={"email": "definitely-not-registered@example.com"})

    assert r_known.json()["message"] == r_unknown.json()["message"]


def test_forgot_password_returns_dev_token_outside_production(client, register_and_login):
    from app.config import ENVIRONMENT
    assert ENVIRONMENT != "production"  # тест валиден только для dev-режима

    _headers, _tokens, email = register_and_login()
    r = client.post("/auth/forgot-password", json={"email": email})
    assert r.status_code == 200
    assert r.json()["dev_reset_token"] is not None


def test_reset_password_with_valid_token(client, register_and_login):
    headers, _tokens, email = register_and_login(password="oldpassword123")

    r = client.post("/auth/forgot-password", json={"email": email})
    reset_token = r.json()["dev_reset_token"]

    r2 = client.post("/auth/reset-password", json={"token": reset_token, "new_password": "brandnewpass789"})
    assert r2.status_code == 200

    r3 = client.post("/auth/login", json={"email": email, "password": "brandnewpass789"})
    assert r3.status_code == 200

    r4 = client.post("/auth/login", json={"email": email, "password": "oldpassword123"})
    assert r4.status_code == 401


def test_reset_password_token_is_single_use(client, register_and_login):
    _headers, _tokens, email = register_and_login(password="oldpassword123")

    r = client.post("/auth/forgot-password", json={"email": email})
    reset_token = r.json()["dev_reset_token"]

    r2 = client.post("/auth/reset-password", json={"token": reset_token, "new_password": "firstchange123"})
    assert r2.status_code == 200

    # повторное использование того же токена должно быть отклонено
    r3 = client.post("/auth/reset-password", json={"token": reset_token, "new_password": "secondchange456"})
    assert r3.status_code == 400


def test_reset_password_invalid_token_rejected(client):
    r = client.post("/auth/reset-password", json={"token": "not-a-real-token", "new_password": "somepassword123"})
    assert r.status_code == 400


def test_reset_password_revokes_existing_refresh_tokens(client, register_and_login):
    _headers, tokens, email = register_and_login(password="oldpassword123")
    old_refresh_token = tokens["refresh_token"]

    r = client.post("/auth/forgot-password", json={"email": email})
    reset_token = r.json()["dev_reset_token"]
    client.post("/auth/reset-password", json={"token": reset_token, "new_password": "newpassword999"})

    r2 = client.post("/auth/refresh", json={"refresh_token": old_refresh_token})
    assert r2.status_code == 401


def test_forgot_password_rate_limited(client, register_and_login):
    _headers, _tokens, email = register_and_login()

    for _ in range(3):
        r = client.post("/auth/forgot-password", json={"email": email})
        assert r.status_code == 200

    r = client.post("/auth/forgot-password", json={"email": email})
    assert r.status_code == 429
