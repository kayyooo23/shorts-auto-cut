"""
Шифрование access_token/refresh_token перед записью в БД.

Использует Fernet (симметричное шифрование, cryptography.fernet) с
отдельным ключом TOKEN_ENCRYPTION_KEY — специально НЕ тем же, что
SECRET_KEY для JWT, чтобы утечка одного не автоматически компрометировала
другое.

Генерация ключа для .env:
    python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""

from cryptography.fernet import Fernet, InvalidToken

from app.config import TOKEN_ENCRYPTION_KEY

_fernet = Fernet(TOKEN_ENCRYPTION_KEY.encode()) if TOKEN_ENCRYPTION_KEY else None


def encrypt_token(plain: str | None) -> str | None:
    if plain is None:
        return None
    if _fernet is None:
        raise RuntimeError(
            "TOKEN_ENCRYPTION_KEY не задан — нельзя сохранять токены соцаккаунтов "
            "без шифрования. Сгенерируй ключ и добавь в .env (см. docstring этого модуля)."
        )
    return _fernet.encrypt(plain.encode()).decode()


def decrypt_token(encrypted: str | None) -> str | None:
    if encrypted is None:
        return None
    if _fernet is None:
        raise RuntimeError("TOKEN_ENCRYPTION_KEY не задан — не могу расшифровать токен.")
    try:
        return _fernet.decrypt(encrypted.encode()).decode()
    except InvalidToken:
        raise RuntimeError(
            "Не удалось расшифровать токен — либо повреждён, либо TOKEN_ENCRYPTION_KEY "
            "изменился с момента шифрования (тогда все существующие SocialAccount "
            "нужно переподключать заново, старым ключом их не расшифровать)."
        )
