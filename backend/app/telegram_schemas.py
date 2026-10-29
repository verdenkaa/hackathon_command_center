import ipaddress
import re
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator


def normalize_username(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    name = value.strip().removeprefix('@')
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{4,31}', name):
        raise ValueError('Telegram username: 5–32 латинских символа, цифры и _, начало с буквы')
    return name.lower()


class TelegramConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')
    chat_id: str | None = Field(default=None, max_length=32)
    routes: dict[str, int | None] = Field(default_factory=dict)
    public_url: str = Field(default='', max_length=500)
    confirm_chat: bool = False

    @field_validator('chat_id')
    @classmethod
    def chat(cls, value: str | None) -> str | None:
        if not value or not value.strip():
            return None
        value = value.strip()
        if not re.fullmatch(r'-?[1-9]\d{0,19}', value):
            raise ValueError('Введите числовой ID чата Telegram')
        return value

    @field_validator('routes')
    @classmethod
    def routes_valid(cls, value: dict[str, int | None]) -> dict[str, int | None]:
        from app.services.telegram import EVENTS
        if set(value) - set(EVENTS) or any(v is not None and (isinstance(v, bool) or v < 0 or v > 2147483647) for v in value.values()):
            raise ValueError('Неизвестное событие или неверный ID темы (0 — общий чат)')
        return value

    @field_validator('public_url')
    @classmethod
    def url(cls, value: str) -> str:
        value = value.strip().rstrip('/')
        if not value:
            return ''
        parsed = urlsplit(value)
        host = (parsed.hostname or '').lower().rstrip('.')
        _ = parsed.port  # Validate an explicitly provided port.
        if parsed.scheme not in ('http', 'https') or not host or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError('Нужен доступный команде HTTP(S) адрес без пароля и параметров')
        if host == 'localhost' or host.endswith('.localhost'):
            raise ValueError('localhost недоступен команде')
        try:
            addr = ipaddress.ip_address(host)
            if addr.is_loopback or addr.is_unspecified or addr.is_link_local:
                raise ValueError('Локальный адрес сервера недоступен команде')
        except ValueError as exc:
            if 'недоступен' in str(exc):
                raise
        return value


class DeliveryRetry(BaseModel):
    accept_duplicate_risk: bool = False


class TestDelivery(BaseModel):
    confirmed_chat_id: str
    thread_id: int | None = Field(default=None, ge=1, le=2147483647)


class DeleteAccount(BaseModel):
    model_config = ConfigDict(extra='forbid')
    confirm: Literal[True]
    preview_version: str
    incident_captains: dict[int, int] = Field(default_factory=dict)
    task_primaries: dict[int, int] = Field(default_factory=dict)
