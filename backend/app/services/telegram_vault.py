"""Separate DPAPI secret using the existing Windows vault and instance isolation."""
from pathlib import Path
from app.config import settings
from app.services import advisor_vault as windows

VaultUnavailable = windows.VaultUnavailable
available = windows.available


def _path() -> Path:
    return windows._path().with_name('telegram.dpapi')


def is_saved() -> bool:
    if settings.app_secrets_dir:
        return bool(settings.secret_value('telegram'))
    try:
        return _path().is_file()
    except VaultUnavailable:
        return False


def save(secret: str) -> None:
    if settings.app_secrets_dir:
        raise VaultUnavailable('Измените токен через локальную панель управления')
    import re
    if not re.fullmatch(r'\d{5,20}:[A-Za-z0-9_-]{20,100}', secret.strip()):
        raise VaultUnavailable('Неверный формат токена бота')
    encrypted = windows._crypt(secret.strip().encode('utf-8'))
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.pending')
    temp.write_bytes(encrypted)
    temp.replace(path)


def load() -> str:
    if settings.app_secrets_dir:
        value = settings.secret_value('telegram')
        if not value:
            raise VaultUnavailable('Токен Telegram не задан в локальной панели')
        return value
    try:
        return windows._crypt(_path().read_bytes(), decrypt=True).decode('utf-8')
    except (OSError, UnicodeError):
        raise VaultUnavailable('Токен не задан или хранилище недоступно') from None


def delete() -> None:
    if settings.app_secrets_dir:
        raise VaultUnavailable('Удалите токен через локальную панель управления')
    _path().unlink(missing_ok=True)
