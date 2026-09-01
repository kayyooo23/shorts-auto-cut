"""
Общий интерфейс публикации видео на внешнюю платформу.

Каждая платформа (YouTube, TikTok, Instagram) реализует один и тот же
контракт: upload(). Это позволяет Celery-задаче publish_target не знать
ничего о конкретной платформе — просто взять нужный Publisher по значению
Platform и вызвать upload().
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class UploadResult:
    remote_id: str
    remote_url: str


class PublishError(Exception):
    """Ошибка публикации — ловится в Celery-задаче и пишется в PublishTarget.error_message."""


class Publisher(ABC):
    """
    account: app.models.SocialAccount — содержит access_token/refresh_token
    конкретного пользователя для этой платформы.
    """

    def __init__(self, account):
        self.account = account

    @abstractmethod
    def upload(self, video_path: str, title: str, description: str) -> UploadResult:
        """Заливает видео на платформу, возвращает id и ссылку на опубликованный ролик.
        Обязана поднимать PublishError при любой ошибке (истёкший токен,
        отказ платформы, сетевая ошибка и т.д.) — Celery-задача сама решает,
        нужно ли повторить попытку."""
        raise NotImplementedError

    def refresh_token_if_needed(self) -> None:
        """Платформы с коротким временем жизни access_token переопределяют
        этот метод, чтобы обновить его через refresh_token перед upload().
        По умолчанию — ничего не делает."""
        pass
