"""
Публикация в TikTok через Content Posting API.

ВАЖНО, прочитай перед использованием:
  - Пока приложение не прошло ревью TikTok (audit), API работает только
    в "unaudited" режиме: ролики публикуются как ПРИВАТНЫЕ (SELF_ONLY) и
    видны только автору. Публичная публикация от имени произвольных
    пользователей доступна только после одобрения заявки на аудит,
    которое TikTok может рассматривать неделями и не гарантирует одобрение.
  - Настройка: TikTok for Developers → создать приложение → подключить
    "Content Posting API" → получить Client Key/Secret → OAuth redirect URI.
  - Требуется прямая ссылка на видеофайл (PULL_FROM_URL) либо загрузка
    чанками (FILE_UPLOAD) — ниже реализован вариант с прямой загрузкой файла.

Документация может меняться — перед продакшен-использованием сверься
с https://developers.tiktok.com/doc/content-posting-api-get-started
"""

import requests

from app.publishers.base import Publisher, UploadResult, PublishError

TIKTOK_API_BASE = "https://open.tiktokapis.com/v2"


class TikTokPublisher(Publisher):
    def upload(self, video_path: str, title: str, description: str) -> UploadResult:
        headers = {"Authorization": f"Bearer {self.account.access_token}"}

        try:
            # Шаг 1: инициализация публикации — сообщаем TikTok размер файла
            import os
            file_size = os.path.getsize(video_path)

            init_resp = requests.post(
                f"{TIKTOK_API_BASE}/post/publish/video/init/",
                headers=headers,
                json={
                    "post_info": {
                        "title": title[:150],
                        "privacy_level": "SELF_ONLY",  # до прохождения аудита иначе нельзя
                    },
                    "source_info": {
                        "source": "FILE_UPLOAD",
                        "video_size": file_size,
                        "chunk_size": file_size,
                        "total_chunk_count": 1,
                    },
                },
                timeout=30,
            )
            init_resp.raise_for_status()
            init_data = init_resp.json()["data"]
            publish_id = init_data["publish_id"]
            upload_url = init_data["upload_url"]

            # Шаг 2: заливаем сам файл по подписанному URL
            with open(video_path, "rb") as f:
                upload_resp = requests.put(
                    upload_url,
                    data=f,
                    headers={"Content-Range": f"bytes 0-{file_size - 1}/{file_size}", "Content-Type": "video/mp4"},
                    timeout=300,
                )
            upload_resp.raise_for_status()

            # TikTok обрабатывает видео асинхронно — publish_id можно опросить
            # через /post/publish/status/fetch/, чтобы узнать финальный video_id.
            # Здесь возвращаем то, что есть сразу — статус уточняется отдельно.
            return UploadResult(remote_id=publish_id, remote_url="")
        except requests.HTTPError as e:
            raise PublishError(f"TikTok upload failed: {e.response.text if e.response else e}") from e
        except Exception as e:
            raise PublishError(f"TikTok upload failed: {e}") from e
