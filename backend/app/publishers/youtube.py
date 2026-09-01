"""
Публикация в YouTube через YouTube Data API v3.

Настройка (один раз, на стороне разработчика):
  1. Google Cloud Console → создать проект → включить "YouTube Data API v3".
  2. Настроить OAuth consent screen, создать OAuth 2.0 Client ID (тип: Web application).
  3. Redirect URI должен указывать на твой /social-accounts/youtube/callback.
  4. Client ID/Secret — в переменные окружения (см. .env.example).

Каждый ПОЛЬЗОВАТЕЛЬ приложения проходит OAuth-согласие сам (см. main.py,
эндпоинты /social-accounts/youtube/connect и /callback) — это не твой
личный аккаунт, а аккаунт конкретного пользователя приложения.

Квота: загрузка видео стоит 1600 unit, дефолтная суточная квота проекта —
10 000 unit (~6 загрузок/день на весь проект, не на пользователя). Для
реального продукта с несколькими пользователями нужно подавать заявку на
увеличение квоты в Google Cloud Console.
"""

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleAuthRequest
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from app.publishers.base import Publisher, UploadResult, PublishError
from app.config import YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET


class YouTubePublisher(Publisher):
    def _build_credentials(self) -> Credentials:
        return Credentials(
            token=self.account.access_token,
            refresh_token=self.account.refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=YOUTUBE_CLIENT_ID,
            client_secret=YOUTUBE_CLIENT_SECRET,
        )

    def refresh_token_if_needed(self) -> None:
        creds = self._build_credentials()
        if creds.expired and creds.refresh_token:
            creds.refresh(GoogleAuthRequest())
            self.account.access_token = creds.token
            # вызывающий код (Celery-задача) обязан сохранить account в БД после этого

    def upload(self, video_path: str, title: str, description: str) -> UploadResult:
        try:
            self.refresh_token_if_needed()
            creds = self._build_credentials()
            youtube = build("youtube", "v3", credentials=creds)

            request = youtube.videos().insert(
                part="snippet,status",
                body={
                    "snippet": {
                        "title": title[:100],  # лимит YouTube на длину заголовка
                        "description": description[:5000],
                        "tags": ["shorts"],
                        "categoryId": "24",  # Entertainment
                    },
                    "status": {"privacyStatus": "public", "selfDeclaredMadeForKids": False},
                },
                media_body=MediaFileUpload(video_path, chunksize=-1, resumable=True),
            )
            response = request.execute()
            video_id = response["id"]
            return UploadResult(remote_id=video_id, remote_url=f"https://youtube.com/shorts/{video_id}")
        except Exception as e:
            raise PublishError(f"YouTube upload failed: {e}") from e
