"""
Публикация Reels в Instagram через Instagram Graph API.

ВАЖНО, прочитай перед использованием:
  - Работает ТОЛЬКО с Instagram Business или Creator аккаунтом, привязанным
    к Facebook-странице. Обычный личный аккаунт через API не публикует.
  - Видео должно быть доступно по прямой публичной URL (Instagram сам его
    скачивает) — то есть перед публикацией готовый ролик нужно выложить
    на публично доступный storage (S3/аналог), просто путь на диске сервера
    не подойдёт.
  - Настройка: Meta for Developers → создать приложение → добавить продукт
    "Instagram Graph API" → подключить Facebook-страницу и Instagram-аккаунт.
  - Публикация двухшаговая: создать media-контейнер → опубликовать контейнер
    (с задержкой, пока Instagram обработает видео).

Документация: https://developers.facebook.com/docs/instagram-api/guides/content-publishing
"""

import time

import requests

from app.publishers.base import Publisher, UploadResult, PublishError

GRAPH_API_BASE = "https://graph.facebook.com/v19.0"


class InstagramPublisher(Publisher):
    def upload(self, video_path: str, title: str, description: str) -> UploadResult:
        # video_path здесь ожидается как ПУБЛИЧНЫЙ URL (см. заметку выше),
        # а не путь на локальном диске — вызывающий код (Celery-задача)
        # обязан сначала залить рендер на публичное хранилище.
        video_url = video_path
        ig_user_id = self.account.platform_account_id

        try:
            # Шаг 1: создать media-контейнер
            create_resp = requests.post(
                f"{GRAPH_API_BASE}/{ig_user_id}/media",
                data={
                    "media_type": "REELS",
                    "video_url": video_url,
                    "caption": description[:2200],
                    "access_token": self.account.access_token,
                },
                timeout=30,
            )
            create_resp.raise_for_status()
            container_id = create_resp.json()["id"]

            # Шаг 2: дождаться обработки видео Instagram'ом (асинхронно)
            status = "IN_PROGRESS"
            for _ in range(30):  # до ~5 минут ожидания
                status_resp = requests.get(
                    f"{GRAPH_API_BASE}/{container_id}",
                    params={"fields": "status_code", "access_token": self.account.access_token},
                    timeout=15,
                )
                status_resp.raise_for_status()
                status = status_resp.json().get("status_code")
                if status == "FINISHED":
                    break
                if status == "ERROR":
                    raise PublishError("Instagram: обработка видео завершилась ошибкой")
                time.sleep(10)
            else:
                raise PublishError("Instagram: превышено время ожидания обработки видео")

            # Шаг 3: опубликовать контейнер
            publish_resp = requests.post(
                f"{GRAPH_API_BASE}/{ig_user_id}/media_publish",
                data={"creation_id": container_id, "access_token": self.account.access_token},
                timeout=30,
            )
            publish_resp.raise_for_status()
            media_id = publish_resp.json()["id"]

            return UploadResult(remote_id=media_id, remote_url=f"https://instagram.com/reel/{media_id}")
        except requests.HTTPError as e:
            raise PublishError(f"Instagram upload failed: {e.response.text if e.response else e}") from e
        except Exception as e:
            raise PublishError(f"Instagram upload failed: {e}") from e
