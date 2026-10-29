import io
import json
import urllib.request
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.integrations.telegram import TelegramClient, vault
from app.services import telegram as svc


def entity_text(text: str, entity: dict) -> str:
    raw = text.encode('utf-16-le')
    return raw[entity['offset'] * 2:(entity['offset'] + entity['length']) * 2].decode('utf-16-le')


def test_transport_formats_without_interpreting_user_markup(monkeypatch):
    monkeypatch.setattr(vault, 'load', lambda: 'synthetic')
    requests = []

    def response(request, **kwargs):
        requests.append(json.loads(request.data))
        return io.BytesIO(b'{"ok":true,"result":{"message_id":1}}')

    monkeypatch.setattr(urllib.request, 'urlopen', response)
    text = ('🤖 ИИ: ручной анализ #1\n\nПроект: A < B & C\n'
            '1. Проверить <b>сервис</b>\nСитуация: «🙂 *не Markdown*»\n'
            'Ответственный: @captain_user\nОткрыть: https://team.example/?project=1&task=2')
    TelegramClient().send('-100', None, text)
    body = requests[0]
    assert body['text'] == text and 'parse_mode' not in body
    styled = [(e['type'], entity_text(text, e)) for e in body['entities']]
    assert ('bold', '🤖 ИИ: ручной анализ #1') in styled
    assert ('bold', '1. Проверить <b>сервис</b>') in styled
    assert ('italic', '«🙂 *не Markdown*»') in styled
    assert ('mention', '@captain_user') in styled
    assert ('url', 'https://team.example/?project=1&task=2') in styled
    assert all(e['offset'] >= 0 and e['length'] > 0 for e in body['entities'])


@pytest.mark.parametrize(('kind', 'marker'), [
    ('incident_red_created', '🔴'), ('incident_red_confirmed', '🔴'),
    ('incident_yellow_created', '🟡'), ('incident_resolved', '✅'),
    ('ai_recommendation', '🤖'), ('task_assigned', '📌'), ('task_overdue', '⏰'),
])
def test_event_marker_and_readable_sections(monkeypatch, kind, marker):
    db = Mock()
    db.get.return_value = SimpleNamespace(name='Project', public_url=None)
    monkeypatch.setattr(svc, 'mentions', lambda *args: ([], []))
    monkeypatch.setattr('app.deps.project_member_ids', lambda *args: [])
    queued = Mock()
    monkeypatch.setattr(svc, 'enqueue', queued)
    svc.event(db, 1, kind, {'title': 'Details'}, [])
    text = queued.call_args.args[3]
    assert text.startswith(marker + ' ')
    assert '\n\nПроект: Project\n' in text


def test_split_formatted_report_preserves_text_and_offsets(monkeypatch):
    monkeypatch.setattr(vault, 'load', lambda: 'synthetic')
    text = '🤖 ИИ: анализ\n\n' + ('Ситуация: 🙂 <&> «цитата»\n' * 600)
    parts = svc.split_text(text)
    assert ''.join(parts) == text

    def response(request, **kwargs):
        body = json.loads(request.data)
        assert len(body['text'].encode('utf-16-le')) // 2 <= 4096
        for entity in body['entities']:
            assert entity_text(body['text'], entity)
        return io.BytesIO(b'{"ok":true,"result":{"message_id":1}}')

    monkeypatch.setattr(urllib.request, 'urlopen', response)
    for index, part in enumerate(parts, 1):
        TelegramClient().send('-100', None, f'(часть {index}/{len(parts)})\n' + part)
