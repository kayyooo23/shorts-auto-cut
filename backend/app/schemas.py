from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, field_validator


class UserCreate(BaseModel):
    email: EmailStr
    password: str

    @field_validator("password")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        return _validate_password_length(v)


def _validate_password_length(v: str) -> str:
    if len(v) < 8:
        raise ValueError("Пароль должен быть не короче 8 символов")
    return v


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    email: str
    created_at: datetime
    is_admin: bool


class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class AccessTokenOnly(BaseModel):
    access_token: str
    token_type: str = "bearer"


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def validate_new_password(cls, v: str) -> str:
        return _validate_password_length(v)


class DeleteAccountRequest(BaseModel):
    current_password: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ForgotPasswordResponse(BaseModel):
    message: str
    # Заполняется ТОЛЬКО вне продакшена (см. app/email.py) — чтобы можно
    # было протестировать флоу локально без настоящего email-провайдера.
    dev_reset_token: str | None = None


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def validate_new_password(cls, v: str) -> str:
        return _validate_password_length(v)


class SubtitleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    start: float
    end: float
    text: str
    order_index: int


class SubtitleUpdate(BaseModel):
    start: float | None = None
    end: float | None = None
    text: str | None = None


class SubtitleCreate(BaseModel):
    start: float
    end: float
    text: str


class ClipOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    track_id: str
    file_path: str
    source_duration: float | None
    position_start: float
    position_end: float
    trim_start: float
    trim_end: float
    volume: float
    pip_x: float
    pip_y: float
    pip_width: float
    pip_height: float


class TrackOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    moment_id: str
    type: str
    order_index: int
    name: str | None
    clips: list[ClipOut] = []


class TrackCreate(BaseModel):
    type: str  # "video" | "audio"
    name: str | None = None


class ClipUpdate(BaseModel):
    position_start: float | None = None
    position_end: float | None = None
    trim_start: float | None = None
    trim_end: float | None = None
    volume: float | None = None
    pip_x: float | None = None
    pip_y: float | None = None
    pip_width: float | None = None
    pip_height: float | None = None


class MomentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    video_id: str
    start: float
    end: float
    reason: str | None
    hook_line: str | None
    status: str
    banner_path: str | None
    banner_position: str
    audio_path: str | None
    audio_duration: float | None
    audio_trim_start: float | None
    audio_trim_end: float | None
    audio_volume: float
    output_path: str | None
    subtitles: list[SubtitleOut] = []
    tracks: list[TrackOut] = []
    publish_targets: list["PublishTargetOut"] = []


class MomentUpdate(BaseModel):
    start: float | None = None
    end: float | None = None
    status: str | None = None
    banner_position: str | None = None
    audio_trim_start: float | None = None
    audio_trim_end: float | None = None
    audio_volume: float | None = None


class VideoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    filename: str
    status: str
    error_message: str | None
    duration_seconds: float | None
    created_at: datetime
    moments: list[MomentOut] = []


class VideoListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    filename: str
    status: str
    created_at: datetime


class SocialAccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    platform: str
    platform_username: str | None
    created_at: datetime


class PublishTargetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    moment_id: str
    platform: str
    status: str
    scheduled_at: datetime | None
    title: str | None
    description: str | None
    hashtags: str | None
    remote_url: str | None
    error_message: str | None
    published_at: datetime | None
    uniqueize: bool


class PublishRequest(BaseModel):
    """Тело запроса на публикацию момента: на каких платформах (через какие
    подключённые аккаунты) и когда."""
    social_account_ids: list[str]
    title: str | None = None
    description: str | None = None
    hashtags: str | None = None  # напр. "#юмор #сериал" — добавляется к описанию перед загрузкой
    scheduled_at: datetime | None = None  # None = опубликовать как можно скорее
    uniqueize: bool = False  # см. pipeline/uniqueize.py


class HashtagDraftOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    hashtags: str
    created_at: datetime


class HashtagDraftCreate(BaseModel):
    name: str
    hashtags: str


class UploadResponse(BaseModel):
    video: VideoOut
    paid_with_coins: bool
    coins_spent: int
    remaining_free_cuts_today: int


class PlatformUsage(BaseModel):
    platform: str
    connected: int
    limit: int


class BillingMe(BaseModel):
    subscription_tier: str
    subscription_expires_at: datetime | None
    coin_balance: int
    cuts_used_today: int
    cuts_daily_limit: int
    uniqueize_used_today: int
    uniqueize_daily_limit: int
    platform_usage: list[PlatformUsage]
    same_ip_free_signups_last_7d: int  # информационный сигнал, см. app/billing.py


class CoinGrant(BaseModel):
    amount: int
    note: str | None = None


class TierSet(BaseModel):
    tier: str
    expires_at: datetime | None = None


class ProjectVideoSummary(BaseModel):
    """Краткая сводка по видео — чтобы карточка проекта не тянула весь VideoOut со всеми моментами."""
    model_config = ConfigDict(from_attributes=True)
    id: str
    filename: str
    status: str


class ProjectMomentSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    hook_line: str | None
    status: str
    start: float
    end: float


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    video_id: str
    moment_id: str | None
    title: str | None
    note: str | None
    created_at: datetime
    updated_at: datetime
    video: ProjectVideoSummary
    moment: ProjectMomentSummary | None


class ProjectCreate(BaseModel):
    video_id: str
    moment_id: str | None = None
    title: str | None = None
    note: str | None = None


class ProjectUpdate(BaseModel):
    title: str | None = None
    note: str | None = None


MomentOut.model_rebuild()
