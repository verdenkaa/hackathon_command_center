"""Telegram Bot API transport. Never persist or log provider bodies or token URLs."""
from __future__ import annotations

from app.services import telegram_vault as vault
from app.integrations.telegram_format import message_entities


class TelegramError(RuntimeError):
    def __init__(self, code: str, *, retry_after: float = 0, uncertain: bool = False) -> None:
        super().__init__(code)
        self.code = code
        self.retry_after = retry_after
        self.uncertain = uncertain


class TelegramClient:
    def send(self, chat_id: str, thread_id: int | None, text: str) -> int:
        try:
            token = vault.load()
        except (vault.VaultUnavailable, OSError):
            raise TelegramError('KEY_MISSING') from None
        body: dict = {'chat_id': chat_id, 'text': text, 'entities': message_entities(text),
                      'link_preview_options': {'is_disabled': True}}
        if thread_id is not None:
            body['message_thread_id'] = thread_id
        try:
            # httpx logs full request URLs at INFO. Use urllib to keep token URLs out of logs.
            import json
            import urllib.request
            import urllib.error
            import socket
            request = urllib.request.Request(f'https://api.telegram.org/bot{token}/sendMessage',
                data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'}, method='POST')
            try:
                with urllib.request.urlopen(request, timeout=20) as response:
                    data = json.load(response)
            except urllib.error.HTTPError as exc:
                try:
                    data = json.load(exc)
                except (ValueError, OSError):
                    data = {'ok': False, 'error_code': exc.code}
            except urllib.error.URLError as exc:
                if isinstance(exc.reason, (ConnectionRefusedError, socket.gaierror)):
                    raise TelegramError('TEMPORARY', retry_after=5) from None
                raise TelegramError('UNKNOWN_RESULT', uncertain=True) from None
            if data.get('ok'):
                return int(data['result']['message_id'])
            code = data.get('error_code')
            description = str(data.get('description', '')).lower()
            if code == 429:
                wait = min(max(float(data.get('parameters', {}).get('retry_after', 5)), 1), 86400)
                raise TelegramError('RATE_LIMIT', retry_after=wait)
            if code == 401:
                raise TelegramError('INVALID_TOKEN')
            if code == 403:
                raise TelegramError('BOT_FORBIDDEN')
            if 'thread' in description or 'topic' in description:
                raise TelegramError('TOPIC_UNAVAILABLE')
            if code and code >= 500:
                raise TelegramError('TEMPORARY', retry_after=10)
            raise TelegramError('CHAT_UNAVAILABLE')
        except TelegramError:
            raise
        except Exception:
            raise TelegramError('UNKNOWN_RESULT', uncertain=True) from None


telegram_client = TelegramClient()
