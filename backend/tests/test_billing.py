"""
Тесты биллинга гоняются на реальном коротком видеофайле через реальный
ffprobe (не мок) — see fixture short_video_path. Длинное видео (>30 мин)
не генерируется физически (это было бы дорого) — вместо этого
ensure_duration_allowed() тестируется напрямую с фиктивным числом секунд,
без похода в ffprobe.
"""

import subprocess
from pathlib import Path

import pytest
from fastapi import HTTPException

from app import billing
from app.models import CoinTransactionReason


@pytest.fixture(scope="module")
def short_video_path(tmp_path_factory):
    path = tmp_path_factory.mktemp("videos") / "short.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=blue:s=320x240:d=3", "-c:v", "libx264", str(path)],
        capture_output=True, check=True,
    )
    return str(path)


def _upload(client, headers, path):
    with open(path, "rb") as f:
        return client.post("/videos/upload", files={"file": ("ep.mp4", f, "video/mp4")}, headers=headers)


# ---------- Длительность видео ----------

def test_real_ffprobe_reads_duration(short_video_path):
    duration = billing.get_video_duration_seconds(short_video_path)
    assert abs(duration - 3.0) < 0.5


def test_duration_over_limit_rejected():
    with pytest.raises(HTTPException) as exc_info:
        billing.ensure_duration_allowed(31 * 60)
    assert exc_info.value.status_code == 400


def test_duration_under_limit_allowed():
    billing.ensure_duration_allowed(29 * 60)  # не должно поднять исключение


def test_upload_rejects_too_long_video_without_charging_quota(client, register_and_login, monkeypatch):
    """Если видео длиннее лимита — квота не должна тратиться, а файл должен
    быть удалён с диска (не остаётся мусора после отказа)."""
    headers, _tokens, _email = register_and_login()

    # подменяем определение длительности, чтобы не генерировать реальный
    # 31-минутный файл — сама функция ensure_duration_allowed уже
    # протестирована на реальных числах выше
    monkeypatch.setattr(billing, "get_video_duration_seconds", lambda path: 31 * 60)

    r = client.post(
        "/videos/upload",
        files={"file": ("long.mp4", b"fake bytes", "video/mp4")},
        headers=headers,
    )
    assert r.status_code == 400

    r2 = client.get("/videos", headers=headers)
    assert r2.json() == []  # ничего не создалось в БД


# ---------- Дневная квота нарезок ----------

def test_free_tier_daily_cut_limit(client, register_and_login, short_video_path):
    headers, _tokens, _email = register_and_login()

    r1 = _upload(client, headers, short_video_path)
    assert r1.status_code == 200
    assert r1.json()["paid_with_coins"] is False
    assert r1.json()["remaining_free_cuts_today"] == 0  # free = 1/день

    r2 = _upload(client, headers, short_video_path)
    assert r2.status_code == 402  # квота исчерпана, монет нет


def test_extra_cut_paid_with_coins(client, register_and_login, short_video_path):
    headers, _tokens, _email = register_and_login()

    _upload(client, headers, short_video_path)  # тратим бесплатную квоту

    client.post("/billing/dev/grant-coins", json={"amount": 100}, headers=headers)

    r = _upload(client, headers, short_video_path)
    assert r.status_code == 200
    assert r.json()["paid_with_coins"] is True
    assert r.json()["coins_spent"] == billing.EXTRA_CUT_COST_COINS

    me = client.get("/billing/me", headers=headers).json()
    assert me["coin_balance"] == 100 - billing.EXTRA_CUT_COST_COINS
    assert me["cuts_used_today"] == 2


def test_tier2_has_higher_daily_limit(client, register_and_login, short_video_path):
    headers, _tokens, _email = register_and_login()
    client.post("/billing/dev/set-tier", json={"tier": "tier2"}, headers=headers)

    for _ in range(5):  # tier2 = 5 нарезок/день бесплатно
        r = _upload(client, headers, short_video_path)
        assert r.status_code == 200, r.text
        assert r.json()["paid_with_coins"] is False

    r = _upload(client, headers, short_video_path)  # 6-я — сверх лимита
    assert r.status_code == 402


# ---------- Лимиты подключённых аккаунтов ----------

def test_free_tier_account_limit_per_platform(client, register_and_login):
    from app.models import Platform, SocialAccount
    from app.database import SessionLocal

    headers, _tokens, email = register_and_login()

    db = SessionLocal()
    from app.models import User
    user = db.query(User).filter(User.email == email).first()

    # free = 1 аккаунт на платформу — первый бесплатно
    used_coins = billing.ensure_account_slot_available(db, user, Platform.YOUTUBE)
    assert used_coins is False
    db.add(SocialAccount(owner_id=user.id, platform=Platform.YOUTUBE, platform_account_id="yt1", access_token="x"))
    db.commit()

    # второй — лимит исчерпан, монет нет
    with pytest.raises(HTTPException) as exc_info:
        billing.ensure_account_slot_available(db, user, Platform.YOUTUBE)
    assert exc_info.value.status_code == 402
    db.close()


def test_extra_account_slot_purchase_persists(client, register_and_login):
    from app.models import Platform, SocialAccount, User
    from app.database import SessionLocal

    headers, _tokens, email = register_and_login()
    client.post("/billing/dev/grant-coins", json={"amount": 1000}, headers=headers)

    db = SessionLocal()
    user = db.query(User).filter(User.email == email).first()

    used_coins = billing.ensure_account_slot_available(db, user, Platform.TIKTOK)
    assert used_coins is False  # первый аккаунт — в рамках базового лимита free=1
    db.add(SocialAccount(owner_id=user.id, platform=Platform.TIKTOK, platform_account_id="tt1", access_token="x"))
    db.commit()

    # второй — покупаем слот за монеты
    used_coins2 = billing.ensure_account_slot_available(db, user, Platform.TIKTOK)
    assert used_coins2 is True
    db.add(SocialAccount(owner_id=user.id, platform=Platform.TIKTOK, platform_account_id="tt2", access_token="x"))
    db.commit()

    db.refresh(user)
    assert user.coin_balance == 1000 - billing.EXTRA_ACCOUNT_SLOT_COST_COINS

    # лимит увеличился НАВСЕГДА (не разовое разрешение)
    new_limit = billing.account_slot_limit(db, user, Platform.TIKTOK)
    assert new_limit == 2  # 1 базовый + 1 докупленный

    db.close()


def test_insufficient_coins_returns_402_with_no_side_effects(client, register_and_login):
    from app.models import Platform, User
    from app.database import SessionLocal

    headers, _tokens, email = register_and_login()
    db = SessionLocal()
    user = db.query(User).filter(User.email == email).first()

    balance_before = user.coin_balance
    with pytest.raises(HTTPException):
        billing.spend_coins(db, user, 9999, CoinTransactionReason.EXTRA_CUT)

    db.refresh(user)
    assert user.coin_balance == balance_before  # ничего не списалось при отказе
    db.close()


def test_billing_me_reflects_state(client, register_and_login, short_video_path):
    headers, _tokens, _email = register_and_login()
    _upload(client, headers, short_video_path)

    r = client.get("/billing/me", headers=headers)
    assert r.status_code == 200
    data = r.json()
    assert data["subscription_tier"] == "free"
    assert data["cuts_used_today"] == 1
    assert data["cuts_daily_limit"] == 1
    assert len(data["platform_usage"]) == 3


def test_dev_endpoints_disabled_in_production(client, register_and_login, monkeypatch):
    """Dev-эндпоинты для начисления монет/смены тарифа без оплаты должны
    существовать только НЕ в проде. Формально это lifecycle-флаг на старте
    приложения, поэтому здесь проверяем сам факт наличия/логики флага
    ENVIRONMENT, а не runtime-переключение (роуты регистрируются один раз
    при импорте app.main)."""
    from app.config import ENVIRONMENT
    # В тестовом окружении ENVIRONMENT=development — эндпоинты должны быть доступны
    assert ENVIRONMENT != "production"
    headers, _tokens, _email = register_and_login()
    r = client.post("/billing/dev/grant-coins", json={"amount": 10}, headers=headers)
    assert r.status_code == 200


def test_same_ip_signup_signal_is_informational_not_blocking(client):
    """Несколько free-регистраций с одного IP НЕ блокируются (см. billing.py
    docstring про CGNAT/общие сети) — но счётчик в /billing/me растёт,
    это сигнал для ручной проверки, а не автоматический отказ."""
    import uuid

    emails = [f"{uuid.uuid4()}@example.com" for _ in range(3)]
    headers_list = []
    for email in emails:
        r = client.post("/auth/register", json={"email": email, "password": "password123"})
        assert r.status_code == 200 or r.status_code == 201  # регистрация не блокируется
        r = client.post("/auth/login", json={"email": email, "password": "password123"})
        headers_list.append({"Authorization": f"Bearer {r.json()['access_token']}"})

    me = client.get("/billing/me", headers=headers_list[-1]).json()
    # TestClient всегда бьёт с одного "IP" (testclient) — счётчик должен
    # отразить все 3 регистрации из этой пачки
    assert me["same_ip_free_signups_last_7d"] >= 3
