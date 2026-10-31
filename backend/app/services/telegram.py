"""Project routing, structured rendering and a leased transactional outbox."""
from __future__ import annotations

from datetime import timedelta
from typing import Callable
from uuid import uuid4

from sqlalchemy import update
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import (TelegramSettings, TelegramDelivery, Project, User, Task, TaskAssignee,
                           Incident, Role, RoleAssignment, AdvisorJob)
from app.integrations.telegram import TelegramError, telegram_client
from app.telegram_schemas import normalize_username
from app.timeutil import utcnow

EVENTS = {
    'task_assigned': 'Назначение задачи', 'task_overdue': 'Просрочка задачи',
    'incident_yellow_created': 'Создание жёлтого инцидента',
    'incident_red_created': 'Запрос серьёзного инцидента',
    'incident_red_confirmed': 'Подтверждение серьёзного инцидента',
    'incident_resolved': 'Закрытие инцидента',
    'ai_recommendation': 'Новая рекомендация ИИ (отдельная)',
    'ai_report': 'Полный отчёт запуска ИИ',
}
EVENT_MARKERS = {
    'task_assigned': '📌', 'task_overdue': '⏰',
    'incident_yellow_created': '🟡', 'incident_red_created': '🔴',
    'incident_red_confirmed': '🔴', 'incident_resolved': '✅',
    'ai_recommendation': '🤖', 'ai_report': '🤖',
}
ERRORS = {
    'KEY_MISSING': 'Токен не подключён или хранилище Windows недоступно',
    'INVALID_TOKEN': 'Токен бота неверен или отозван',
    'BOT_FORBIDDEN': 'Бот удалён из чата или не имеет права отправки',
    'TOPIC_UNAVAILABLE': 'Тема закрыта, удалена или недоступна боту',
    'CHAT_UNAVAILABLE': 'Чат недоступен или ID направления неверен',
    'RATE_LIMIT': 'Ограничение Telegram: повтор после задержки',
    'TEMPORARY': 'Временная ошибка Telegram или соединения',
    'UNKNOWN_RESULT': 'Результат неизвестен: сообщение могло быть отправлено',
    'CONTENT_CHANGED': 'Доставка приостановлена после обезличивания аккаунта. Повтор всего сообщения может дублировать прежние части',
}


def mentions(db: Session, ids: list[int]) -> tuple[list[str], list[str]]:
    names: set[str] = set()
    missing: list[str] = []
    for uid in sorted(set(ids)):
        user = db.get(User, uid)
        if not user or user.deleted_identity:
            continue
        try:
            name = normalize_username(user.telegram_username)
        except ValueError:
            name = None
        if name:
            names.add(name)
        else:
            missing.append(user.display_name)
    return sorted(names), missing


def split_text(text: str) -> list[str]:
    # Limit UTF-16 units conservatively; preserve every character including newlines.
    parts: list[str] = []
    while text:
        units = 0
        end = 0
        for char in text:
            size = 2 if ord(char) > 0xffff else 1
            if units + size > 3800:
                break
            units += size
            end += 1
        if end < len(text):
            boundary = text.rfind('\n', 0, end)
            if boundary > end // 2:
                end = boundary + 1
        parts.append(text[:end])
        text = text[end:]
    return parts


def enqueue(db: Session, project_id: int, event_type: str, text: str, usernames: list[str],
            *, event_key: str | None = None, test_thread: int | None = None) -> TelegramDelivery | None:
    cfg = db.get(TelegramSettings, project_id)
    if not cfg or not cfg.chat_id:
        return None
    route = test_thread if event_type == 'test' else cfg.routes.get(event_type)
    if route is None and event_type != 'test':
        return None
    if event_key and db.query(TelegramDelivery).filter_by(event_key=event_key).first():
        return None
    row = TelegramDelivery(project_id=project_id, event_type=event_type, text=text,
        mentions=usernames, chat_id=cfg.chat_id, thread_id=route or None, mode='live', state='pending',
        event_key=event_key)
    db.add(row)
    db.flush()
    return row


def event(db: Session, project_id: int, ntype: str, payload: dict, recipients: list[int]) -> None:
    if ntype not in EVENTS:
        return
    project = db.get(Project, project_id)
    if project is None:
        return
    lines = [f'{EVENT_MARKERS[ntype]} {EVENTS[ntype]}', '', f'Проект: {project.name}']
    ids = recipients
    if payload.get('task_id'):
        task = db.get(Task, payload['task_id'])
        if not task or task.project_id != project_id:
            return
        lines += ['', f'Задача #{task.id}: {task.title}']
        if task.deadline:
            lines.append(f'Срок: {task.deadline.isoformat()} UTC')
        if ntype == 'task_overdue':
            ids = [a.user_id for a in db.query(TaskAssignee).filter_by(task_id=task.id)]
    elif payload.get('incident_id'):
        incident = db.get(Incident, payload['incident_id'])
        if not incident or incident.project_id != project_id:
            return
        lines += ['', f'Инцидент #{incident.number}: {incident.title}']
        if incident.owner_id:
            owner = db.get(User, incident.owner_id)
            lines.append('Ответственный: ' + (owner.display_name if owner else 'Удалённый пользователь'))
        if ntype == 'incident_resolved':
            lines.append('Решение: ' + (incident.resolution or 'Закрыт'))
    else:
        lines += ['', str(payload.get('title', ''))]
    from app.deps import project_member_ids
    ids = list(set(ids) & set(project_member_ids(db, project_id)))
    names, missing = mentions(db, ids)
    if names:
        lines += ['', ' '.join('@' + name for name in names)]
    if missing:
        lines.append('Без Telegram username: ' + ', '.join(missing))
    cfg = db.get(TelegramSettings, project_id)
    from app.config import settings as app_settings
    from app.services.portable import current_public_url
    url = current_public_url() if app_settings.app_managed else (cfg.public_url if cfg else '')
    if url:
        suffix = f'?project={project_id}'
        if payload.get('task_id'):
            suffix += f'&task={payload["task_id"]}'
        elif payload.get('incident_id'):
            suffix += f'&incident={payload["incident_id"]}'
        lines += ['', 'Открыть: ' + url + suffix]
    enqueue(db, project_id, ntype, '\n'.join(lines), names)


def report(db: Session, job: AdvisorJob, result: dict | None = None) -> None:
    if job.kind != 'analysis':
        return
    project = db.get(Project, job.project_id)
    lines = [f'🤖 ИИ: {"автоматический" if job.trigger == "automatic" else "ручной"} анализ #{job.id}',
             '', f'Проект: {project.name}', '']
    ids: set[int] = set()
    if result is None:
        lines.append('⚠️ Анализ не выполнен: ' + (job.error_code or 'ошибка обработки') + '. Это не положительный результат.')
    else:
        required = result['captain_intervention'] == 'required'
        lines.append('⚠️ Требуется вмешательство капитана' if required else '✅ Вмешательство капитана не требуется')
        if result.get('summary'):
            lines += ['', 'Вывод: ' + result['summary']]
        if required:
            ids.update(r.user_id for r in db.query(RoleAssignment).join(User, User.id == RoleAssignment.user_id)
                .filter(RoleAssignment.project_id == job.project_id, RoleAssignment.role == Role.captain,
                        RoleAssignment.revoked_at.is_(None), User.active.is_(True)))
        if not result['recommendations']:
            lines.append('Проверка завершена. Новых рекомендаций нет.')
        for index, item in enumerate(result['recommendations'], 1):
            lines += ['', f'{index}. {item["title"]}', 'Ситуация: ' + item['situation'],
                      'Основания: ' + '; '.join(item['grounds']), 'Последствия: ' + item['consequence'],
                      'Действие: ' + item['action'], 'Ограничения: ' + '; '.join(item['limitations'])]
            ids.update(item.get('action_user_ids', []))
        names, missing = mentions(db, list(ids))
        if names:
            lines += ['', ' '.join('@' + name for name in names)]
        if missing:
            lines.append('Без Telegram username: ' + ', '.join(missing))
    names, _ = mentions(db, list(ids))
    enqueue(db, job.project_id, 'ai_report', '\n'.join(lines), names, event_key=f'ai-report:{job.id}')


def work_once(factory: sessionmaker[Session], sender: Callable[[str, int | None, str], int] | None = None) -> bool:
    sender = sender or telegram_client.send
    now = utcnow()
    token = uuid4().hex
    with factory() as db:
        # A crashed sender may have delivered: never resend automatically after a lease expires.
        db.query(TelegramDelivery).filter(TelegramDelivery.state == 'sending', TelegramDelivery.lease_until < now).update(
            {'state': 'uncertain', 'error_code': 'UNKNOWN_RESULT', 'lease_token': None})
        row = db.query(TelegramDelivery).filter(TelegramDelivery.state == 'pending',
            TelegramDelivery.next_attempt_at <= now).order_by(TelegramDelivery.id).first()
        if row is None:
            db.commit()
            return False
        delivery_id = row.id
        claimed = db.execute(update(TelegramDelivery).where(TelegramDelivery.id == delivery_id,
            TelegramDelivery.state == 'pending').values(state='sending', lease_token=token,
            lease_until=now + timedelta(minutes=2), attempted_at=now, attempts=TelegramDelivery.attempts + 1))
        db.commit()
        if claimed.rowcount != 1:
            return False
    while True:
        with factory() as db:
            row = db.get(TelegramDelivery, delivery_id)
            if row.state != 'sending' or row.lease_token != token:
                return True
            parts = split_text(row.text)
            position = len(row.message_ids)
            if position >= len(parts):
                row.state, row.sent_at, row.error_code = 'sent', utcnow(), None
                row.lease_token, row.lease_until = None, None
                db.commit()
                return True
            chat, thread, text = row.chat_id, row.thread_id, parts[position]
            if len(parts) > 1:
                text = f'(часть {position + 1}/{len(parts)})\n' + text
        try:
            message_id = sender(chat, thread, text)
            error = None
        except TelegramError as exc:
            error = exc
        except Exception:
            error = TelegramError('UNKNOWN_RESULT', uncertain=True)
        with factory() as db:
            row = db.get(TelegramDelivery, delivery_id)
            if row.state != 'sending' or row.lease_token != token:
                return True
            if error:
                row.error_code = error.code if error.code in ERRORS else 'UNKNOWN_RESULT'
                row.state = 'uncertain' if error.uncertain else 'error'
                if not error.uncertain and error.code in ('RATE_LIMIT', 'TEMPORARY') and row.attempts < 3:
                    row.state = 'pending'
                    row.next_attempt_at = utcnow() + timedelta(seconds=max(error.retry_after, 2 ** row.attempts))
                row.lease_token, row.lease_until = None, None
                db.commit()
                return True
            row.message_ids = [*row.message_ids, message_id]
            row.lease_until = utcnow() + timedelta(minutes=2)
            db.commit()
