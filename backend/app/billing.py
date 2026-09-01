"""
Биллинг: дневные квоты на нарезки по тарифу, лимиты подключённых аккаунтов
по платформам, списание монет за превышение лимитов.

Все изменения coin_balance идут ТОЛЬКО через spend_coins()/credit_coins() —
это гарантирует, что в CoinTransaction всегда есть полная история и
balance_after всегда совпадает с реальным балансом (полезно при разборе
споров с пользователем "почему у меня списались монеты").
"""

import subprocess
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import (
    MAX_VIDEO_DURATION_SECONDS, DAILY_CUT_LIMITS, ACCOUNT_LIMITS_PER_PLATFORM,
    EXTRA_CUT_COST_COINS, EXTRA_ACCOUNT_SLOT_COST_COINS, DAILY_UNIQUEIZE_LIMITS,
    FFPROBE_PATH,
)
from app.models import (
    User, Video, SocialAccount, AccountSlotPurchase, CoinTransaction,
    CoinTransactionReason, Platform, SubscriptionTier, UniqueizeUsage,
)


# ---------- Длительность видео ----------

def get_video_duration_seconds(filepath: str) -> float:
    """Определяет длительность видео через ffprobe. Поднимает HTTPException(400),
    если файл повреждён или не является читаемым видео — так пользователь сразу
    получает понятную ошибку при загрузке, а не после долгой транскрипции."""
    try:
        result = subprocess.run(
            [
                FFPROBE_PATH, "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                filepath,
            ],
            capture_output=True, text=True, timeout=30,
        )
        duration = float(result.stdout.strip())
        return duration
    except (ValueError, subprocess.TimeoutExpired, FileNotFoundError) as e:
        raise HTTPException(400, f"Не удалось прочитать видеофайл (повреждён или неверный формат): {e}")


def ensure_duration_allowed(duration_seconds: float) -> None:
    if duration_seconds > MAX_VIDEO_DURATION_SECONDS:
        max_minutes = MAX_VIDEO_DURATION_SECONDS // 60
        raise HTTPException(
            400,
            f"Видео длиннее {max_minutes} минут (у тебя {duration_seconds / 60:.1f} мин) — "
            f"максимум на нарезку {max_minutes} минут за один раз",
        )


# ---------- Монеты ----------

def spend_coins(db: Session, user: User, amount: int, reason: CoinTransactionReason, note: str = "") -> None:
    """Списывает amount монет (amount > 0). Поднимает HTTPException(402), если
    баланса не хватает — ничего не меняет в БД в этом случае."""
    if user.coin_balance < amount:
        raise HTTPException(
            402,
            f"Недостаточно монет: нужно {amount}, на балансе {user.coin_balance}. Пополни баланс.",
        )
    user.coin_balance -= amount
    db.add(CoinTransaction(
        user_id=user.id, amount=-amount, reason=reason, note=note, balance_after=user.coin_balance,
    ))
    # commit делает вызывающий код — так операция остаётся частью одной транзакции
    # с остальными изменениями (например, созданием Video или AccountSlotPurchase)


def credit_coins(db: Session, user: User, amount: int, reason: CoinTransactionReason, note: str = "") -> None:
    """Начисляет amount монет (amount > 0). Используется после успешной оплаты
    (см. /billing/coins/webhook) или для возвратов."""
    user.coin_balance += amount
    db.add(CoinTransaction(
        user_id=user.id, amount=amount, reason=reason, note=note, balance_after=user.coin_balance,
    ))


# ---------- Дневная квота нарезок ----------

def _today_range() -> tuple[datetime, datetime]:
    now = datetime.utcnow()
    start = datetime(now.year, now.month, now.day)
    return start, start + timedelta(days=1)


def count_cuts_today(db: Session, user: User) -> int:
    start, end = _today_range()
    return (
        db.query(func.count(Video.id))
        .filter(Video.owner_id == user.id, Video.created_at >= start, Video.created_at < end)
        .scalar()
    ) or 0


def daily_cut_limit(user: User) -> int:
    return DAILY_CUT_LIMITS[user.subscription_tier.value]


def ensure_cut_allowed(db: Session, user: User) -> bool:
    """
    Проверяет, можно ли пользователю сделать ещё одну нарезку сегодня.
    Если дневная квота тарифа исчерпана — пытается списать монеты за
    нарезку сверх лимита. Поднимает HTTPException(402), если монет не хватает.

    Возвращает True, если нарезка оплачена монетами (сверх квоты),
    False — если она укладывается в бесплатную квоту тарифа.
    """
    used_today = count_cuts_today(db, user)
    limit = daily_cut_limit(user)

    if used_today < limit:
        return False

    spend_coins(
        db, user, EXTRA_CUT_COST_COINS, CoinTransactionReason.EXTRA_CUT,
        note=f"Нарезка сверх дневного лимита тарифа {user.subscription_tier.value} ({used_today}/{limit})",
    )
    return True


# ---------- Дневная квота уникализации ----------

def count_uniqueize_usages_today(db: Session, user: User) -> int:
    start, end = _today_range()
    return (
        db.query(func.count(UniqueizeUsage.id))
        .filter(UniqueizeUsage.user_id == user.id, UniqueizeUsage.created_at >= start, UniqueizeUsage.created_at < end)
        .scalar()
    ) or 0


def daily_uniqueize_limit(user: User) -> int:
    return DAILY_UNIQUEIZE_LIMITS[user.subscription_tier.value]


def ensure_uniqueize_allowed(db: Session, user: User, moment_id: str) -> None:
    """
    Проверяет дневную квоту уникализации (считается ЗА НАРЕЗКУ — один вызов
    POST /moments/{id}/publish с uniqueize=true, независимо от числа
    аккаунтов). Если квота исчерпана — HTTPException(402): цена монет за
    превышение лимита ещё не определена (обсуждается отдельно), поэтому
    сейчас превышение просто блокируется, ничего не списывается.

    При успехе — записывает использование в UniqueizeUsage (в РАМКАХ той
    же транзакции, что и остальные изменения запроса; коммитит вызывающий код).
    """
    used_today = count_uniqueize_usages_today(db, user)
    limit = daily_uniqueize_limit(user)

    if used_today >= limit:
        raise HTTPException(
            402,
            f"Дневной лимит уникализации на тарифе {user.subscription_tier.value} исчерпан "
            f"({used_today}/{limit}). Покупка дополнительных уникализаций за монеты скоро появится.",
        )

    db.add(UniqueizeUsage(user_id=user.id, moment_id=moment_id))


# ---------- Лимиты подключённых аккаунтов ----------

def count_connected_accounts(db: Session, user: User, platform: Platform) -> int:
    return (
        db.query(func.count(SocialAccount.id))
        .filter(SocialAccount.owner_id == user.id, SocialAccount.platform == platform)
        .scalar()
    ) or 0


def purchased_extra_slots(db: Session, user: User, platform: Platform) -> int:
    return (
        db.query(func.coalesce(func.sum(AccountSlotPurchase.slots), 0))
        .filter(AccountSlotPurchase.user_id == user.id, AccountSlotPurchase.platform == platform)
        .scalar()
    ) or 0


def account_slot_limit(db: Session, user: User, platform: Platform) -> int:
    base = ACCOUNT_LIMITS_PER_PLATFORM[user.subscription_tier.value]
    return base + purchased_extra_slots(db, user, platform)


def ensure_account_slot_available(db: Session, user: User, platform: Platform) -> bool:
    """
    Проверяет, можно ли подключить ещё один аккаунт данной платформы.
    Если лимит тарифа исчерпан — пытается купить дополнительный слот за
    монеты (это разовая покупка, слот остаётся навсегда, в отличие от
    оплаты нарезки монетами, которая разовая только для одной нарезки).
    Поднимает HTTPException(402), если монет не хватает.

    Возвращает True, если для подключения потребовался докупленный слот.
    """
    connected = count_connected_accounts(db, user, platform)
    limit = account_slot_limit(db, user, platform)

    if connected < limit:
        return False

    spend_coins(
        db, user, EXTRA_ACCOUNT_SLOT_COST_COINS, CoinTransactionReason.EXTRA_ACCOUNT_SLOT,
        note=f"Доп. слот подключения аккаунта {platform.value} (было {connected}/{limit})",
    )
    db.add(AccountSlotPurchase(user_id=user.id, platform=platform, slots=1))
    return True


# ---------- Мультиаккаунтинг (обход free-лимита новыми email) ----------
#
# Это НАМЕРЕННО не блокирующая проверка, а информационная. IP-адрес —
# ненадёжный сигнал: студенческие общежития, офисы, мобильные операторы
# с CGNAT легитимно сажают десятки разных людей за один внешний IP.
# Автоматическая блокировка по этому признаку била бы по настоящим
# пользователям чаще, чем по злоупотребляющим. Для реальной защиты в
# будущем это должно перерасти в подтверждение по телефону (SMS) —
# отдельная интеграция с провайдером типа Twilio/SMS.ru, обсуждается
# отдельно, если проблема реально проявится на практике.

def count_free_tier_signups_from_ip(db: Session, ip: str, within_days: int = 7) -> int:
    """Сколько FREE-тарифных аккаунтов зарегистрировано с этого IP за
    последние N дней — полезно показать в админке/логах как сигнал для
    ручной проверки, не для автоматического отказа."""
    if not ip:
        return 0
    cutoff = datetime.utcnow() - timedelta(days=within_days)
    return (
        db.query(func.count(User.id))
        .filter(
            User.registration_ip == ip,
            User.subscription_tier == SubscriptionTier.FREE,
            User.created_at >= cutoff,
        )
        .scalar()
    ) or 0
