"""
Конфигурация приложения. Все параметры читаются из переменных окружения,
с разумными дефолтами для локальной разработки.
"""

import os
import sys
from pathlib import Path

# Режим выполнения фоновых задач — определяется здесь же (а не ниже, как
# раньше), потому что от него зависят пути к БД/хранилищу и источник
# секретов ниже. См. подробное описание режимов у переменной RUNNER_MODE.
RUNNER_MODE = os.getenv("RUNNER_MODE", "celery")

# BASE_DIR — директория с РЕСУРСАМИ приложения (alembic/, ffmpeg рядом с
# .exe): при обычном запуске из исходников это папка backend/ в репозитории,
# при запуске из PyInstaller-сборки (RUNNER_MODE=local) — папка, где лежит
# сам .exe. Это НЕ путь для пользовательских данных (БД/загрузки/секреты) —
# та не должна зависеть от того, куда установлен .exe (Program Files и т.п.
# может быть недоступен для записи), см. DATA_DIR ниже.
if RUNNER_MODE == "local":
    from app.local_config import (
        get_data_dir,
        get_bundled_resource_dir,
        get_external_resource_dir,
        get_or_create_local_secrets,
        get_anthropic_api_key as _get_anthropic_api_key,
    )

    BASE_DIR = get_bundled_resource_dir()
    EXTERNAL_RESOURCE_DIR = get_external_resource_dir()
    DATA_DIR = get_data_dir()
    _local_secrets = get_or_create_local_secrets()
else:
    BASE_DIR = Path(__file__).resolve().parent.parent
    EXTERNAL_RESOURCE_DIR = BASE_DIR
    DATA_DIR = BASE_DIR
    _local_secrets = {}

# База данных (по умолчанию SQLite; в desktop-режиме — в app-data
# директории пользователя, не рядом с .exe и не в CWD процесса — см.
# DATA_DIR выше. На проде облачного SaaS лучше Postgres — см. README)
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{(DATA_DIR / 'storage' / 'app.db').as_posix()}")

# Redis — брокер для Celery (очередь фоновых задач). Не используется в
# desktop-режиме (RUNNER_MODE=local).
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")

# Anthropic API — для поиска интересных моментов и подбора хештегов.
# В desktop-режиме пользователь вводит ключ через экран настроек фронтенда
# (см. /settings/anthropic-key в app/main.py) — он сохраняется в тот же
# локальный конфиг, что и секреты выше, а не в переменные окружения.
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY") or (_get_anthropic_api_key() if RUNNER_MODE == "local" else "") or ""
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")

# Whisper
WHISPER_MODEL_SIZE = os.getenv("WHISPER_MODEL_SIZE", "medium")
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cpu")  # "cuda" если есть GPU

# Куда сохраняются загруженные видео и результаты нарезки
UPLOADS_DIR = DATA_DIR / "storage" / "uploads"
OUTPUTS_DIR = DATA_DIR / "storage" / "outputs"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

# Сколько моментов искать по умолчанию на один эпизод
DEFAULT_MOMENTS_COUNT = int(os.getenv("DEFAULT_MOMENTS_COUNT", "6"))

# Авторизация (JWT)
# ВАЖНО: на проде SECRET_KEY обязательно переопредели через переменную
# окружения — приложение откажется стартовать в проде с дефолтным ключом
# (см. проверку в main.py). В desktop-режиме (RUNNER_MODE=local) ключ
# генерируется один раз при первом запуске и хранится в локальном
# конфиге — см. app/local_config.py.
SECRET_KEY = os.getenv("SECRET_KEY") or _local_secrets.get("secret_key") or "dev-only-insecure-secret-change-me"
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))  # 1 час
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "30"))

# Разрешённые источники для CORS — на проде ОБЯЗАТЕЛЬНО указать реальный
# домен фронтенда через запятую, "*" допустим только для локальной разработки.
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*").split(",")

# "production" / "development" — переключает строгие проверки безопасности
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")

# Лимиты на попытки логина/регистрации (защита от брутфорса и спам-регистрации)
LOGIN_RATE_LIMIT = os.getenv("LOGIN_RATE_LIMIT", "5/minute")
REGISTER_RATE_LIMIT = os.getenv("REGISTER_RATE_LIMIT", "3/minute")

# Восстановление пароля
PASSWORD_RESET_TOKEN_EXPIRE_MINUTES = int(os.getenv("PASSWORD_RESET_TOKEN_EXPIRE_MINUTES", "60"))
FORGOT_PASSWORD_RATE_LIMIT = os.getenv("FORGOT_PASSWORD_RATE_LIMIT", "3/minute")

# Блокировка аккаунта после N неудачных попыток входа подряд — защита от
# медленного перебора пароля с разных IP по ОДНОМУ конкретному аккаунту
# (rate limit по IP выше этого не ловит, потому что там IP разные).
# Считается независимо от IP, сбрасывается при успешном входе.
MAX_FAILED_LOGIN_ATTEMPTS = int(os.getenv("MAX_FAILED_LOGIN_ATTEMPTS", "5"))
ACCOUNT_LOCKOUT_MINUTES = int(os.getenv("ACCOUNT_LOCKOUT_MINUTES", "15"))

# --- OAuth-приложения платформ публикации ---
# Каждое получается в консоли разработчика соответствующей платформы,
# см. комментарии в app/publishers/*.py про требования каждой платформы.
APP_BASE_URL = os.getenv("APP_BASE_URL", "http://localhost:8000")
# Адрес фронтенда — куда редиректить пользователя после OAuth-подключения
# аккаунта (см. main.py::social_account_callback). Специально отдельная
# переменная, а не APP_BASE_URL — это разные адреса (backend/frontend).
FRONTEND_BASE_URL = os.getenv("FRONTEND_BASE_URL", "http://localhost:5173")

YOUTUBE_CLIENT_ID = os.getenv("YOUTUBE_CLIENT_ID", "")
YOUTUBE_CLIENT_SECRET = os.getenv("YOUTUBE_CLIENT_SECRET", "")

TIKTOK_CLIENT_KEY = os.getenv("TIKTOK_CLIENT_KEY", "")
TIKTOK_CLIENT_SECRET = os.getenv("TIKTOK_CLIENT_SECRET", "")

INSTAGRAM_APP_ID = os.getenv("INSTAGRAM_APP_ID", "")
INSTAGRAM_APP_SECRET = os.getenv("INSTAGRAM_APP_SECRET", "")

# Публичный базовый URL для хранилища рендеров — нужен для Instagram,
# которому нужна публичная прямая ссылка на видео (см. publishers/instagram.py)
PUBLIC_STORAGE_BASE_URL = os.getenv("PUBLIC_STORAGE_BASE_URL", "")

# (RUNNER_MODE читается в самом верху файла — от него зависят пути к
# БД/хранилищу и источник секретов, см. комментарий там же. Здесь только
# описание режимов для справки:
#   "celery" (по умолчанию) — задачи уходят через Redis-брокер на отдельный
#     воркер-процесс; нужен для облачного SaaS с несколькими пользователями.
#   "local" — задачи выполняются в пуле потоков внутри того же процесса,
#     без Redis/Celery/Docker; используется в desktop-версии (Tauri).
# См. app/job_runner.py — единая точка dispatch(), которая прячет разницу
# от остального кода (app/main.py не знает, какой режим активен).)

# Какие платформы реально доступны для подключения прямо сейчас.
# YouTube работает "из коробки" сразу после получения ключей. TikTok до
# прохождения ревью (audit) публикует только приватно (видно только автору),
# Instagram требует Business-аккаунт + публичный хостинг видео — оба готовы
# как код, но не готовы как реальная услуга для случайного пользователя,
# пока эти внешние условия не выполнены. Выключены по умолчанию, чтобы не
# создавать пользователю ложных ожиданий "нажал — работает".
PLATFORM_ENABLED = {
    "youtube": os.getenv("PLATFORM_YOUTUBE_ENABLED", "true").lower() == "true",
    "tiktok": os.getenv("PLATFORM_TIKTOK_ENABLED", "false").lower() == "true",
    "instagram": os.getenv("PLATFORM_INSTAGRAM_ENABLED", "false").lower() == "true",
}

# --- Тарифы, лимиты и монеты ---

# Максимальная длина одного видео на вход, для ЛЮБОГО тарифа (в секундах)
MAX_VIDEO_DURATION_SECONDS = int(os.getenv("MAX_VIDEO_DURATION_SECONDS", str(30 * 60)))

# Сколько нарезок (загрузок видео на обработку) доступно бесплатно в сутки
# по каждому тарифу
DAILY_CUT_LIMITS = {
    "free": 1,
    "tier2": 5,
    "tier3": 9,
}

# Сколько раз в день можно бесплатно применить уникализацию (pipeline/uniqueize.py)
# при публикации. Считается ЗА НАРЕЗКУ (один вызов POST /moments/{id}/publish
# с uniqueize=true), а не за каждый аккаунт — даже если этот вызов создаёт
# PublishTarget сразу на 5 подключённых аккаунтов, это одно списание квоты.
DAILY_UNIQUEIZE_LIMITS = {
    "free": 2,
    "tier2": 5,
    "tier3": 10,
}

# Сколько аккаунтов НА КАЖДУЮ платформу (YouTube/TikTok/Instagram по отдельности)
# можно подключить бесплатно по каждому тарифу
ACCOUNT_LIMITS_PER_PLATFORM = {
    "free": 1,
    "tier2": 3,
    "tier3": 5,
}

# Цены в монетах
EXTRA_CUT_COST_COINS = int(os.getenv("EXTRA_CUT_COST_COINS", "50"))
EXTRA_ACCOUNT_SLOT_COST_COINS = int(os.getenv("EXTRA_ACCOUNT_SLOT_COST_COINS", "200"))

# Секрет для проверки вебхуков от платёжного провайдера (см. main.py:
# /billing/coins/webhook, /billing/subscription/webhook). ЗАМЕНИТЬ на
# реальную HMAC-проверку подписи конкретного провайдера перед продакшеном —
# статический секрет в теле запроса это временная заглушка для разработки.
PAYMENT_WEBHOOK_SECRET = os.getenv("PAYMENT_WEBHOOK_SECRET", "")

# Ключ шифрования access_token/refresh_token соцаккаунтов (Fernet).
# ОТДЕЛЬНЫЙ от SECRET_KEY — компрометация одного не должна автоматически
# компрометировать другой. Сгенерировать:
#   python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# В desktop-режиме — как и SECRET_KEY, генерируется один раз и хранится
# в локальном конфиге (app/local_config.py), а не в переменной окружения.
TOKEN_ENCRYPTION_KEY = os.getenv("TOKEN_ENCRYPTION_KEY") or _local_secrets.get("token_encryption_key") or ""

if not TOKEN_ENCRYPTION_KEY and ENVIRONMENT != "production":
    # Удобство для локальной разработки: ключ генерируется на старте процесса.
    # ВАЖНО: он не переживёт рестарт — все SocialAccount, созданные в эту
    # сессию, станут нерасшифровываемыми после перезапуска. Для чего-то
    # долгоживущего даже локально — задай TOKEN_ENCRYPTION_KEY в .env.
    from cryptography.fernet import Fernet
    TOKEN_ENCRYPTION_KEY = Fernet.generate_key().decode()
    print(
        "[config] TOKEN_ENCRYPTION_KEY не задан — сгенерирован временный ключ "
        "на время этого запуска (только для разработки). Задай постоянный "
        "в .env, если не хочешь терять доступ к токенам между рестартами.",
        file=sys.stderr,
    )


def assert_production_safe() -> None:
    """
    Жёсткая проверка при старте: не даёт приложению подняться в проде
    с небезопасными дефолтами. Вызывается из main.py.
    """
    if ENVIRONMENT != "production":
        return

    problems = []
    if SECRET_KEY == "dev-only-insecure-secret-change-me":
        problems.append("SECRET_KEY не переопределён (используется дефолт для разработки)")
    if CORS_ORIGINS == ["*"]:
        problems.append("CORS_ORIGINS=* разрешает запросы с любого сайта — укажи домен фронтенда")
    if DATABASE_URL.startswith("sqlite"):
        problems.append("DATABASE_URL указывает на SQLite — на проде используй Postgres")
    if not PAYMENT_WEBHOOK_SECRET:
        problems.append("PAYMENT_WEBHOOK_SECRET не задан — вебхуки оплаты не защищены")
    if not TOKEN_ENCRYPTION_KEY:
        problems.append("TOKEN_ENCRYPTION_KEY не задан — токены соцаккаунтов нельзя будет сохранить")
    problems.append(
        "Реальный email-провайдер не подключён (app/email.py — сейчас только dev-заглушка, "
        "печатает письма в лог вместо отправки) — восстановление пароля не будет работать для пользователей"
    )

    if problems:
        raise RuntimeError(
            "Небезопасная конфигурация для ENVIRONMENT=production:\n  - "
            + "\n  - ".join(problems)
        )
