"""Telegram-интеграция. До передачи токена — mock; реальная отправка добавится с ключами."""
from __future__ import annotations

import logging

from app.config import settings

logger = logging.getLogger("hcc.telegram")


class TelegramClient:
    def send(self, text: str, mention_usernames: list[str] | None = None) -> bool:
        token = settings.telegram_bot_token
        chat_id = settings.telegram_chat_id
        mention = " ".join(f"@{u}" for u in (mention_usernames or []))
        if not token or not chat_id:
            logger.info("[telegram mock] %s %s", text, mention)
            return True
        # Реальная отправка в общий чат будет добавлена при наличии токена.
        logger.info("[telegram stub] %s %s", text, mention)
        return True


telegram_client = TelegramClient()
