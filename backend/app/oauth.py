"""
OAuth-подключение внешних аккаунтов (YouTube/TikTok/Instagram) к пользователю.

Схема одинаковая для всех платформ:
  1. GET /social-accounts/{platform}/connect  → отдаёт authorize_url,
     на который фронтенд редиректит пользователя (открывает окно логина
     самой платформы — YouTube/TikTok/Instagram).
  2. Пользователь логинится и подтверждает доступ на стороне платформы.
  3. Платформа редиректит браузer на /social-accounts/{platform}/callback
     с параметрами ?code=...&state=...
  4. Наш callback обменивает code на access/refresh token и сохраняет
     SocialAccount в БД.

`state` — подписанный JWT с user_id и платформой, коротко живущий (10 минут).
Это защищает от CSRF (проверяем, что callback пришёл для того же
пользователя, который инициировал connect) без отдельной таблицы для
временных состояний.
"""

from datetime import datetime, timedelta

import requests
from jose import jwt, JWTError

from app.config import (
    SECRET_KEY, JWT_ALGORITHM, APP_BASE_URL,
    YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET,
    TIKTOK_CLIENT_KEY, TIKTOK_CLIENT_SECRET,
    INSTAGRAM_APP_ID, INSTAGRAM_APP_SECRET,
)
from app.models import Platform


class OAuthError(Exception):
    pass


def make_state(user_id: str, platform: str) -> str:
    payload = {"sub": user_id, "platform": platform, "exp": datetime.utcnow() + timedelta(minutes=10)}
    return jwt.encode(payload, SECRET_KEY, algorithm=JWT_ALGORITHM)


def verify_state(state: str, expected_platform: str) -> str:
    """Возвращает user_id, если state валиден и не истёк."""
    try:
        payload = jwt.decode(state, SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except JWTError:
        raise OAuthError("Невалидный или истёкший state — начни подключение заново")

    if payload.get("platform") != expected_platform:
        raise OAuthError("state не соответствует платформе")
    return payload["sub"]


def _redirect_uri(platform: str) -> str:
    return f"{APP_BASE_URL}/social-accounts/{platform}/callback"


def get_authorize_url(platform: Platform, user_id: str) -> str:
    state = make_state(user_id, platform.value)
    redirect_uri = _redirect_uri(platform.value)

    if platform == Platform.YOUTUBE:
        scope = "https://www.googleapis.com/auth/youtube.upload"
        return (
            "https://accounts.google.com/o/oauth2/v2/auth"
            f"?client_id={YOUTUBE_CLIENT_ID}&redirect_uri={redirect_uri}"
            f"&response_type=code&scope={scope}&access_type=offline&prompt=consent&state={state}"
        )

    if platform == Platform.TIKTOK:
        scope = "video.publish"
        return (
            "https://www.tiktok.com/v2/auth/authorize"
            f"?client_key={TIKTOK_CLIENT_KEY}&redirect_uri={redirect_uri}"
            f"&response_type=code&scope={scope}&state={state}"
        )

    if platform == Platform.INSTAGRAM:
        # Instagram публикация идёт через Facebook Login с правами на
        # управление привязанной Instagram Business-страницей.
        scope = "instagram_basic,instagram_content_publish,pages_show_list,pages_read_engagement"
        return (
            "https://www.facebook.com/v19.0/dialog/oauth"
            f"?client_id={INSTAGRAM_APP_ID}&redirect_uri={redirect_uri}"
            f"&scope={scope}&state={state}"
        )

    raise OAuthError(f"Платформа {platform} не поддерживается")


def exchange_code(platform: Platform, code: str) -> dict:
    """
    Обменивает authorization code на токены и базовую информацию об
    аккаунте. Возвращает dict:
        {access_token, refresh_token, expires_at, platform_account_id, platform_username}
    """
    redirect_uri = _redirect_uri(platform.value)

    if platform == Platform.YOUTUBE:
        resp = requests.post("https://oauth2.googleapis.com/token", data={
            "code": code,
            "client_id": YOUTUBE_CLIENT_ID,
            "client_secret": YOUTUBE_CLIENT_SECRET,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        # получаем id/название канала для отображения в UI
        channel_resp = requests.get(
            "https://www.googleapis.com/youtube/v3/channels",
            params={"part": "snippet", "mine": "true"},
            headers={"Authorization": f"Bearer {data['access_token']}"},
            timeout=30,
        )
        channel_resp.raise_for_status()
        items = channel_resp.json().get("items", [])
        channel_id = items[0]["id"] if items else ""
        channel_title = items[0]["snippet"]["title"] if items else None

        return {
            "access_token": data["access_token"],
            "refresh_token": data.get("refresh_token"),
            "expires_at": datetime.utcnow() + timedelta(seconds=data.get("expires_in", 3600)),
            "platform_account_id": channel_id,
            "platform_username": channel_title,
        }

    if platform == Platform.TIKTOK:
        resp = requests.post("https://open.tiktokapis.com/v2/oauth/token/", data={
            "client_key": TIKTOK_CLIENT_KEY,
            "client_secret": TIKTOK_CLIENT_SECRET,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        }, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        return {
            "access_token": data["access_token"],
            "refresh_token": data.get("refresh_token"),
            "expires_at": datetime.utcnow() + timedelta(seconds=data.get("expires_in", 86400)),
            "platform_account_id": data.get("open_id", ""),
            "platform_username": None,  # требует отдельного вызова /user/info/
        }

    if platform == Platform.INSTAGRAM:
        # Шаг 1: короткоживущий токен пользователя Facebook
        resp = requests.get("https://graph.facebook.com/v19.0/oauth/access_token", params={
            "client_id": INSTAGRAM_APP_ID,
            "client_secret": INSTAGRAM_APP_SECRET,
            "redirect_uri": redirect_uri,
            "code": code,
        }, timeout=30)
        resp.raise_for_status()
        user_token = resp.json()["access_token"]

        # Шаг 2: находим Facebook-страницу пользователя и привязанный
        # Instagram Business-аккаунт
        pages_resp = requests.get("https://graph.facebook.com/v19.0/me/accounts", params={
            "access_token": user_token,
        }, timeout=30)
        pages_resp.raise_for_status()
        pages = pages_resp.json().get("data", [])
        if not pages:
            raise OAuthError("К аккаунту Facebook не привязано ни одной страницы")

        page = pages[0]
        page_id = page["id"]
        page_token = page["access_token"]  # долгоживущий токен страницы — используем его для публикации

        ig_resp = requests.get(f"https://graph.facebook.com/v19.0/{page_id}", params={
            "fields": "instagram_business_account",
            "access_token": page_token,
        }, timeout=30)
        ig_resp.raise_for_status()
        ig_account = ig_resp.json().get("instagram_business_account")
        if not ig_account:
            raise OAuthError("К этой Facebook-странице не привязан Instagram Business-аккаунт")

        return {
            "access_token": page_token,
            "refresh_token": None,  # токены страницы Facebook долгоживущие, refresh не требуется
            "expires_at": None,
            "platform_account_id": ig_account["id"],
            "platform_username": None,
        }

    raise OAuthError(f"Платформа {platform} не поддерживается")
