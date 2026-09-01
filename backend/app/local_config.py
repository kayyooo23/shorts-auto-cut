"""
Хранилище конфигурации для desktop-режима (RUNNER_MODE=local).

В отличие от облачного режима (переменные окружения, задаются при деплое),
desktop-приложение запускает конечный пользователь двойным кликом — он не
может и не должен вписывать SECRET_KEY/TOKEN_ENCRYPTION_KEY руками. Поэтому
здесь:

- секреты генерируются один раз при первом запуске и сохраняются на диск
  в пользовательскую app-data директорию (не рядом с .exe — та папка может
  быть в Program Files, куда обычный пользователь не может писать, и не
  переживает переустановку/обновление приложения);
- ANTHROPIC_API_KEY пользователь вводит через экран настроек фронтенда,
  тоже сохраняется сюда же (см. /settings/anthropic-key в app/main.py).

get_resource_dir() — отдельная вещь: это папка, где лежат файлы, упакованные
РЯДОМ с .exe (ffmpeg.exe, alembic/), а не пользовательские данные.
"""

import json
import os
import secrets as _secrets
import sys
from pathlib import Path
from threading import Lock

from cryptography.fernet import Fernet

APP_DIR_NAME = "ShortsAutoCut"
_CONFIG_FILE_NAME = "config.json"

_lock = Lock()


def get_data_dir() -> Path:
    """
    Пользовательская директория для БД/секретов/загрузок:
    %APPDATA%/ShortsAutoCut на Windows, ~/.shortsautocut как фолбэк
    на других ОС (запуск не из-под Windows — например, при разработке).
    """
    appdata = os.getenv("APPDATA")
    base = Path(appdata) if appdata else Path.home() / ".shortsautocut"
    data_dir = base / APP_DIR_NAME
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def get_bundled_resource_dir() -> Path:
    """
    Директория с ресурсами, ВПАЯННЫМИ в сам .exe через PyInstaller --add-data
    (alembic/, alembic.ini) — во время работы onefile-сборки они распакованы
    во временную папку sys._MEIPASS, а НЕ рядом с самим .exe на диске.
    При обычном запуске из исходников — папка backend/ в репозитории.
    """
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parent.parent


def get_external_resource_dir() -> Path:
    """
    Директория с ресурсами, лежащими РЯДОМ с самим .exe на диске (не внутри
    PyInstaller-архива) — например, ffmpeg.exe/ffprobe.exe, которые Tauri
    кладёт рядом с backend-сайдкаром при установке. При обычном запуске из
    исходников — папка backend/ в репозитории (см. FFMPEG_PATH/FFPROBE_PATH
    в app/config.py, там же фолбэк на системный PATH).
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _config_path() -> Path:
    return get_data_dir() / _CONFIG_FILE_NAME


def load_config() -> dict:
    path = _config_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_config(data: dict) -> None:
    path = _config_path()
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def get_or_create_local_secrets() -> dict:
    """
    Гарантирует наличие SECRET_KEY и TOKEN_ENCRYPTION_KEY в конфиге —
    генерирует один раз при первом запуске и сохраняет на диск, чтобы они
    не менялись при каждом рестарте (иначе все выданные JWT и все
    сохранённые токены соцаккаунтов становились бы недействительными
    после каждого перезапуска приложения).
    """
    with _lock:
        config = load_config()
        changed = False
        if not config.get("secret_key"):
            config["secret_key"] = _secrets.token_hex(32)
            changed = True
        if not config.get("token_encryption_key"):
            config["token_encryption_key"] = Fernet.generate_key().decode()
            changed = True
        if changed:
            save_config(config)
        return config


def get_anthropic_api_key() -> str:
    return load_config().get("anthropic_api_key", "")


def set_anthropic_api_key(key: str) -> None:
    with _lock:
        config = load_config()
        config["anthropic_api_key"] = key.strip()
        save_config(config)
