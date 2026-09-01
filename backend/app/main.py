"""
API-сервер приложения.

Основные эндпоинты:
  POST   /videos/upload           — загрузить эпизод, запускает обработку
  GET    /videos                  — список всех загруженных видео
  GET    /videos/{id}             — статус видео + найденные моменты
  PATCH  /moments/{id}            — редактирование момента (таймкоды, статус, баннер)
  PATCH  /subtitles/{id}          — редактирование одной реплики субтитров
  DELETE /moments/{id}            — удалить момент (например, если не подошёл)
"""

import shutil
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, HTTPException, Depends, Request
from fastapi.responses import RedirectResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from sqlalchemy.orm import Session

from app.config import UPLOADS_DIR, CORS_ORIGINS, LOGIN_RATE_LIMIT, REGISTER_RATE_LIMIT, assert_production_safe, FRONTEND_BASE_URL, FORGOT_PASSWORD_RATE_LIMIT
from app.database import get_db, SessionLocal
from app.models import (
    Video, Moment, Subtitle, VideoStatus, User,
    SocialAccount, PublishTarget, Platform, PublishStatus, MomentStatus,
    SubscriptionTier, CoinTransactionReason, HashtagDraft, Project,
    Track, Clip, TrackType,
)
from app.schemas import (
    VideoOut, VideoListItem, MomentOut, MomentUpdate, SubtitleOut, SubtitleUpdate, SubtitleCreate,
    UserCreate, UserLogin, UserOut, Token,
    SocialAccountOut, PublishTargetOut, PublishRequest,
    UploadResponse, BillingMe, PlatformUsage, CoinGrant, TierSet,
    RefreshRequest, AccessTokenOnly, HashtagDraftOut, HashtagDraftCreate,
    ProjectOut, ProjectCreate, ProjectUpdate,
    ChangePasswordRequest, ForgotPasswordRequest, ForgotPasswordResponse, ResetPasswordRequest,
    DeleteAccountRequest,
    TrackOut, TrackCreate, ClipOut, ClipUpdate,
)
from app.auth import (
    hash_password, verify_password, create_access_token, get_current_user, get_media_user,
    create_refresh_token, validate_refresh_token, revoke_refresh_token, revoke_all_refresh_tokens,
    create_password_reset_token, consume_password_reset_token,
    is_locked_out, register_failed_login, register_successful_login,
)
from app.email import send_password_reset_email, EmailNotConfiguredError
from app.tasks import process_video, publish_target as publish_target_task, render_moment_task
from app.job_runner import dispatch
from pipeline.suggest_hashtags import suggest_hashtags
from pipeline.thumbnail import get_or_create_thumbnail, ThumbnailError
from app import oauth
from app import billing
from app.config import ENVIRONMENT, RUNNER_MODE, BASE_DIR

# Останавливаем запуск, если конфигурация небезопасна для прода
# (дефолтный SECRET_KEY, открытый CORS, SQLite и т.п.)
assert_production_safe()


def _run_migrations_to_head() -> None:
    """
    Накатывает схему БД до последней миграции через Alembic (alembic/).
    `alembic upgrade head` идемпотентен — повторный вызов на уже актуальной
    базе ничего не делает, поэтому безопасно гонять при каждом старте.
    """
    from alembic.config import Config
    from alembic import command

    alembic_cfg = Config(str(BASE_DIR / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(BASE_DIR / "alembic"))
    command.upgrade(alembic_cfg, "head")


if RUNNER_MODE == "local":
    # Desktop-режим: пользователь не запускает `alembic upgrade head` руками —
    # приложение само доводит схему БД до актуальной при каждом старте.
    _run_migrations_to_head()
else:
    # Облачный режим (RUNNER_MODE=celery): миграции — явный шаг деплоя
    # (`alembic upgrade head` перед перезапуском серверов), НЕ автоматический
    # при старте — иначе несколько одновременно поднимающихся инстансов
    # приложения могли бы гонять миграцию параллельно друг с другом.
    # См. README, раздел "Миграции базы данных (Alembic)".
    pass


def _bootstrap_admin_account() -> None:
    """
    Единственный способ завести админ-аккаунт — задать ADMIN_EMAIL и
    ADMIN_PASSWORD в окружении (см. .env.example), НЕ публичная форма
    регистрации. Идемпотентно, безопасно гонять при каждом старте:
      - пользователя с таким email нет — создаёт его с is_admin=True;
      - уже есть — просто гарантирует is_admin=True (на случай, если
        переменные добавили ПОСЛЕ того, как аккаунт уже существовал,
        например обычной регистрацией на тот же email).
    """
    from app.config import ADMIN_EMAIL, ADMIN_PASSWORD

    if not ADMIN_EMAIL or not ADMIN_PASSWORD:
        return

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == ADMIN_EMAIL).first()
        if user is None:
            user = User(
                email=ADMIN_EMAIL,
                hashed_password=hash_password(ADMIN_PASSWORD),
                is_admin=True,
            )
            db.add(user)
            db.commit()
        elif not user.is_admin:
            user.is_admin = True
            db.commit()
    finally:
        db.close()


_bootstrap_admin_account()

app = FastAPI(title="Shorts Auto-Cut API")


@app.on_event("startup")
def _start_local_scheduler():
    # В desktop-режиме (RUNNER_MODE=local) нет Celery Beat — отложенную
    # публикацию по расписанию проверяет свой фоновый поток внутри же
    # процесса. В облачном режиме (RUNNER_MODE=celery) это делает
    # отдельный процесс `celery beat`, здесь ничего запускать не нужно.
    if RUNNER_MODE == "local":
        from app import local_scheduler
        local_scheduler.start()


@app.on_event("shutdown")
def _stop_local_scheduler():
    if RUNNER_MODE == "local":
        from app import local_scheduler
        local_scheduler.stop()


# Rate limiting — защита /auth/* от перебора паролей и спам-регистрации
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS_ORIGINS берётся из окружения — на проде это конкретный домен фронтенда,
# не "*" (иначе любой сайт сможет слать запросы от имени залогиненного пользователя)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

ALLOWED_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".webm"}


# ---------- Авторизация ----------

@app.post("/auth/register", response_model=UserOut, status_code=201)
@limiter.limit(REGISTER_RATE_LIMIT)
def register(request: Request, data: UserCreate, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.email == data.email).first()
    if existing:
        raise HTTPException(400, "Пользователь с таким email уже зарегистрирован")

    user = User(
        email=data.email,
        hashed_password=hash_password(data.password),
        registration_ip=get_remote_address(request),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@app.post("/auth/login", response_model=Token)
@limiter.limit(LOGIN_RATE_LIMIT)
def login(request: Request, data: UserLogin, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == data.email).first()

    if user is not None and is_locked_out(user):
        remaining = int((user.locked_until - datetime.utcnow()).total_seconds())
        db.commit()  # на случай, если is_locked_out только что сняла истёкшую блокировку
        raise HTTPException(
            423,
            f"Аккаунт временно заблокирован из-за большого числа неудачных попыток входа. "
            f"Попробуй снова через {max(remaining // 60 + 1, 1)} мин.",
        )

    if user is None or not verify_password(data.password, user.hashed_password):
        if user is not None:
            register_failed_login(db, user)
            db.commit()
        raise HTTPException(401, "Неверный email или пароль")

    register_successful_login(user)

    access_token = create_access_token(user.id)
    refresh_token = create_refresh_token(db, user.id)
    db.commit()
    return Token(access_token=access_token, refresh_token=refresh_token)


@app.post("/auth/refresh", response_model=AccessTokenOnly)
def refresh(data: RefreshRequest, db: Session = Depends(get_db)):
    """
    Обменивает refresh-токен на новый access-токен. Используется, когда
    access-токен истёк (обычно через час) — фронтенд вызывает это вместо
    того, чтобы заставлять пользователя логиниться заново. Возвращает
    только access_token: refresh-токен НЕ ротируется на каждый /refresh —
    ротация только на login, иначе клиенту пришлось бы каждый раз
    пересохранять новый refresh_token, что усложняет фронтенд без
    ощутимого выигрыша в безопасности для этого сценария.
    """
    user = validate_refresh_token(db, data.refresh_token)
    access_token = create_access_token(user.id)
    return AccessTokenOnly(access_token=access_token)


@app.post("/auth/logout")
def logout(data: RefreshRequest, db: Session = Depends(get_db)):
    """Отзывает refresh-токен — после этого им нельзя будет получить новый access-токен."""
    revoke_refresh_token(db, data.refresh_token)
    db.commit()
    return {"ok": True}


@app.post("/auth/change-password")
def change_password(
    data: ChangePasswordRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Смена пароля залогиненным пользователем. Требует текущий пароль —
    так проверяем, что это реально владелец аккаунта, а не кто-то, кто
    перехватил активный access-токен (например, оставленную открытой сессию).

    Отзывает ВСЕ refresh-токены после смены — если пароль скомпрометирован
    и кто-то ещё держит долгую сессию, эта смена пароля её обрывает.
    Текущий access-токен доработает до своего естественного истечения
    (обычно час) — это компромисс, чтобы не разлогинивать самого
    пользователя посреди смены пароля.
    """
    if not verify_password(data.current_password, current_user.hashed_password):
        raise HTTPException(400, "Текущий пароль указан неверно")

    current_user.hashed_password = hash_password(data.new_password)
    revoke_all_refresh_tokens(db, current_user.id)
    db.commit()
    return {"ok": True}


@app.post("/auth/forgot-password", response_model=ForgotPasswordResponse)
@limiter.limit(FORGOT_PASSWORD_RATE_LIMIT)
def forgot_password(request: Request, data: ForgotPasswordRequest, db: Session = Depends(get_db)):
    """
    Запрашивает восстановление пароля. ВСЕГДА возвращает одинаковый ответ
    независимо от того, существует ли аккаунт с этим email — иначе по
    разнице в ответе можно было бы проверять, какие email зарегистрированы
    в системе (user enumeration).

    Вне продакшена (ENVIRONMENT != production) дополнительно возвращает
    сам токен восстановления в ответе — тестировать флоу локально без
    настоящего email-провайдера (см. app/email.py, который пока только
    печатает письмо в лог, а не отправляет).
    """
    user = db.query(User).filter(User.email == data.email).first()

    generic_response = ForgotPasswordResponse(
        message="Если аккаунт с таким email существует, на него отправлена ссылка для восстановления пароля"
    )

    if user is None:
        return generic_response

    raw_token = create_password_reset_token(db, user.id)
    db.commit()

    reset_url = f"{FRONTEND_BASE_URL}/reset-password?token={raw_token}"

    try:
        send_password_reset_email(user.email, reset_url)
    except EmailNotConfiguredError:
        # В проде это должно было отсечься на старте приложения
        # (assert_production_safe), но подстрахуемся и здесь.
        raise HTTPException(500, "Отправка email временно недоступна — попробуй позже")

    if ENVIRONMENT != "production":
        generic_response.dev_reset_token = raw_token

    return generic_response


@app.post("/auth/reset-password")
def reset_password(data: ResetPasswordRequest, db: Session = Depends(get_db)):
    """Завершает восстановление пароля по токену из /auth/forgot-password."""
    user = consume_password_reset_token(db, data.token)
    user.hashed_password = hash_password(data.new_password)
    revoke_all_refresh_tokens(db, user.id)
    db.commit()
    return {"ok": True}


@app.get("/auth/me", response_model=UserOut)
def read_current_user(current_user: User = Depends(get_current_user)):
    return current_user


@app.delete("/auth/me")
def delete_own_account(
    data: DeleteAccountRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Полное и необратимое удаление собственного аккаунта — требует пароль
    ещё раз (защита от случайного/чужого вызова через перехваченный
    access-токен, оставленную открытой сессию и т.п.). Каскадно удаляет
    ВСЁ: видео, моменты, субтитры, дорожки/клипы, подключённые соцаккаунты,
    задачи публикации, черновики хештегов, проекты — см. cascade="all,
    delete-orphan" на соответствующих relationship в app/models.py.

    Файлы на диске (видео, баннеры, аудио/видео-клипы) НЕ удаляются этим
    эндпоинтом — только записи в БД. Это осознанный компромисс: массовое
    удаление потенциально большого числа файлов синхронно внутри HTTP-
    запроса может занять непредсказуемо долго. См. TODO в README.
    """
    if not verify_password(data.current_password, current_user.hashed_password):
        raise HTTPException(400, "Пароль указан неверно")

    db.delete(current_user)
    db.commit()
    return {"ok": True}


# ---------- Видео ----------

@app.post("/videos/upload", response_model=UploadResponse)
def upload_video(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"Неподдерживаемый формат файла: {ext}")

    video_id = str(uuid.uuid4())
    dest_path = UPLOADS_DIR / f"{video_id}{ext}"

    with dest_path.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    try:
        # Длительность и дневная квота проверяются ДО создания записи в БД —
        # если что-то не проходит, файл с диска удаляется, ничего не остаётся
        # в "подвешенном" состоянии.
        duration = billing.get_video_duration_seconds(str(dest_path))
        billing.ensure_duration_allowed(duration)
        paid_with_coins = billing.ensure_cut_allowed(db, current_user)
    except HTTPException:
        dest_path.unlink(missing_ok=True)
        raise

    video = Video(
        id=video_id,
        owner_id=current_user.id,
        filename=file.filename,
        filepath=str(dest_path),
        duration_seconds=duration,
        status=VideoStatus.UPLOADED,
    )
    db.add(video)
    db.commit()
    db.refresh(video)
    db.refresh(current_user)

    # Запускаем обработку в фоне (Celery в облачном режиме, локальный
    # пул потоков в desktop). dispatch() сам по себе может упасть СИНХРОННО
    # прямо здесь — например, если RUNNER_MODE каким-то образом не долетел
    # до "local" в desktop-сборке и код пытается достучаться до
    # несуществующего Celery-брокера, или задача не зарегистрирована для
    # локального режима. Video-запись уже закоммичена выше — без этого
    # try/except такая ошибка ушла бы наверх как 500 и оставила бы видео
    # висеть в статусе "uploaded" НАВСЕГДА (единственное место, где
    # ошибка могла произойти ДО входа в try/except внутри самой задачи —
    # см. app/tasks.py::_process_video_core, который сам ловит всё
    # остальное и всегда переводит в FAILED).
    try:
        dispatch(process_video, video.id)
    except Exception as e:
        video.status = VideoStatus.FAILED
        video.error_message = f"Не удалось поставить видео в очередь на обработку: {e}"
        db.commit()
        db.refresh(video)

    used_today = billing.count_cuts_today(db, current_user)
    limit = billing.daily_cut_limit(current_user)
    remaining = max(0, limit - used_today)

    return UploadResponse(
        video=video,
        paid_with_coins=paid_with_coins,
        coins_spent=billing.EXTRA_CUT_COST_COINS if paid_with_coins else 0,
        remaining_free_cuts_today=remaining,
    )


@app.get("/videos", response_model=list[VideoListItem])
def list_videos(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return (
        db.query(Video)
        .filter(Video.owner_id == current_user.id)
        .order_by(Video.created_at.desc())
        .all()
    )


def _get_owned_video(video_id: str, db: Session, current_user: User) -> Video:
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        raise HTTPException(404, "Видео не найдено")
    if video.owner_id != current_user.id:
        # 404, а не 403 — не раскрываем существование чужих видео
        raise HTTPException(404, "Видео не найдено")
    return video


@app.get("/videos/{video_id}", response_model=VideoOut)
def get_video(video_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return _get_owned_video(video_id, db, current_user)


@app.get("/videos/{video_id}/moments", response_model=list[MomentOut])
def get_video_moments(video_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    video = _get_owned_video(video_id, db, current_user)
    return video.moments


_VIDEO_MEDIA_TYPES = {
    ".mp4": "video/mp4", ".mov": "video/quicktime", ".mkv": "video/x-matroska",
    ".avi": "video/x-msvideo", ".webm": "video/webm",
}
_IMAGE_MEDIA_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}


@app.get("/videos/{video_id}/file")
def get_video_file(video_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_media_user)):
    """
    Отдаёт исходный видеофайл — для живого предпросмотра в редакторе
    (тег <video> на фронтенде). Авторизация через get_media_user (токен
    в query-параметре, см. app/auth.py) — <video> не может слать заголовки.

    Честное ограничение: браузер умеет проигрывать нативно только mp4/webm.
    Если пользователь загрузил .mkv/.avi — сам файл отдастся корректно,
    но <video> в браузере скорее всего не сможет его воспроизвести
    (это ограничение самого браузера, не бэкенда).
    """
    video = _get_owned_video(video_id, db, current_user)
    ext = Path(video.filepath).suffix.lower()
    media_type = _VIDEO_MEDIA_TYPES.get(ext, "application/octet-stream")
    return FileResponse(video.filepath, media_type=media_type)


@app.get("/videos/{video_id}/thumbnail")
def get_video_thumbnail(video_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_media_user)):
    """
    Кадр для карточки в списке "Мои видео" — берём не самый первый кадр
    (часто чёрный/титульный), а 10% от длительности, но не дальше 2с,
    чтобы не тянуть кадр из середины ещё не обработанного длинного видео.
    Работает независимо от статуса обработки — нужен только сам файл на
    диске, транскрипция/поиск моментов ни при чём.
    """
    video = _get_owned_video(video_id, db, current_user)
    time_seconds = min(2.0, (video.duration_seconds or 10.0) * 0.1)
    try:
        thumb_path = get_or_create_thumbnail(video.filepath, time_seconds)
    except ThumbnailError as e:
        raise HTTPException(500, str(e))
    return FileResponse(thumb_path, media_type="image/jpeg")


@app.get("/moments/{moment_id}/banner/file")
def get_banner_file(moment_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_media_user)):
    moment = _get_owned_moment(moment_id, db, current_user)
    if not moment.banner_path:
        raise HTTPException(404, "У момента нет баннера")
    ext = Path(moment.banner_path).suffix.lower()
    media_type = _IMAGE_MEDIA_TYPES.get(ext, "application/octet-stream")
    return FileResponse(moment.banner_path, media_type=media_type)


@app.get("/moments/{moment_id}/thumbnail")
def get_moment_thumbnail(moment_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_media_user)):
    """Кадр видео в момент времени moment.start — для карточки момента
    в ленте (вместо чёрного прямоугольника-заглушки)."""
    moment = _get_owned_moment(moment_id, db, current_user)
    try:
        thumb_path = get_or_create_thumbnail(moment.video.filepath, moment.start)
    except ThumbnailError as e:
        raise HTTPException(500, str(e))
    return FileResponse(thumb_path, media_type="image/jpeg")


@app.get("/clips/{clip_id}/thumbnail")
def get_clip_thumbnail(clip_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_media_user)):
    """Кадр ИЗ ФАЙЛА КЛИПА (не из основного видео) в момент trim_start —
    только для video-клипов (PIP-наложений), у аудио превью не имеет смысла."""
    clip = _get_owned_clip(clip_id, db, current_user)
    try:
        thumb_path = get_or_create_thumbnail(clip.file_path, clip.trim_start)
    except ThumbnailError as e:
        raise HTTPException(500, str(e))
    return FileResponse(thumb_path, media_type="image/jpeg")


def _get_owned_moment(moment_id: str, db: Session, current_user: User) -> Moment:
    moment = db.query(Moment).filter(Moment.id == moment_id).first()
    if not moment or moment.video.owner_id != current_user.id:
        raise HTTPException(404, "Момент не найден")
    return moment


@app.patch("/moments/{moment_id}", response_model=MomentOut)
def update_moment(
    moment_id: str,
    update: MomentUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    moment = _get_owned_moment(moment_id, db, current_user)

    for field, value in update.model_dump(exclude_unset=True).items():
        setattr(moment, field, value)

    db.commit()
    db.refresh(moment)
    return moment


@app.delete("/moments/{moment_id}")
def delete_moment(moment_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    moment = _get_owned_moment(moment_id, db, current_user)
    db.delete(moment)
    db.commit()
    return {"ok": True}


@app.post("/moments/{moment_id}/subtitles", response_model=SubtitleOut, status_code=201)
def create_subtitle(
    moment_id: str,
    data: SubtitleCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Добавляет новую реплику субтитров к моменту — например, если whisper
    что-то пропустил при транскрипции. order_index проставляется
    автоматически по позиции start среди уже существующих реплик, чтобы
    новая строка встала в хронологически правильное место, а не всегда
    в конец списка.
    """
    moment = _get_owned_moment(moment_id, db, current_user)

    existing = sorted(moment.subtitles, key=lambda s: s.start)
    order_index = sum(1 for s in existing if s.start <= data.start)

    subtitle = Subtitle(moment_id=moment.id, start=data.start, end=data.end, text=data.text, order_index=order_index)
    db.add(subtitle)

    # раздвигаем order_index у реплик после вставленной, чтобы порядок
    # остался последовательным (0,1,2,...) без дырок и дублей
    for s in existing[order_index:]:
        s.order_index += 1

    db.commit()
    db.refresh(subtitle)
    return subtitle


@app.patch("/subtitles/{subtitle_id}", response_model=SubtitleOut)
def update_subtitle(
    subtitle_id: str,
    update: SubtitleUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    subtitle = db.query(Subtitle).filter(Subtitle.id == subtitle_id).first()
    if not subtitle or subtitle.moment.video.owner_id != current_user.id:
        raise HTTPException(404, "Субтитр не найден")

    for field, value in update.model_dump(exclude_unset=True).items():
        setattr(subtitle, field, value)

    db.commit()
    db.refresh(subtitle)
    return subtitle


@app.delete("/subtitles/{subtitle_id}")
def delete_subtitle(subtitle_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    subtitle = db.query(Subtitle).filter(Subtitle.id == subtitle_id).first()
    if not subtitle or subtitle.moment.video.owner_id != current_user.id:
        raise HTTPException(404, "Субтитр не найден")
    db.delete(subtitle)
    db.commit()
    return {"ok": True}





# ---------- Подключённые аккаунты платформ ----------

@app.get("/platforms")
def list_platforms():
    """
    Список платформ публикации с флагом реальной доступности —
    фронтенд показывает "скоро" вместо кнопки подключения для тех,
    что помечены enabled=false.
    """
    from app.config import PLATFORM_ENABLED
    return [{"platform": p.value, "enabled": PLATFORM_ENABLED[p.value]} for p in Platform]


@app.get("/social-accounts", response_model=list[SocialAccountOut])
def list_social_accounts(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return db.query(SocialAccount).filter(SocialAccount.owner_id == current_user.id).all()


@app.get("/social-accounts/{platform}/connect")
def connect_social_account(platform: Platform, current_user: User = Depends(get_current_user)):
    """
    Возвращает ссылку, на которую фронтенд должен отправить пользователя
    (открыть в новом окне/вкладке), чтобы он вошёл на платформе и разрешил
    доступ. После подтверждения платформа сама редиректнет на /callback.
    """
    from app.config import PLATFORM_ENABLED
    if not PLATFORM_ENABLED[platform.value]:
        raise HTTPException(503, f"Публикация в {platform.value} пока недоступна — скоро откроем")

    url = oauth.get_authorize_url(platform, current_user.id)
    return {"authorize_url": url}


@app.get("/social-accounts/{platform}/callback")
def social_account_callback(platform: Platform, code: str, state: str, db: Session = Depends(get_db)):
    """
    Редирект-эндпоинт, на который платформа отправляет браузер пользователя
    после подтверждения доступа. Не требует Authorization-заголовка — личность
    пользователя восстанавливается из подписанного `state`.
    """
    try:
        user_id = oauth.verify_state(state, platform.value)
        token_data = oauth.exchange_code(platform, code)
    except oauth.OAuthError as e:
        raise HTTPException(400, str(e))

    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(404, "Пользователь не найден")

    existing = (
        db.query(SocialAccount)
        .filter(
            SocialAccount.owner_id == user_id,
            SocialAccount.platform == platform,
            SocialAccount.platform_account_id == token_data["platform_account_id"],
        )
        .first()
    )

    if existing:
        existing.access_token = token_data["access_token"]
        if token_data.get("refresh_token"):
            existing.refresh_token = token_data["refresh_token"]
        existing.token_expires_at = token_data["expires_at"]
        existing.platform_username = token_data["platform_username"] or existing.platform_username
    else:
        # Новый аккаунт — проверяем лимит тарифа, при исчерпании списываем
        # монеты за докупленный слот (см. app/billing.py)
        billing.ensure_account_slot_available(db, user, platform)
        db.add(SocialAccount(
            owner_id=user_id,
            platform=platform,
            platform_account_id=token_data["platform_account_id"],
            platform_username=token_data["platform_username"],
            access_token=token_data["access_token"],
            refresh_token=token_data.get("refresh_token"),
            token_expires_at=token_data["expires_at"],
        ))

    db.commit()

    # На реальном фронтенде тут лучше редиректить на страницу
    # "аккаунт подключён" в самом приложении, а не отдавать голый JSON.
    return RedirectResponse(url=f"{FRONTEND_BASE_URL}/accounts?connected={platform.value}")


@app.delete("/social-accounts/{account_id}")
def disconnect_social_account(account_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    account = db.query(SocialAccount).filter(SocialAccount.id == account_id).first()
    if not account or account.owner_id != current_user.id:
        raise HTTPException(404, "Аккаунт не найден")
    db.delete(account)
    db.commit()
    return {"ok": True}


# ---------- Баннер и аудио-оверлей момента ----------

BANNER_ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
AUDIO_ALLOWED_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".ogg"}


@app.post("/moments/{moment_id}/banner", response_model=MomentOut)
def upload_banner(
    moment_id: str, file: UploadFile = File(...),
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    moment = _get_owned_moment(moment_id, db, current_user)

    ext = Path(file.filename).suffix.lower()
    if ext not in BANNER_ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"Неподдерживаемый формат изображения: {ext}")

    if moment.banner_path:
        Path(moment.banner_path).unlink(missing_ok=True)  # чистим предыдущий баннер при замене

    dest_path = UPLOADS_DIR / f"{moment.id}_banner{ext}"
    with dest_path.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    moment.banner_path = str(dest_path)
    db.commit()
    db.refresh(moment)
    return moment


@app.delete("/moments/{moment_id}/banner", response_model=MomentOut)
def delete_banner(moment_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    moment = _get_owned_moment(moment_id, db, current_user)
    if moment.banner_path:
        Path(moment.banner_path).unlink(missing_ok=True)
        moment.banner_path = None
        db.commit()
        db.refresh(moment)
    return moment


@app.post("/moments/{moment_id}/audio", response_model=MomentOut)
def upload_audio_overlay(
    moment_id: str, file: UploadFile = File(...),
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    moment = _get_owned_moment(moment_id, db, current_user)

    ext = Path(file.filename).suffix.lower()
    if ext not in AUDIO_ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"Неподдерживаемый формат аудио: {ext}")

    if moment.audio_path:
        Path(moment.audio_path).unlink(missing_ok=True)  # чистим предыдущий оверлей при замене

    dest_path = UPLOADS_DIR / f"{moment.id}_audio{ext}"
    with dest_path.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    audio_duration = billing.get_video_duration_seconds(str(dest_path))
    moment_duration = moment.end - moment.start

    moment.audio_path = str(dest_path)
    moment.audio_duration = audio_duration
    moment.audio_trim_start = 0.0
    moment.audio_trim_end = min(audio_duration, moment_duration)
    db.commit()
    db.refresh(moment)
    return moment


@app.delete("/moments/{moment_id}/audio", response_model=MomentOut)
def delete_audio_overlay(moment_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    moment = _get_owned_moment(moment_id, db, current_user)
    if moment.audio_path:
        Path(moment.audio_path).unlink(missing_ok=True)
        moment.audio_path = None
        moment.audio_duration = None
        moment.audio_trim_start = None
        moment.audio_trim_end = None
        db.commit()
        db.refresh(moment)
    return moment


@app.post("/moments/{moment_id}/tracks", response_model=TrackOut, status_code=201)
def create_track(
    moment_id: str, data: TrackCreate,
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    """Создаёт новую дорожку (video или audio) внутри момента — пока без
    клипов, файл загружается отдельным вызовом POST /tracks/{id}/clips."""
    moment = _get_owned_moment(moment_id, db, current_user)

    try:
        track_type = TrackType(data.type)
    except ValueError:
        raise HTTPException(400, f"Неизвестный тип дорожки: {data.type}")

    max_order = max((t.order_index for t in moment.tracks), default=-1)
    track = Track(moment_id=moment.id, type=track_type, name=data.name, order_index=max_order + 1)
    db.add(track)
    db.commit()
    db.refresh(track)
    return track


def _get_owned_track(track_id: str, db: Session, current_user: User) -> Track:
    track = db.query(Track).filter(Track.id == track_id).first()
    if not track or track.moment.video.owner_id != current_user.id:
        raise HTTPException(404, "Дорожка не найдена")
    return track


@app.delete("/tracks/{track_id}")
def delete_track(track_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    track = _get_owned_track(track_id, db, current_user)
    for clip in track.clips:
        Path(clip.file_path).unlink(missing_ok=True)
    db.delete(track)
    db.commit()
    return {"ok": True}


CLIP_ALLOWED_EXTENSIONS = AUDIO_ALLOWED_EXTENSIONS | {".mp4", ".mov", ".mkv", ".webm"}


@app.post("/tracks/{track_id}/clips", response_model=ClipOut, status_code=201)
def upload_clip(
    track_id: str, file: UploadFile = File(...),
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    """
    Загружает файл (видео или аудио, в зависимости от типа дорожки) и
    размещает его клипом на дорожке. По умолчанию клип ставится в начало
    момента (position_start=0) и использует файл с начала на всю его
    длину (или на длину момента, если файл длиннее).
    """
    track = _get_owned_track(track_id, db, current_user)
    moment = track.moment

    ext = Path(file.filename).suffix.lower()
    if ext not in CLIP_ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"Неподдерживаемый формат файла: {ext}")

    dest_path = UPLOADS_DIR / f"{track.id}_{len(track.clips)}_clip{ext}"
    with dest_path.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    try:
        source_duration = billing.get_video_duration_seconds(str(dest_path))
    except HTTPException:
        dest_path.unlink(missing_ok=True)
        raise

    moment_duration = moment.end - moment.start
    clip_len = min(source_duration, moment_duration)

    clip = Clip(
        track_id=track.id,
        file_path=str(dest_path),
        source_duration=source_duration,
        position_start=0.0,
        position_end=clip_len,
        trim_start=0.0,
        trim_end=clip_len,
    )
    db.add(clip)
    db.commit()
    db.refresh(clip)
    return clip


def _get_owned_clip(clip_id: str, db: Session, current_user: User) -> Clip:
    clip = db.query(Clip).filter(Clip.id == clip_id).first()
    if not clip or clip.track.moment.video.owner_id != current_user.id:
        raise HTTPException(404, "Клип не найден")
    return clip


@app.patch("/clips/{clip_id}", response_model=ClipOut)
def update_clip(
    clip_id: str, data: ClipUpdate,
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    clip = _get_owned_clip(clip_id, db, current_user)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(clip, field, value)
    db.commit()
    db.refresh(clip)
    return clip


@app.delete("/clips/{clip_id}")
def delete_clip(clip_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    clip = _get_owned_clip(clip_id, db, current_user)
    Path(clip.file_path).unlink(missing_ok=True)
    db.delete(clip)
    db.commit()
    return {"ok": True}


# ---------- Рендер ----------

@app.post("/moments/{moment_id}/render", response_model=MomentOut)
def render_moment_endpoint(moment_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """
    Запускает рендер момента (ffmpeg): вырезка сегмента, вшитые субтитры,
    наложение баннера. Момент должен быть в статусе approved — то есть
    пользователь уже отредактировал таймкоды/субтитры/баннер в редакторе
    и подтвердил, что этот момент готов. Статус меняется на rendered
    после успешного завершения фоновой задачи — прогресс можно отслеживать
    через GET /videos/{video_id}/moments (или отдельный GET на сам момент,
    если добавишь его на фронте).
    """
    moment = _get_owned_moment(moment_id, db, current_user)

    if moment.status != MomentStatus.APPROVED:
        raise HTTPException(
            400,
            f"Момент должен быть в статусе 'approved' для рендера (сейчас: {moment.status.value}). "
            f"Сначала одобри его: PATCH /moments/{{id}} {{'status': 'approved'}}",
        )

    dispatch(render_moment_task, moment.id)
    return moment


# ---------- Рекомендованные хештеги ----------

@app.post("/moments/{moment_id}/suggest-hashtags", response_model=list[str])
def suggest_hashtags_endpoint(moment_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """
    Подбирает хештеги под содержимое момента через Claude API — берёт текст
    субтитров и краткое описание (hook_line/reason из find_moments), просит
    Claude предложить релевантные теги. Синхронный вызов (не через очередь) —
    занимает пару секунд, вызывается прямо из модалки публикации по кнопке.

    Ничего не сохраняет сам — просто возвращает список, дальше пользователь
    решает, использовать эти теги как есть, отредактировать или сохранить
    как черновик (POST /hashtag-drafts).
    """
    moment = _get_owned_moment(moment_id, db, current_user)

    subtitles_text = " ".join(s.text for s in sorted(moment.subtitles, key=lambda s: s.order_index))
    context_parts = [p for p in [moment.hook_line, moment.reason, subtitles_text] if p]

    if not context_parts:
        raise HTTPException(400, "У момента нет ни субтитров, ни описания — нечего анализировать")

    try:
        return suggest_hashtags("\n".join(context_parts))
    except Exception as e:
        raise HTTPException(502, f"Не удалось получить рекомендации от Claude: {e}")


# ---------- Публикация ----------

@app.post("/moments/{moment_id}/publish", response_model=list[PublishTargetOut])
def publish_moment(
    moment_id: str,
    request: PublishRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Ставит момент в очередь на публикацию на одной или нескольких платформах
    сразу — по одному PublishTarget на каждый выбранный social_account_id.
    Момент должен быть уже одобрен (status=approved) и отрендерен
    (output_path заполнен рендер-задачей ffmpeg).
    """
    moment = _get_owned_moment(moment_id, db, current_user)

    if not moment.output_path:
        raise HTTPException(400, "Момент ещё не отрендерен — сначала запусти рендер")

    accounts = (
        db.query(SocialAccount)
        .filter(SocialAccount.id.in_(request.social_account_ids), SocialAccount.owner_id == current_user.id)
        .all()
    )
    found_ids = {a.id for a in accounts}
    missing = set(request.social_account_ids) - found_ids
    if missing:
        raise HTTPException(404, f"Аккаунты не найдены или не принадлежат тебе: {missing}")

    if request.uniqueize:
        # Считается ЗА НАРЕЗКУ (один этот вызов), а не за количество
        # аккаунтов ниже — поэтому проверяем и списываем квоту ОДИН раз
        # здесь, до создания PublishTarget на каждый аккаунт.
        billing.ensure_uniqueize_allowed(db, current_user, moment.id)

    targets = []
    for account in accounts:
        target = PublishTarget(
            moment_id=moment.id,
            social_account_id=account.id,
            platform=account.platform,
            status=PublishStatus.QUEUED,
            scheduled_at=request.scheduled_at,
            title=request.title or moment.hook_line,
            description=request.description,
            hashtags=request.hashtags,
            uniqueize=request.uniqueize,
        )
        db.add(target)
        db.flush()
        targets.append(target)

        # публикуем сразу, только если не задано время в будущем;
        # запланированные публикации забирает Celery Beat (см. README)
        if request.scheduled_at is None:
            dispatch(publish_target_task, target.id)

    db.commit()
    for t in targets:
        db.refresh(t)
    return targets


@app.get("/moments/{moment_id}/publish-targets", response_model=list[PublishTargetOut])
def get_publish_targets(moment_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    moment = _get_owned_moment(moment_id, db, current_user)
    return moment.publish_targets


# ---------- Черновики хештегов ----------

@app.get("/hashtag-drafts", response_model=list[HashtagDraftOut])
def list_hashtag_drafts(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return (
        db.query(HashtagDraft)
        .filter(HashtagDraft.user_id == current_user.id)
        .order_by(HashtagDraft.created_at.desc())
        .all()
    )


@app.post("/hashtag-drafts", response_model=HashtagDraftOut, status_code=201)
def create_hashtag_draft(data: HashtagDraftCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    draft = HashtagDraft(user_id=current_user.id, name=data.name, hashtags=data.hashtags)
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return draft


@app.delete("/hashtag-drafts/{draft_id}")
def delete_hashtag_draft(draft_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    draft = db.query(HashtagDraft).filter(HashtagDraft.id == draft_id).first()
    if not draft or draft.user_id != current_user.id:
        raise HTTPException(404, "Черновик не найден")
    db.delete(draft)
    db.commit()
    return {"ok": True}


# ---------- Проекты (личные закладки на видео/моменты) ----------

def _get_owned_project(project_id: str, db: Session, current_user: User) -> Project:
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project or project.user_id != current_user.id:
        raise HTTPException(404, "Проект не найден")
    return project


@app.post("/projects", response_model=ProjectOut, status_code=201)
def create_project(data: ProjectCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Сохраняет видео (целиком, moment_id=None) или конкретный момент как
    личный проект — "отложить и вернуться позже", с собственной заметкой."""
    video = db.query(Video).filter(Video.id == data.video_id).first()
    if not video or video.owner_id != current_user.id:
        raise HTTPException(404, "Видео не найдено")

    if data.moment_id is not None:
        moment = db.query(Moment).filter(Moment.id == data.moment_id).first()
        if not moment or moment.video_id != video.id:
            raise HTTPException(404, "Момент не найден в этом видео")

    project = Project(
        user_id=current_user.id,
        video_id=data.video_id,
        moment_id=data.moment_id,
        title=data.title,
        note=data.note,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@app.get("/projects", response_model=list[ProjectOut])
def list_projects(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return (
        db.query(Project)
        .filter(Project.user_id == current_user.id)
        .order_by(Project.updated_at.desc())
        .all()
    )


@app.get("/projects/{project_id}", response_model=ProjectOut)
def get_project(project_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return _get_owned_project(project_id, db, current_user)


@app.patch("/projects/{project_id}", response_model=ProjectOut)
def update_project(
    project_id: str, data: ProjectUpdate,
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    project = _get_owned_project(project_id, db, current_user)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(project, field, value)
    db.commit()
    db.refresh(project)
    return project


@app.delete("/projects/{project_id}")
def delete_project(project_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    project = _get_owned_project(project_id, db, current_user)
    db.delete(project)
    db.commit()
    return {"ok": True}


# ---------- Биллинг ----------

@app.get("/billing/me", response_model=BillingMe)
def billing_me(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    platform_usage = [
        PlatformUsage(
            platform=p.value,
            connected=billing.count_connected_accounts(db, current_user, p),
            limit=billing.account_slot_limit(db, current_user, p),
        )
        for p in Platform
    ]
    return BillingMe(
        subscription_tier=current_user.subscription_tier.value,
        subscription_expires_at=current_user.subscription_expires_at,
        coin_balance=current_user.coin_balance,
        cuts_used_today=billing.count_cuts_today(db, current_user),
        cuts_daily_limit=billing.daily_cut_limit(current_user),
        uniqueize_used_today=billing.count_uniqueize_usages_today(db, current_user),
        uniqueize_daily_limit=billing.daily_uniqueize_limit(current_user),
        platform_usage=platform_usage,
        same_ip_free_signups_last_7d=billing.count_free_tier_signups_from_ip(db, current_user.registration_ip),
    )


# --- Начисление монет и смена тарифа ---
#
# В проде эти операции ДОЛЖНЫ триггериться исключительно вебхуком платёжного
# провайдера (ЮKassa/CloudPayments/Stripe — в зависимости от того, кого
# подключишь) после подтверждённой оплаты, с проверкой подписи запроса.
# Ниже — заглушка вебхука с проверкой общего секрета (замени на реальную
# HMAC-проверку подписи конкретного провайдера перед продакшеном) и
# dev-only эндпоинты для ручного тестирования без реальной оплаты —
# они физически отключены при ENVIRONMENT=production.

@app.post("/billing/coins/webhook")
def coins_webhook(
    payload: dict,
    db: Session = Depends(get_db),
):
    """
    Вызывается платёжным провайдером после успешной оплаты монет.
    Ожидаемый payload: {"webhook_secret": "...", "user_id": "...", "amount": 500, "order_id": "..."}
    ЗАМЕНИТЬ webhook_secret на реальную проверку подписи провайдера перед продакшеном.
    """
    from app.config import PAYMENT_WEBHOOK_SECRET

    if not PAYMENT_WEBHOOK_SECRET or payload.get("webhook_secret") != PAYMENT_WEBHOOK_SECRET:
        raise HTTPException(401, "Неверный webhook_secret")

    user = db.query(User).filter(User.id == payload["user_id"]).first()
    if not user:
        raise HTTPException(404, "Пользователь не найден")

    billing.credit_coins(
        db, user, int(payload["amount"]), CoinTransactionReason.PURCHASE,
        note=f"order_id={payload.get('order_id', '')}",
    )
    db.commit()
    return {"ok": True, "new_balance": user.coin_balance}


@app.post("/billing/subscription/webhook")
def subscription_webhook(payload: dict, db: Session = Depends(get_db)):
    """
    Вызывается платёжным провайдером после подтверждённой оплаты подписки.
    Ожидаемый payload: {"webhook_secret": "...", "user_id": "...", "tier": "tier2", "expires_at": "2026-08-13T00:00:00"}
    """
    from app.config import PAYMENT_WEBHOOK_SECRET

    if not PAYMENT_WEBHOOK_SECRET or payload.get("webhook_secret") != PAYMENT_WEBHOOK_SECRET:
        raise HTTPException(401, "Неверный webhook_secret")

    user = db.query(User).filter(User.id == payload["user_id"]).first()
    if not user:
        raise HTTPException(404, "Пользователь не найден")

    try:
        tier = SubscriptionTier(payload["tier"])
    except ValueError:
        raise HTTPException(400, f"Неизвестный тариф: {payload['tier']}")

    user.subscription_tier = tier
    user.subscription_expires_at = (
        datetime.fromisoformat(payload["expires_at"]) if payload.get("expires_at") else None
    )
    db.commit()
    return {"ok": True, "tier": user.subscription_tier.value}


if ENVIRONMENT != "production":
    @app.post("/billing/dev/grant-coins", response_model=BillingMe)
    def dev_grant_coins(
        grant: CoinGrant,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
    ):
        """Только для локальной разработки — начисляет монеты себе без оплаты.
        Недоступно при ENVIRONMENT=production."""
        billing.credit_coins(db, current_user, grant.amount, CoinTransactionReason.PURCHASE, note=grant.note or "dev grant")
        db.commit()
        return billing_me(db, current_user)

    @app.post("/billing/dev/set-tier", response_model=BillingMe)
    def dev_set_tier(
        data: TierSet,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
    ):
        """Только для локальной разработки — меняет свой тариф без оплаты.
        Недоступно при ENVIRONMENT=production."""
        try:
            current_user.subscription_tier = SubscriptionTier(data.tier)
        except ValueError:
            raise HTTPException(400, f"Неизвестный тариф: {data.tier}")
        current_user.subscription_expires_at = data.expires_at
        db.commit()
        return billing_me(db, current_user)


# ---------- Настройки desktop-версии ----------
# Только для RUNNER_MODE=local: в облачном режиме ANTHROPIC_API_KEY задаётся
# через переменную окружения при деплое, экран настроек ему не нужен и
# сохранение в локальный файл всё равно не подхватилось бы (см.
# app/config.py::get_anthropic_api_key).

@app.get("/settings/anthropic-key")
def get_anthropic_key_status(current_user: User = Depends(get_current_user)):
    """Не возвращает сам ключ — только флаг, задан ли он, чтобы фронтенд
    показал "ключ сохранён" вместо пустого поля (и не выводил секрет обратно
    на экран)."""
    if RUNNER_MODE != "local":
        raise HTTPException(404, "Доступно только в desktop-режиме")
    from app.config import get_anthropic_api_key
    return {"is_set": bool(get_anthropic_api_key())}


@app.put("/settings/anthropic-key")
def set_anthropic_key(payload: dict, current_user: User = Depends(get_current_user)):
    if RUNNER_MODE != "local":
        raise HTTPException(404, "Доступно только в desktop-режиме")
    api_key = (payload.get("api_key") or "").strip()
    if not api_key:
        raise HTTPException(400, "Ключ не может быть пустым")
    from app import local_config
    local_config.set_anthropic_api_key(api_key)
    return {"is_set": True}


@app.get("/system/whisper-status")
def whisper_status(current_user: User = Depends(get_current_user)):
    """Пока faster-whisper качает модель распознавания речи при первом
    использовании (модель НЕ вшита в инсталлятор), фронтенд поллит этот
    эндпоинт, чтобы показать "скачивается модель" вместо зависшего спиннера
    транскрипции без объяснений."""
    from pipeline.transcribe import get_whisper_download_state
    return get_whisper_download_state()


@app.get("/health")
def health():
    return {"status": "ok"}
