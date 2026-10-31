import io
import json
import urllib.error
from unittest.mock import patch

import pytest

from control.telegram import DeliveryError, send_alert, send_backup


@pytest.mark.parametrize('description,expected', [
    ('Bad Request: chat not found', 'чат'),
    ('Bad Request: message thread not found', 'тем'),
    ('Forbidden: bot is not a member of the channel chat', 'бот'),
    ('Unauthorized', 'токен'),
])
def test_telegram_response_is_actionable_without_echoing_tokens(description, expected):
    body = io.BytesIO(json.dumps({'ok': False, 'description': description}).encode())
    error = urllib.error.HTTPError('https://secret', 400, 'bad', {}, body)
    with patch('urllib.request.urlopen', side_effect=error), pytest.raises(DeliveryError) as result:
        send_backup('PRIVATE_TOKEN', '-1001', 1, b'archive', {'id': 'abc', 'created': 1}, 'qa')
    assert expected in str(result.value).lower()
    assert 'PRIVATE_TOKEN' not in str(result.value)
    assert 'неопредел' not in str(result.value).lower()


def test_alert_uses_separate_chat_and_plain_username():
    response = io.BytesIO(b'{"ok":true,"result":{"message_id":1}}')
    with patch('urllib.request.urlopen', return_value=response) as request:
        send_alert('PRIVATE_TOKEN', '-2002', 12, 'Docker: готов → сбой', 'server_admin')
    payload = json.loads(request.call_args.args[0].data)
    assert payload['chat_id'] == '-2002'
    assert payload['message_thread_id'] == 12
    assert '@server_admin' in payload['text']
    assert payload['parse_mode'] == 'HTML'
    assert '<b>' in payload['text']


def test_formatted_alert_escapes_user_content_and_marks_status():
    response = io.BytesIO(b'{"ok":true}')
    with patch('urllib.request.urlopen', return_value=response) as request:
        send_alert('TOKEN','-100',None,'Штаб <unsafe> · 29.10 13:49\nПлатформа: ожидает запуска → сбой. <script>','server_admin')
    body=json.loads(request.call_args.args[0].data)
    assert '🔴' in body['text']
    assert '&lt;script&gt;' in body['text']
    assert '<script>' not in body['text']
    assert '<i>' in body['text']
