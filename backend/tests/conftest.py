"""
Настройка тестового окружения. Выполняется ДО импорта любого app.* модуля
в тестовых файлах — критично, чтобы переменные окружения и заглушки
тяжёлых зависимостей (faster_whisper, anthropic) были на месте раньше,
чем app.config их прочитает.

Использует отдельную временную SQLite-базу на весь тестовый прогон
(не in-memory ":memory:", потому что у каждого соединения был бы свой
пустой инстанс — файл на диске гарантирует, что все сессии видят одни
и те же данные).
"""

import os
import sys
import tempfile
import types
import uuid

_tmpdir = tempfile.mkdtemp(prefix="shorts_app_test_")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_tmpdir}/test.db")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("PAYMENT_WEBHOOK_SECRET", "test-webhook-secret")
os.environ.setdefault("CORS_ORIGINS", "*")

from cryptography.fernet import Fernet  # noqa: E402
os.environ.setdefault("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())

# Тяжёлые/недоступные в CI зависимости — не нужны для API/billing/render тестов.
# Тесты, которым реально нужен whisper или Claude, не входят в этот набор
# (это были бы дорогие интеграционные тесты с реальными ключами/GPU).
if "faster_whisper" not in sys.modules:
    fw_stub = types.ModuleType("faster_whisper")
    fw_stub.WhisperModel = object
    sys.modules["faster_whisper"] = fw_stub

if "anthropic" not in sys.modules:
    anthropic_stub = types.ModuleType("anthropic")
    anthropic_stub.Anthropic = object
    sys.modules["anthropic"] = anthropic_stub

import pytest
from fastapi.testclient import TestClient

# Явно создаём схему БД для тестов через create_all — быстрее и проще, чем
# гонять Alembic-миграции на эфемерной тестовой базе. app/main.py сам
# больше не создаёт таблицы неявно (см. его код): в RUNNER_MODE=local он
# гоняет alembic upgrade head, а в облачном режиме миграции — это ручной
# шаг деплоя, не то, что должно происходить при обычном импорте модуля.
from app.database import Base, engine
import app.models  # noqa: F401 — регистрирует все таблицы на Base.metadata
Base.metadata.create_all(bind=engine)

from app.main import app
import app.tasks as tasks_module


@pytest.fixture(autouse=True)
def _test_isolation(monkeypatch):
    """
    Автоматически применяется к каждому тесту:
    - Celery-задачи не диспатчатся реально (нет брокера в тестах) — тест
      сам решает, вызывать ли .run() синхронно, если ему нужен результат.
    - Rate limiter сбрасывается, чтобы тесты login/register не мешали
      друг другу общим лимитом на TestClient-адрес.
    """
    monkeypatch.setattr(tasks_module.process_video, "delay", lambda *a, **k: None)
    monkeypatch.setattr(tasks_module.publish_target, "delay", lambda *a, **k: None)
    monkeypatch.setattr(tasks_module.render_moment_task, "delay", lambda *a, **k: None)
    app.state.limiter.reset()
    yield


@pytest.fixture()
def client():
    return TestClient(app)


@pytest.fixture()
def register_and_login(client):
    """
    Фабрика: register_and_login() -> (headers, tokens_dict, email)
    Каждый вызов создаёт нового пользователя со случайным email — тесты
    не пересекаются по дневным квотам/лимитам аккаунтов.
    """
    def _make(email: str | None = None, password: str = "password123"):
        email = email or f"{uuid.uuid4()}@example.com"
        r = client.post("/auth/register", json={"email": email, "password": password})
        assert r.status_code == 201, r.text
        r = client.post("/auth/login", json={"email": email, "password": password})
        assert r.status_code == 200, r.text
        tokens = r.json()
        headers = {"Authorization": f"Bearer {tokens['access_token']}"}
        return headers, tokens, email
    return _make
