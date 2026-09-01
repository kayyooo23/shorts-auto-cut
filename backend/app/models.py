"""
Модели БД.

Video          — загруженный эпизод целиком, проходит стадии обработки.
Moment         — найденный ИИ фрагмент для нарезки на шортс.
Subtitle       — отдельная реплика субтитров внутри момента (редактируемая построчно).
SocialAccount  — подключённый аккаунт пользователя на внешней платформе (OAuth).
PublishTarget  — задача "опубликовать этот момент на этой платформе/аккаунте".
                 Один момент может иметь несколько PublishTarget — по одному
                 на каждую выбранную платформу.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import Column, String, Float, Integer, Text, DateTime, ForeignKey, Enum, Boolean
from sqlalchemy.orm import relationship

from app.database import Base


def gen_uuid() -> str:
    return str(uuid.uuid4())


class VideoStatus(str, enum.Enum):
    UPLOADED = "uploaded"
    TRANSCRIBING = "transcribing"
    FINDING_MOMENTS = "finding_moments"
    READY = "ready"          # моменты найдены, ждут ревью пользователя
    FAILED = "failed"


class MomentStatus(str, enum.Enum):
    PENDING = "pending"       # ждёт решения пользователя
    APPROVED = "approved"     # одобрен, можно рендерить
    REJECTED = "rejected"
    RENDERED = "rendered"     # ffmpeg отработал, файл готов к публикации


class Platform(str, enum.Enum):
    YOUTUBE = "youtube"
    TIKTOK = "tiktok"
    INSTAGRAM = "instagram"


class PublishStatus(str, enum.Enum):
    QUEUED = "queued"         # ждёт своего часа (scheduled_at) или публикации прямо сейчас
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    FAILED = "failed"


class SubscriptionTier(str, enum.Enum):
    FREE = "free"
    TIER2 = "tier2"
    TIER3 = "tier3"


class CoinTransactionReason(str, enum.Enum):
    PURCHASE = "purchase"              # пополнение баланса (оплата деньгами)
    EXTRA_CUT = "extra_cut"            # списание за нарезку сверх дневного лимита тарифа
    EXTRA_ACCOUNT_SLOT = "extra_account_slot"  # списание за доп. слот подключения аккаунта
    REFUND = "refund"                  # возврат (например, если рендер/публикация не удались)


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=gen_uuid)
    email = Column(String, unique=True, nullable=False, index=True)
    hashed_password = Column(String, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    is_admin = Column(Boolean, default=False, nullable=False)  # см. main.py::_bootstrap_admin_account
    created_at = Column(DateTime, default=datetime.utcnow)

    subscription_tier = Column(Enum(SubscriptionTier), default=SubscriptionTier.FREE, nullable=False)
    subscription_expires_at = Column(DateTime, nullable=True)  # null = бессрочно (или FREE-тариф)
    coin_balance = Column(Integer, default=0, nullable=False)
    registration_ip = Column(String, nullable=True)  # см. app/billing.py::flag_shared_ip_signups
    failed_login_attempts = Column(Integer, default=0, nullable=False)
    locked_until = Column(DateTime, nullable=True)  # см. app/auth.py::is_locked_out

    videos = relationship("Video", back_populates="owner", cascade="all, delete-orphan")
    social_accounts = relationship("SocialAccount", back_populates="owner", cascade="all, delete-orphan")
    coin_transactions = relationship("CoinTransaction", back_populates="user", cascade="all, delete-orphan")
    slot_purchases = relationship("AccountSlotPurchase", back_populates="user", cascade="all, delete-orphan")
    refresh_tokens = relationship("RefreshToken", back_populates="user", cascade="all, delete-orphan")
    uniqueize_usages = relationship("UniqueizeUsage", back_populates="user", cascade="all, delete-orphan")
    hashtag_drafts = relationship("HashtagDraft", back_populates="user", cascade="all, delete-orphan")
    password_reset_tokens = relationship("PasswordResetToken", back_populates="user", cascade="all, delete-orphan")
    projects = relationship("Project", back_populates="user", cascade="all, delete-orphan")


class Video(Base):
    __tablename__ = "videos"

    id = Column(String, primary_key=True, default=gen_uuid)
    owner_id = Column(String, ForeignKey("users.id"), nullable=False)
    filename = Column(String, nullable=False)
    filepath = Column(String, nullable=False)
    duration_seconds = Column(Float, nullable=True)  # определяется при загрузке через ffprobe
    status = Column(Enum(VideoStatus), default=VideoStatus.UPLOADED, nullable=False)
    error_message = Column(Text, nullable=True)
    transcript_path = Column(String, nullable=True)  # путь к сохранённому transcript.json
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    owner = relationship("User", back_populates="videos")
    moments = relationship("Moment", back_populates="video", cascade="all, delete-orphan")


class Moment(Base):
    __tablename__ = "moments"

    id = Column(String, primary_key=True, default=gen_uuid)
    video_id = Column(String, ForeignKey("videos.id"), nullable=False)

    start = Column(Float, nullable=False)
    end = Column(Float, nullable=False)
    reason = Column(Text, nullable=True)
    hook_line = Column(String, nullable=True)

    # настройки рендера, задаются пользователем в редакторе
    banner_path = Column(String, nullable=True)
    banner_position = Column(String, default="bottom-right")  # top-left/top-right/bottom-left/bottom-right

    audio_path = Column(String, nullable=True)
    audio_duration = Column(Float, nullable=True)  # длительность исходного файла, секунды
    audio_trim_start = Column(Float, nullable=True)
    audio_trim_end = Column(Float, nullable=True)
    audio_volume = Column(Float, default=1.0, nullable=False)

    # Дополнительные видео/аудио дорожки — см. модели Track/Clip ниже

    status = Column(Enum(MomentStatus), default=MomentStatus.PENDING, nullable=False)
    output_path = Column(String, nullable=True)  # путь к готовому нарезанному файлу (после ffmpeg)

    created_at = Column(DateTime, default=datetime.utcnow)

    video = relationship("Video", back_populates="moments")
    subtitles = relationship("Subtitle", back_populates="moment", cascade="all, delete-orphan")
    publish_targets = relationship("PublishTarget", back_populates="moment", cascade="all, delete-orphan")
    tracks = relationship("Track", back_populates="moment", cascade="all, delete-orphan", order_by="Track.order_index")


class Subtitle(Base):
    __tablename__ = "subtitles"

    id = Column(String, primary_key=True, default=gen_uuid)
    moment_id = Column(String, ForeignKey("moments.id"), nullable=False)

    start = Column(Float, nullable=False)  # относительно начала момента, секунды
    end = Column(Float, nullable=False)
    text = Column(Text, nullable=False)
    order_index = Column(Integer, nullable=False)  # порядок реплики внутри момента

    moment = relationship("Moment", back_populates="subtitles")


class TrackType(str, enum.Enum):
    VIDEO = "video"
    AUDIO = "audio"


class Track(Base):
    """
    Дорожка внутри момента — как трек в Premiere/DaVinci. Может быть
    video (наложение картинки поверх основной, picture-in-picture) или
    audio (звук/музыка поверх оригинальной звуковой дорожки момента).
    Само исходное видео момента (Video.filepath, обрезанное по
    Moment.start/end) — НЕ трек, это всегда базовый нижний слой; треки
    здесь — только ДОПОЛНИТЕЛЬНЫЕ наложения сверху.

    order_index определяет порядок наложения видео-дорожек друг на друга
    (больше — выше/поверх); для аудио влияет только на отображение в UI,
    громкость всех аудио-дорожек просто складывается при смешивании.
    """
    __tablename__ = "tracks"

    id = Column(String, primary_key=True, default=gen_uuid)
    moment_id = Column(String, ForeignKey("moments.id"), nullable=False)
    type = Column(Enum(TrackType), nullable=False)
    order_index = Column(Integer, nullable=False, default=0)
    name = Column(String, nullable=True)  # опциональная подпись дорожки самому себе
    created_at = Column(DateTime, default=datetime.utcnow)

    moment = relationship("Moment", back_populates="tracks")
    clips = relationship("Clip", back_populates="track", cascade="all, delete-orphan", order_by="Clip.position_start")


class Clip(Base):
    """
    Один загруженный файл, размещённый на дорожке.

    position_start/position_end — КОГДА клип звучит/показывается на общей
    шкале МОМЕНТА (0 = начало момента). trim_start/trim_end — КАКОЙ кусок
    ИСХОДНОГО ФАЙЛА используется (файл может быть длиннее, чем то место
    на шкале, куда его поместили).

    Для video-клипов x/y/width/height задают прямоугольник наложения в
    долях кадра (0.0-1.0) — например x=0.6,y=0.05,width=0.35,height=0.35
    это небольшая картинка в правом верхнем углу.
    """
    __tablename__ = "clips"

    id = Column(String, primary_key=True, default=gen_uuid)
    track_id = Column(String, ForeignKey("tracks.id"), nullable=False)

    file_path = Column(String, nullable=False)
    source_duration = Column(Float, nullable=True)  # полная длительность исходного файла — для UI-полосы обрезки

    position_start = Column(Float, nullable=False, default=0.0)
    position_end = Column(Float, nullable=False)
    trim_start = Column(Float, nullable=False, default=0.0)
    trim_end = Column(Float, nullable=False)

    volume = Column(Float, default=1.0, nullable=False)  # только для аудио-клипов

    # только для video-клипов (picture-in-picture), доли кадра 0.0-1.0
    pip_x = Column(Float, default=0.6, nullable=False)
    pip_y = Column(Float, default=0.05, nullable=False)
    pip_width = Column(Float, default=0.35, nullable=False)
    pip_height = Column(Float, default=0.35, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow)

    track = relationship("Track", back_populates="clips")


class SocialAccount(Base):
    """
    Один подключённый аккаунт пользователя на внешней платформе.
    Токены OAuth хранятся здесь — см. ВАЖНО в конце файла про шифрование.
    """
    __tablename__ = "social_accounts"

    id = Column(String, primary_key=True, default=gen_uuid)
    owner_id = Column(String, ForeignKey("users.id"), nullable=False)
    platform = Column(Enum(Platform), nullable=False)

    # данные аккаунта на самой платформе (для отображения в UI — "какой аккаунт подключён")
    platform_account_id = Column(String, nullable=False)
    platform_username = Column(String, nullable=True)

    access_token_encrypted = Column("access_token", Text, nullable=False)
    refresh_token_encrypted = Column("refresh_token", Text, nullable=True)
    token_expires_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    owner = relationship("User", back_populates="social_accounts")
    publish_targets = relationship("PublishTarget", back_populates="social_account")

    # Прозрачное шифрование: весь остальной код (publishers/*.py, oauth.py)
    # читает/пишет account.access_token как обычную строку, а в БД всегда
    # попадает и хранится зашифрованное значение. См. app/token_crypto.py.

    @property
    def access_token(self) -> str | None:
        from app.token_crypto import decrypt_token
        return decrypt_token(self.access_token_encrypted)

    @access_token.setter
    def access_token(self, value: str | None) -> None:
        from app.token_crypto import encrypt_token
        self.access_token_encrypted = encrypt_token(value)

    @property
    def refresh_token(self) -> str | None:
        from app.token_crypto import decrypt_token
        return decrypt_token(self.refresh_token_encrypted)

    @refresh_token.setter
    def refresh_token(self, value: str | None) -> None:
        from app.token_crypto import encrypt_token
        self.refresh_token_encrypted = encrypt_token(value)


class PublishTarget(Base):
    """
    Задача "опубликовать конкретный момент на конкретной платформе через
    конкретный аккаунт". У одного Moment может быть несколько PublishTarget —
    например, один и тот же нарезанный ролик уходит и в YouTube, и в TikTok.
    """
    __tablename__ = "publish_targets"

    id = Column(String, primary_key=True, default=gen_uuid)
    moment_id = Column(String, ForeignKey("moments.id"), nullable=False)
    social_account_id = Column(String, ForeignKey("social_accounts.id"), nullable=False)
    platform = Column(Enum(Platform), nullable=False)  # дублируем для удобства фильтрации/логов

    status = Column(Enum(PublishStatus), default=PublishStatus.QUEUED, nullable=False)
    scheduled_at = Column(DateTime, nullable=True)  # null = опубликовать как можно скорее

    title = Column(String, nullable=True)
    description = Column(Text, nullable=True)
    hashtags = Column(Text, nullable=True)  # свободный текст, напр. "#юмор #сериал" — добавляется к описанию перед загрузкой

    # Если True — перед загрузкой на платформу генерируется случайно
    # уникализированная копия рендера (см. pipeline/uniqueize.py), чтобы
    # разные аккаунты не публиковали побитово идентичный файл.
    uniqueize = Column(Boolean, default=False, nullable=False)

    remote_id = Column(String, nullable=True)   # id ролика на платформе после публикации
    remote_url = Column(String, nullable=True)
    error_message = Column(Text, nullable=True)
    published_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    moment = relationship("Moment", back_populates="publish_targets")
    social_account = relationship("SocialAccount", back_populates="publish_targets")


class CoinTransaction(Base):
    """
    Леджер движения монет пользователя. Списания/начисления никогда не
    правят coin_balance напрямую в обход этой таблицы — только через неё,
    чтобы всегда можно было восстановить историю и найти расхождения.
    """
    __tablename__ = "coin_transactions"

    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)

    amount = Column(Integer, nullable=False)  # положительное = начисление, отрицательное = списание
    reason = Column(Enum(CoinTransactionReason), nullable=False)
    note = Column(String, nullable=True)  # например "video_id=... сверх дневного лимита"

    balance_after = Column(Integer, nullable=False)  # снапшот баланса после операции — для аудита
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="coin_transactions")


class AccountSlotPurchase(Base):
    """
    Докупленные слоты для подключения аккаунтов сверх лимита тарифа,
    по одной строке на покупку. Текущий лимит для платформы = базовый
    лимит тарифа + сумма slots по всем покупкам этого пользователя для
    этой платформы.
    """
    __tablename__ = "account_slot_purchases"

    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    platform = Column(Enum(Platform), nullable=False)
    slots = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="slot_purchases")


class RefreshToken(Base):
    """
    Refresh-токен хранится не в открытом виде, а как SHA-256 хеш (как
    пароль) — при утечке БД сами refresh-токены восстановить нельзя,
    только сверить предъявленный токен с хешем.
    """
    __tablename__ = "refresh_tokens"

    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    token_hash = Column(String, unique=True, nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False)
    revoked = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="refresh_tokens")


class UniqueizeUsage(Base):
    """
    Одна запись = один вызов POST /moments/{id}/publish с uniqueize=true —
    ЗА НАРЕЗКУ, а не за количество аккаунтов, на которые публикуется.
    Дневная квота (app/config.py::DAILY_UNIQUEIZE_LIMITS) считается по
    количеству строк здесь за сегодня, не по количеству PublishTarget.
    """
    __tablename__ = "uniqueize_usages"

    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    moment_id = Column(String, ForeignKey("moments.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="uniqueize_usages")


class HashtagDraft(Base):
    """
    Сохранённый набор хештегов/подписи, который пользователь может выбрать
    при публикации вместо того, чтобы каждый раз вводить их заново.
    Один пользователь может иметь несколько черновиков под разные типы
    контента (например, "Юмор" и "Драма" с разными наборами тегов).
    """
    __tablename__ = "hashtag_drafts"

    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    name = Column(String, nullable=False)
    hashtags = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="hashtag_drafts")


class PasswordResetToken(Base):
    """
    Токен восстановления пароля — хранится как SHA-256 хеш (тот же принцип,
    что и RefreshToken): при утечке БД сами токены не восстановить.
    Одноразовый — used=True после успешного использования, повторно
    применить нельзя даже до истечения срока.
    """
    __tablename__ = "password_reset_tokens"

    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    token_hash = Column(String, unique=True, nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False)
    used = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="password_reset_tokens")


class Project(Base):
    """
    Личная закладка пользователя на видео или конкретный момент — способ
    "отложить" работу (нарезку, субтитры) и вернуться к ней позже. Не то
    же самое, что просто список видео (Video/Moment существуют и без
    Project) — Project это то, что пользователь ОСОЗНАННО решил сохранить
    себе на будущее, с собственной заметкой.

    moment_id опционален: можно сохранить весь видео-проект целиком
    (moment_id=None) или конкретный момент внутри него.
    """
    __tablename__ = "projects"

    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    video_id = Column(String, ForeignKey("videos.id"), nullable=False)
    moment_id = Column(String, ForeignKey("moments.id"), nullable=True)

    title = Column(String, nullable=True)  # если не задан — фронтенд показывает имя файла видео
    note = Column(Text, nullable=True)  # личная заметка пользователя самому себе

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="projects")
    video = relationship("Video")
    moment = relationship("Moment")


# access_token/refresh_token в SocialAccount хранятся в БД в ЗАШИФРОВАННОМ
# виде (Fernet, см. app/token_crypto.py) — колонки называются access_token/
# refresh_token в БД, но объект SocialAccount отдаёт/принимает их в открытом
# виде через python-property, шифрование/дешифрование происходит прозрачно.
# Ключ шифрования — TOKEN_ENCRYPTION_KEY, ОТДЕЛЬНЫЙ от SECRET_KEY (JWT).
