"""
Авторизация: хеширование паролей (bcrypt) + JWT access-токены.

Схема:
  1. POST /auth/register — создаёт пользователя, пароль хешируется, никогда
     не хранится и не логируется в открытом виде.
  2. POST /auth/login — проверяет email+пароль, выдаёт JWT access-токен.
  3. Все защищённые эндпоинты требуют заголовок:
         Authorization: Bearer <token>
     и используют Depends(get_current_user).
"""

from datetime import datetime, timedelta
import hashlib
import secrets

import bcrypt
from fastapi import Depends, HTTPException, status, Header
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.config import (
    SECRET_KEY, JWT_ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES, REFRESH_TOKEN_EXPIRE_DAYS,
    PASSWORD_RESET_TOKEN_EXPIRE_MINUTES, MAX_FAILED_LOGIN_ATTEMPTS, ACCOUNT_LOCKOUT_MINUTES,
)
from app.database import get_db
from app.models import User, RefreshToken, PasswordResetToken

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

# bcrypt ограничивает длину пароля 72 байтами — обрезаем заранее, чтобы
# длинные пароли не роняли хеширование с ошибкой
_BCRYPT_MAX_BYTES = 72


def hash_password(password: str) -> str:
    truncated = password.encode("utf-8")[:_BCRYPT_MAX_BYTES]
    return bcrypt.hashpw(truncated, bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    truncated = plain_password.encode("utf-8")[:_BCRYPT_MAX_BYTES]
    return bcrypt.checkpw(truncated, hashed_password.encode("utf-8"))


def create_access_token(user_id: str) -> str:
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    # jti (случайный nonce) гарантирует, что два токена, выпущенные в одну
    # и ту же секунду (например, /auth/login и сразу /auth/refresh), не
    # окажутся побитово идентичной строкой — JWT детерминирован по payload.
    payload = {"sub": user_id, "exp": expire, "jti": secrets.token_hex(8)}
    return jwt.encode(payload, SECRET_KEY, algorithm=JWT_ALGORITHM)


def _clear_lock_if_expired(user: User) -> None:
    """Если срок блокировки истёк — снимаем её и обнуляем счётчик (чистый
    старт), не дожидаясь следующей успешной попытки входа."""
    if user.locked_until is not None and user.locked_until <= datetime.utcnow():
        user.locked_until = None
        user.failed_login_attempts = 0


def is_locked_out(user: User) -> bool:
    _clear_lock_if_expired(user)
    return user.locked_until is not None and user.locked_until > datetime.utcnow()


def register_failed_login(db: Session, user: User) -> None:
    """
    Считается НЕЗАВИСИМО от IP (в отличие от LOGIN_RATE_LIMIT) — защищает
    от медленного перебора пароля одного конкретного аккаунта с разных
    адресов, который IP-based rate limit не поймает.
    """
    _clear_lock_if_expired(user)
    user.failed_login_attempts += 1
    if user.failed_login_attempts >= MAX_FAILED_LOGIN_ATTEMPTS:
        user.locked_until = datetime.utcnow() + timedelta(minutes=ACCOUNT_LOCKOUT_MINUTES)
        user.failed_login_attempts = 0


def register_successful_login(user: User) -> None:
    user.failed_login_attempts = 0
    user.locked_until = None


def authenticate_user(db: Session, email: str, password: str) -> User | None:
    """
    Простая проверка email+пароль без учёта блокировки аккаунта — саму
    блокировку (is_locked_out/register_failed_login/register_successful_login)
    оркеструет вызывающий код (main.py::login), потому что ему нужно
    явно закоммитить изменения счётчика попыток независимо от исхода.
    """
    user = db.query(User).filter(User.email == email).first()
    if user is None:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user


def _user_from_token(token: str, db: Session) -> User:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Не удалось подтвердить учётные данные",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[JWT_ALGORITHM])
        user_id = payload.get("sub")
        if user_id is None:
            raise credentials_error
    except JWTError:
        raise credentials_error

    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise credentials_error
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Аккаунт деактивирован")

    return user


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    return _user_from_token(token, db)


def get_media_user(
    token: str | None = None,
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),
) -> User:
    """
    Тот же принцип, что get_current_user, но токен может прийти ЛИБО через
    query-параметр ?token=..., ЛИБО через обычный заголовок Authorization.
    Нужен ТОЛЬКО для эндпоинтов отдачи медиафайлов (видео/баннер) — тег
    <video> в браузере не умеет слать кастомные заголовки на свои
    собственные запросы (в том числе Range-запросы при перемотке), а
    значит единственный практичный способ авторизовать такой запрос —
    передать токен прямо в URL. НЕ используется для обычных JSON API —
    там токен в заголовке, как и должно быть, чтобы не оседал в логах/
    истории браузера без необходимости.
    """
    raw_token = token
    if not raw_token and authorization and authorization.lower().startswith("bearer "):
        raw_token = authorization.split(" ", 1)[1]
    if not raw_token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Не авторизован")
    return _user_from_token(raw_token, db)


# ---------- Refresh-токены ----------
#
# Access-токен живёт недолго (ACCESS_TOKEN_EXPIRE_MINUTES, по умолчанию час) —
# это специально, чтобы кража access-токена была ограничена по времени.
# Refresh-токен живёт долго (REFRESH_TOKEN_EXPIRE_DAYS, по умолчанию месяц)
# и используется только для того, чтобы получить новый access-токен через
# /auth/refresh, не заставляя пользователя логиниться заново каждый час.
#
# Хранится не сам токен, а его SHA-256 хеш — так же, как пароль. При
# компрометации БД злоумышленник не получает рабочие refresh-токены.

def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode()).hexdigest()


def create_refresh_token(db: Session, user_id: str) -> str:
    raw_token = secrets.token_urlsafe(48)
    db.add(RefreshToken(
        user_id=user_id,
        token_hash=_hash_token(raw_token),
        expires_at=datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
    ))
    # commit — ответственность вызывающего кода (часть общей транзакции логина)
    return raw_token


def validate_refresh_token(db: Session, raw_token: str) -> User:
    """
    Проверяет refresh-токен и возвращает владельца. НЕ отзывает и не меняет
    сам refresh-токен — он остаётся годным до истечения срока или явного
    /auth/logout. Используется в /auth/refresh, чтобы выдать новый
    access-токен, не заставляя пользователя логиниться заново.

    Поднимает HTTPException(401), если токен невалиден, истёк или отозван.
    """
    token_hash = _hash_token(raw_token)
    stored = db.query(RefreshToken).filter(RefreshToken.token_hash == token_hash).first()

    if stored is None or stored.revoked or stored.expires_at < datetime.utcnow():
        raise HTTPException(401, "Refresh-токен невалиден, истёк или отозван — залогинься заново")

    user = db.query(User).filter(User.id == stored.user_id).first()
    if user is None or not user.is_active:
        raise HTTPException(401, "Пользователь не найден или деактивирован")

    return user


def revoke_refresh_token(db: Session, raw_token: str) -> None:
    """Используется в /auth/logout — делает refresh-токен непригодным для дальнейшего использования."""
    token_hash = _hash_token(raw_token)
    stored = db.query(RefreshToken).filter(RefreshToken.token_hash == token_hash).first()
    if stored:
        stored.revoked = True


def revoke_all_refresh_tokens(db: Session, user_id: str) -> None:
    """
    Отзывает ВСЕ refresh-токены пользователя — вызывается при смене пароля
    и при успешном восстановлении пароля через /auth/reset-password.
    Логика: если пароль сменился (сам пользователь или кто-то через сброс),
    все прежде выданные "долгие" сессии должны стать недействительными —
    иначе смена пароля не отсекает того, кто мог получить старый пароль.
    """
    db.query(RefreshToken).filter(RefreshToken.user_id == user_id, RefreshToken.revoked == False).update(  # noqa: E712
        {"revoked": True}
    )


# ---------- Восстановление пароля ----------
#
# Токен восстановления хранится так же, как refresh-токен — только его
# SHA-256 хеш, не сырое значение. Одноразовый (used=True после применения).

def create_password_reset_token(db: Session, user_id: str) -> str:
    raw_token = secrets.token_urlsafe(32)
    db.add(PasswordResetToken(
        user_id=user_id,
        token_hash=_hash_token(raw_token),
        expires_at=datetime.utcnow() + timedelta(minutes=PASSWORD_RESET_TOKEN_EXPIRE_MINUTES),
    ))
    return raw_token


def consume_password_reset_token(db: Session, raw_token: str) -> User:
    """
    Проверяет токен восстановления пароля и сразу помечает его использованным
    (одноразовый — повторно применить нельзя, даже если не истёк срок).
    Поднимает HTTPException(400), если токен невалиден, истёк или уже использован.
    """
    token_hash = _hash_token(raw_token)
    stored = db.query(PasswordResetToken).filter(PasswordResetToken.token_hash == token_hash).first()

    if stored is None or stored.used or stored.expires_at < datetime.utcnow():
        raise HTTPException(400, "Ссылка для восстановления пароля недействительна или истекла — запроси новую")

    stored.used = True

    user = db.query(User).filter(User.id == stored.user_id).first()
    if user is None or not user.is_active:
        raise HTTPException(400, "Пользователь не найден или деактивирован")

    return user
