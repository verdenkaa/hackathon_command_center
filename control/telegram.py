"""Outbound backups only. No getUpdates, incoming handlers, or token logging."""
from __future__ import annotations

import json
from html import escape
import secrets
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

from control import VERSION

# Cloud Bot API sendDocument currently permits 50 MB. Conservative decimal bound.
DOCUMENT_LIMIT = 50_000_000


class DeliveryError(ValueError):
    pass


def _failure(result: dict[str, Any], code: int = 0) -> DeliveryError:
    description = str(result.get('description', '')).lower()
    if 'thread' in description or 'topic' in description:
        detail = 'Тема Telegram не найдена или закрыта. Укажите ID темы из выбранного чата либо очистите поле темы.'
    elif code == 401 or 'unauthorized' in description:
        detail = 'Telegram отклонил токен бота. Сохраните действующий токен из BotFather.'
    elif 'chat not found' in description:
        detail = 'Telegram не нашёл чат. Проверьте числовой ID (обычно -100…), добавьте бота в этот чат.'
    elif code == 403 or 'forbidden' in description or 'not a member' in description or 'rights' in description:
        detail = 'Боту запрещена отправка. Добавьте бота в выбранный чат; в канале выдайте права публикации сообщений и файлов.'
    elif code == 429 or 'too many requests' in description:
        delay = result.get('parameters', {}).get('retry_after', 60)
        detail = f'Telegram ограничил частоту. Повторите отправку через {int(delay) if str(delay).isdigit() else 60} с.'
    elif 'too big' in description:
        detail = 'Telegram отклонил размер файла. Используйте дополнительную папку резервных копий.'
    else:
        detail = f'Telegram отклонил запрос (код {code or result.get("error_code", 400)}). Проверьте ID чата, темы и права бота.'
    return DeliveryError(detail + ' Локальная копия сохранена.')


def _submit(request: urllib.request.Request) -> None:
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            result = json.loads(response.read(1_000_000))
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read(65536))
        except (ValueError, OSError):
            body = {}
        raise _failure(body, exc.code) from None
    except (OSError, ValueError, urllib.error.URLError):
        raise DeliveryError('Нет подтверждения Telegram: проверьте интернет или VPN. Локальная копия сохранена. При обрыве после отправки повтор может создать дубликат.') from None
    if not isinstance(result, dict) or not result.get('ok'):
        raise _failure(result if isinstance(result, dict) else {})


def send_alert(token: str, chat: str, thread: int | None, text: str, administrator: str) -> None:
    mention = '@' + escape(administrator.lstrip('@')) + '\n' if administrator else ''
    header, _, body = text[:2800].partition('\n')
    if not body:
        header, body = 'Штаб · оповещение', header
    title, _, timestamp = header.partition(' · ')
    component, separator, detail = body.partition(': ')
    old, arrow, current = detail.partition(' → ')
    status = current.split('.', 1)[0] if arrow else detail
    color = '🔴' if any(word in status.lower() for word in ('сбой','ошиб','недоступ')) else '🟢' if any(word in status.lower() for word in ('работает','готов','связь')) else '🟡' if 'подготов' in status.lower() else '⚪'
    if separator:
        content = f'{color} <b>{escape(component)}</b>\n'
        content += f'<i>Было: {escape(old)}</i>\n<b>Сейчас: {escape(current)}</b>' if arrow else escape(detail)
    else:
        content = color + ' ' + escape(body)
    formatted = mention + f'🔔 <b>{escape(title)}</b>\n'
    if timestamp:
        formatted += f'<i>{escape(timestamp)}</i>\n'
    formatted += '\n' + content
    fields: dict[str, Any] = {'chat_id': chat, 'text': formatted, 'parse_mode':'HTML'}
    if thread:
        fields['message_thread_id'] = thread
    _submit(urllib.request.Request(f'https://api.telegram.org/bot{token}/sendMessage',
        data=json.dumps(fields).encode(), headers={'Content-Type': 'application/json'}))


def send_backup(token: str, chat: str, thread: int | None, blob: bytes, record: dict[str, Any], identity: str) -> None:
    if len(blob) > DOCUMENT_LIMIT:
        raise DeliveryError("Архив больше лимита Telegram Bot API 50 МБ; сохранён локально. Используйте внешний диск.")
    boundary = "hcc" + secrets.token_hex(16)
    created = datetime.fromtimestamp(record['created'], timezone.utc).strftime('%d.%m.%Y %H:%M UTC')
    caption = (f"🟢 <b>Резервная копия готова</b>\n<b>{escape(identity[:80])}</b>\n"
               f"<i>Снимок: {created}</i>\n\n📦 {len(blob)/1024:.1f} КиБ · версия {escape(VERSION)}\n"
               "🔐 <b>Архив зашифрован</b>\n<i>Откройте файл в хабе. Ключ архива храните отдельно.</i>")
    fields = {"chat_id": chat, "disable_notification": "true", "caption": caption, 'parse_mode':'HTML'}
    if thread:
        fields["message_thread_id"] = str(thread)
    parts: list[bytes] = []
    for name, value in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    parts.append((f'--{boundary}\r\nContent-Disposition: form-data; name="document"; filename="{record["id"]}.hcc"\r\n'
                  'Content-Type: application/octet-stream\r\n\r\n').encode() + blob + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    request = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendDocument", data=b"".join(parts),
                                     headers={"Content-Type": "multipart/form-data; boundary=" + boundary})
    _submit(request)
