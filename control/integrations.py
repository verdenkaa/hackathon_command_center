"""Credential checks without messages, generation, or provider response logging."""
from __future__ import annotations

import json
import os
import re
import http.client
import shutil
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

FXTUNNEL_SERVER = 'tunnel.fxtun.dev:443'


def tunnel_binary() -> str | None:
    binary = shutil.which('fxtunnel')
    candidate = Path(os.environ.get('LOCALAPPDATA', '')) / 'fxTunnel' / 'fxtunnel.exe'
    return binary or (str(candidate) if os.name == 'nt' and candidate.is_file() else None)


def validate(name: str, key: str) -> tuple[str, str]:
    if name not in {'telegram', 'fxtunnel'}:
        return 'retired', 'Интеграция отключена'
    key = key.strip()
    if not key:
        return 'missing', 'Ключ не задан'
    if name == 'telegram' and not re.fullmatch(r'\d{5,20}:[A-Za-z0-9_-]{20,100}', key):
        return 'invalid', 'Неверный формат токена Telegram'
    if name == 'fxtunnel':
        binary = tunnel_binary()
        if not binary:
            return 'unknown', 'Ключ сохранён; установите CLI fxTunnel для проверки'
        try:
            result = subprocess.run([binary, 'domains', 'list', '--server', FXTUNNEL_SERVER],
                env={**os.environ, 'FXTUNNEL_TOKEN': key},
                capture_output=True, timeout=20,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            if result.returncode == 0:
                return 'valid', 'fxTunnel подтвердил ключ'
            text = (result.stdout + result.stderr).decode(errors='replace').lower()
            if any(word in text for word in ('unauthorized', 'invalid token', 'invalid api', 'authentication failed', '401')):
                return 'invalid', 'fxTunnel отклонил ключ'
        except (OSError, subprocess.TimeoutExpired):
            pass
        return 'unknown', 'Ключ сохранён; fxTunnel недоступен или не подтвердил доступ'
    request = urllib.request.Request(f'https://api.telegram.org/bot{key}/getMe')
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            body = json.loads(response.read(65536))
        if name == 'telegram' and not body.get('ok'):
            return 'invalid', 'Telegram отклонил токен'
        return 'valid', 'Telegram подтвердил токен бота'
    except urllib.error.HTTPError as exc:
        try:
            data = json.loads(exc.read(65536))
        except (ValueError, OSError):
            data = {}
        detail = str(data).lower()
        if 'location is not supported' in detail or 'region is not supported' in detail:
            return 'blocked', 'Google не поддерживает регион сервера; проверьте сетевой маршрут/VPN контейнера'
        if any(word in detail for word in ('failed_precondition', 'billing', 'payment')):
            return 'blocked', 'Google требует проверить регион, тариф или платёжные настройки проекта'
        if exc.code == 401 or any(word in detail for word in ('api_key_invalid', 'api key not valid', 'api key expired')):
            return 'invalid', 'Сервис отклонил ключ'
        if exc.code == 403 or 'api_key_service_blocked' in detail or 'service_disabled' in detail:
            return 'blocked', 'Доступ запрещён: проверьте ограничения ключа, API и регион'
        return 'unknown', f'Сервис не подтвердил ключ (HTTP {exc.code}); повторите проверку'
    except (OSError, ValueError, http.client.HTTPException):
        return 'unknown', 'Ключ сохранён; нет связи с API. Проверьте сеть, VPN и сертификаты'
