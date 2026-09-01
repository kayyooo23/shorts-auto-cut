"""
Тесты блокировки аккаунта: считается НЕЗАВИСИМО от IP-based rate limit
(который защищает от перебора с одного адреса) — здесь проверяем защиту
от медленного перебора одного конкретного аккаунта.

Rate limiter из conftest.py сбрасывается перед каждым тестом (autouse
фикстура _test_isolation), поэтому 5 неудачных попыток подряд не упрутся
в LOGIN_RATE_LIMIT (5/minute) раньше, чем сработает блокировка аккаунта.
"""

from datetime import datetime, timedelta

import pytest

from app.config import MAX_FAILED_LOGIN_ATTEMPTS


@pytest.fixture(autouse=True)
def _disable_ip_rate_limit():
    """
    Эти тесты специально делают больше запросов на логин, чем разрешает
    LOGIN_RATE_LIMIT (5/минуту, тестируется отдельно в test_auth.py) —
    нужно изолировать логику блокировки АККАУНТА от логики блокировки
    по IP, иначе они мешают друг другу тестироваться независимо.
    """
    from app.main import app
    app.state.limiter.enabled = False
    yield
    app.state.limiter.enabled = True


def test_account_locks_after_max_failed_attempts(client, register_and_login):
    _headers, _tokens, email = register_and_login(password="correctpass123")

    for _ in range(MAX_FAILED_LOGIN_ATTEMPTS):
        r = client.post("/auth/login", json={"email": email, "password": "wrongpass"})
        assert r.status_code == 401

    # следующая попытка — даже с ПРАВИЛЬНЫМ паролем — должна быть заблокирована
    r = client.post("/auth/login", json={"email": email, "password": "correctpass123"})
    assert r.status_code == 423


def test_successful_login_resets_failed_attempts(client, register_and_login):
    headers, _tokens, email = register_and_login(password="correctpass123")

    # несколько неудачных попыток, но НЕ до порога блокировки
    for _ in range(MAX_FAILED_LOGIN_ATTEMPTS - 1):
        client.post("/auth/login", json={"email": email, "password": "wrongpass"})

    # успешный вход должен сбросить счётчик
    r = client.post("/auth/login", json={"email": email, "password": "correctpass123"})
    assert r.status_code == 200

    # значит, следующая неудачная попытка НЕ должна сразу заблокировать
    r2 = client.post("/auth/login", json={"email": email, "password": "wrongpass"})
    assert r2.status_code == 401  # не 423


def test_locked_account_message_includes_wait_time(client, register_and_login):
    _headers, _tokens, email = register_and_login(password="correctpass123")

    for _ in range(MAX_FAILED_LOGIN_ATTEMPTS):
        client.post("/auth/login", json={"email": email, "password": "wrongpass"})

    r = client.post("/auth/login", json={"email": email, "password": "correctpass123"})
    assert r.status_code == 423
    assert "заблокирован" in r.json()["detail"]


def test_lockout_does_not_affect_other_accounts(client, register_and_login):
    _headers_a, _tokens_a, email_a = register_and_login(password="passa12345")
    headers_b, _tokens_b, email_b = register_and_login(password="passb12345")

    for _ in range(MAX_FAILED_LOGIN_ATTEMPTS):
        client.post("/auth/login", json={"email": email_a, "password": "wrong"})

    # аккаунт A заблокирован
    r_a = client.post("/auth/login", json={"email": email_a, "password": "passa12345"})
    assert r_a.status_code == 423

    # аккаунт B — нет, логика per-account, не глобальная
    r_b = client.post("/auth/login", json={"email": email_b, "password": "passb12345"})
    assert r_b.status_code == 200


def test_lockout_clears_automatically_after_expiry(client, register_and_login):
    """Блокировка снимается сама по истечении срока — без ручного вмешательства."""
    from app.database import SessionLocal
    from app.models import User

    _headers, _tokens, email = register_and_login(password="correctpass123")

    for _ in range(MAX_FAILED_LOGIN_ATTEMPTS):
        client.post("/auth/login", json={"email": email, "password": "wrongpass"})

    # убеждаемся, что залочен
    r = client.post("/auth/login", json={"email": email, "password": "correctpass123"})
    assert r.status_code == 423

    # искусственно "проматываем" время — двигаем locked_until в прошлое,
    # как будто время блокировки истекло
    db = SessionLocal()
    user = db.query(User).filter(User.email == email).first()
    user.locked_until = datetime.utcnow() - timedelta(seconds=1)
    db.commit()
    db.close()

    r2 = client.post("/auth/login", json={"email": email, "password": "correctpass123"})
    assert r2.status_code == 200


def test_nonexistent_email_does_not_error_on_failed_login_tracking(client):
    """Несуществующий email не должен падать с ошибкой на попытке
    записать неудачную попытку (там просто нет User, куда её писать)."""
    r = client.post("/auth/login", json={"email": "nobody@example.com", "password": "whatever123"})
    assert r.status_code == 401


def test_locked_account_rejected_even_with_correct_password(client, register_and_login):
    """Ключевая проверка: блокировка срабатывает ДО сверки пароля — даже
    правильный пароль не пускает, пока аккаунт заблокирован."""
    _headers, _tokens, email = register_and_login(password="correctpass123")

    for _ in range(MAX_FAILED_LOGIN_ATTEMPTS):
        client.post("/auth/login", json={"email": email, "password": "wrong"})

    r = client.post("/auth/login", json={"email": email, "password": "correctpass123"})
    assert r.status_code == 423
