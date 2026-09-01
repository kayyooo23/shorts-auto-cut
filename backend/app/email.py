"""
Отправка email. Сейчас реализована ТОЛЬКО dev-заглушка — реального
почтового провайдера (SendGrid/Postmark/Amazon SES/СМТП-сервер) пока нет.

В dev-режиме (ENVIRONMENT != production) письма не отправляются никуда,
а просто печатаются в лог процесса — этого достаточно, чтобы руками
протестировать флоу восстановления пароля локально, скопировав токен
из вывода сервера.

В проде (ENVIRONMENT == production) вызов этой функции подниет
RuntimeError — специально, чтобы нельзя было случайно задеплоить
приложение, которое молча не отправляет пользователям критичные письма
(сброс пароля, подтверждение регистрации и т.п.), и никто бы не заметил.
"""

import logging

from app.config import ENVIRONMENT

logger = logging.getLogger(__name__)


class EmailNotConfiguredError(Exception):
    pass


def send_password_reset_email(to_email: str, reset_url: str) -> None:
    if ENVIRONMENT == "production":
        raise EmailNotConfiguredError(
            "Реальный email-провайдер не подключён (см. app/email.py) — "
            "нельзя отправлять письма восстановления пароля в проде через dev-заглушку."
        )

    logger.warning(
        "[DEV EMAIL — реально не отправлено] Кому: %s\nСсылка для сброса пароля: %s",
        to_email, reset_url,
    )
