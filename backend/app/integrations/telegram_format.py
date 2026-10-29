"""Telegram entities over literal text; offsets use UTF-16, including emoji."""
from __future__ import annotations

import re
from typing import TypedDict


class Entity(TypedDict):
    type: str
    offset: int
    length: int


def message_entities(text: str) -> list[Entity]:
    entities: list[Entity] = []

    def add(kind: str, start: int, end: int) -> None:
        if end > start:
            entities.append({'type': kind, 'offset': len(text[:start].encode('utf-16-le')) // 2,
                             'length': len(text[start:end].encode('utf-16-le')) // 2})

    # Explicit entities preserve clickable mentions and links alongside styling.
    for match in re.finditer(r'(?<![\w@])@[A-Za-z][A-Za-z0-9_]{4,31}\b|https?://[^\s<>]+', text):
        add('mention' if match.group().startswith('@') else 'url', match.start(), match.end())

    offset = 0
    labels = ('Проект', 'Задача #', 'Инцидент #', 'Срок', 'Ответственный', 'Решение',
              'Вывод', 'Ситуация', 'Основания', 'Последствия', 'Действие', 'Ограничения',
              'Без Telegram username', 'Открыть')
    for raw in text.splitlines(keepends=True):
        line = raw.rstrip('\r\n')
        # Leave room for Telegram's entity limit; links/mentions take priority.
        if len(entities) <= 98:
            if line.startswith(('🔴 ', '🟡 ', '✅ ', '🤖 ', '📌 ', '⏰ ', '🧪 ')) or re.match(r'^\d+\. ', line):
                add('bold', offset, offset + len(line))
            elif line.startswith(labels) and ': ' in line:
                label, value = line.split(': ', 1)
                add('bold', offset, offset + len(label) + 1)
                if label in ('Вывод', 'Ситуация', 'Решение'):
                    add('italic', offset + len(label) + 2, offset + len(line))
        offset += len(raw)
    return sorted(entities, key=lambda entity: (entity['offset'], -entity['length']))
