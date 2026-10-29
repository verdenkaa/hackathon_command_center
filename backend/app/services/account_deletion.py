"""Delete credentials/PII while retaining a shared, non-login historical identity."""
from __future__ import annotations

import hashlib
import json
import re
from uuid import uuid4
from typing import Any

from sqlalchemy import JSON, Text, select, update, delete
from sqlalchemy.orm import Session

from app.api.errors import api_error
from app.db.base import Base
from app.db.models import (User, RoleAssignment, Role, Task, TaskAssignee, Incident, IncidentEvent,
                           Project, Notification, Session as LoginSession, DocumentLock, CompletionVote,
                           AdvisorJob, IncidentTarget, LoginEvent, AuditEntry)
from app.services.audit import write_audit
from app.telegram_schemas import DeleteAccount
from app.timeutil import utcnow

LIMITS = ('Удаляются учётные данные, роли, сессии и копии известных личных данных в БД. '
          'Проектная история сохраняется под именем «Удалённый пользователь». '
          'Файлы документов, резервные копии, внешние логи и уже отправленные сообщения Telegram '
          'не очищаются. Свободный текст без точного совпадения имени/логина может сохраняться.')


def references_user(value: Any, user_id: int, key: str = '') -> bool:
    if isinstance(value, dict):
        if key in ('participants', 'users', 'assignees') and value.get('id') == user_id:
            return True
        return any(references_user(v, user_id, k) for k, v in value.items())
    if isinstance(value, list):
        return any(references_user(v, user_id, key) for v in value)
    return isinstance(value, int) and not isinstance(value, bool) and value == user_id and (
        key.endswith('user_id') or key.endswith('user_ids') or key in ('assignee_ids','actor_id','author_id','owner_id','status_by'))


def target(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if not user or user.deleted_identity:
        raise api_error(404, 'NOT_FOUND', 'Пользователь не найден')
    if user.active:
        raise api_error(409, 'ACCOUNT_ACTIVE', 'Сначала отключите аккаунт')
    return user


def preview(db: Session, user_id: int) -> dict[str, Any]:
    user = target(db, user_id)
    tasks = []
    for assignment in db.query(TaskAssignee).filter_by(user_id=user_id).order_by(TaskAssignee.task_id):
        task = db.get(Task, assignment.task_id)
        remaining = db.query(TaskAssignee).filter(TaskAssignee.task_id == task.id, TaskAssignee.user_id != user_id).order_by(TaskAssignee.user_id).all()
        tasks.append({'id': task.id, 'title': task.title, 'project_id': task.project_id,
                      'project': db.get(Project, task.project_id).name, 'version': task.version,
                      'needs_primary': assignment.is_primary and bool(remaining),
                      'remaining': [{'id': a.user_id, 'name': db.get(User, a.user_id).display_name,
                                     'is_primary': a.is_primary} for a in remaining]})
    incidents = db.query(Incident).filter(Incident.owner_id == user_id, Incident.status != 'resolved').order_by(Incident.id).all()
    projects = []
    for pid in sorted({i.project_id for i in incidents}):
        captains = db.query(User).join(RoleAssignment, RoleAssignment.user_id == User.id).filter(
            RoleAssignment.project_id == pid, RoleAssignment.role == Role.captain,
            RoleAssignment.revoked_at.is_(None), User.active.is_(True), User.deleted_identity.is_(False)).order_by(User.id).all()
        projects.append({'id': pid, 'name': db.get(Project, pid).name,
                         'captains': [{'id': u.id, 'name': u.display_name} for u in captains],
                         'incidents': [{'id': i.id, 'number': i.number, 'title': i.title} for i in incidents if i.project_id == pid]})
    links: dict[str, int] = {}
    for table in Base.metadata.sorted_tables:
        for column in table.columns:
            if any(fk.target_fullname == 'users.id' for fk in column.foreign_keys):
                count = len(db.execute(select(table.c.id).where(column == user_id)).all()) if 'id' in table.c else 0
                if count:
                    links[f'{table.name}.{column.name}'] = count
    value = {'tasks': tasks, 'projects': projects, 'links': links,
             'blocked': any(not p['captains'] for p in projects), 'deletion_limits': LIMITS}
    digest = json.dumps([value, user.login, user.display_name, user.telegram_username], sort_keys=True, ensure_ascii=False)
    value['version'] = hashlib.sha256(digest.encode()).hexdigest()
    return value


def erase(db: Session, user_id: int, body: DeleteAccount, actor_id: int) -> None:
    # Obtain the SQLite write lock before reading dependencies; concurrent writers cannot alter this plan.
    db.execute(update(User).where(User.id == user_id).values(active=User.active))
    user = target(db, user_id)
    plan = preview(db, user_id)
    if plan['blocked']:
        raise api_error(409, 'CAPTAIN_REQUIRED', 'Назначьте активного капитана каждому затронутому проекту')
    if body.preview_version != plan['version']:
        raise api_error(409, 'PREVIEW_STALE', 'Связи изменились. Обновите предварительный обзор')
    if set(body.incident_captains) != {p['id'] for p in plan['projects']}:
        raise api_error(409, 'CAPTAIN_REQUIRED', 'Выберите капитана для каждого проекта с открытыми инцидентами')
    needed = {t['id'] for t in plan['tasks'] if t['needs_primary']}
    if set(body.task_primaries) != needed:
        raise api_error(409, 'PRIMARY_REQUIRED', 'Выберите основного из оставшихся исполнителей каждой затронутой задачи')
    for task in plan['tasks']:
        if task['needs_primary'] and body.task_primaries[task['id']] not in {a['id'] for a in task['remaining']}:
            raise api_error(409, 'INVALID_PRIMARY', 'Основной должен быть выбран из оставшихся исполнителей')
    for project in plan['projects']:
        if body.incident_captains[project['id']] not in {c['id'] for c in project['captains']}:
            raise api_error(409, 'INVALID_CAPTAIN', 'Ответственный должен быть активным капитаном этого проекта')
    # All validations precede mutations. Every following operation shares one transaction.
    tombstone = db.query(User).filter_by(deleted_identity=True).first()
    if tombstone is None:
        tombstone = User(login='deleted-' + uuid4().hex, password_hash='', display_name='Удалённый пользователь',
                         active=False, deleted_identity=True)
        db.add(tombstone)
        db.flush()
    for task in plan['tasks']:
        db.query(TaskAssignee).filter_by(task_id=task['id'], user_id=user_id).delete()
        if task['needs_primary']:
            for assignment in db.query(TaskAssignee).filter_by(task_id=task['id']):
                assignment.is_primary = assignment.user_id == body.task_primaries[task['id']]
        db.get(Task, task['id']).version += 1
        write_audit(db, action='task.assignees_set', actor_id=actor_id, project_id=task['project_id'],
                    entity_type='task', entity_id=task['id'], data={'removed_user_id': tombstone.id,
                    'user_ids': [a['id'] for a in task['remaining']], 'reason': 'account_deleted'})
    for project in plan['projects']:
        captain_id = body.incident_captains[project['id']]
        for item in project['incidents']:
            incident = db.get(Incident, item['id'])
            incident.owner_id = captain_id
            data = {'old_owner_id': tombstone.id, 'new_owner_id': captain_id, 'reason': 'account_deleted'}
            db.add(IncidentEvent(incident_id=incident.id, actor_id=actor_id, event_type='owner_reassigned', data=data))
            write_audit(db, action='incident.owner_reassigned', actor_id=actor_id, project_id=project['id'],
                        entity_type='incident', entity_id=incident.id, data=data)
    # Cancel running jobs whose stored snapshots contain PII; an in-flight provider cannot write it back.
    for job in db.query(AdvisorJob).filter(AdvisorJob.state.in_(('queued', 'waiting', 'running'))):
        if job.user_id == user_id or references_user(job.snapshot, user_id):
            job.state, job.error_code, job.finished_at = 'cancelled', 'ACCOUNT_DELETED', utcnow()
            job.lease_token = None
    db.flush()
    db.query(IncidentTarget).filter_by(target_type='user', target_id=user_id).update({'target_id': tombstone.id})
    db.query(LoginEvent).filter((LoginEvent.user_id == user_id) | (LoginEvent.login == user.login)).update(
        {'login': 'Удалённый пользователь', 'ip': None}, synchronize_session=False)
    for model in (RoleAssignment, LoginSession, Notification, DocumentLock, CompletionVote):
        db.query(model).filter(model.user_id == user_id).delete(synchronize_session=False)
    db.flush()
    # Keep historical FKs valid, including non-null author IDs and baseline actors.
    for table in Base.metadata.sorted_tables:
        for column in table.columns:
            if any(fk.target_fullname == 'users.id' for fk in column.foreign_keys):
                db.execute(update(table).where(column == user_id).values({column.name: tombstone.id}))
    tokens = [s for s in [user.telegram_username, '@' + user.telegram_username if user.telegram_username else None,
                          user.login, user.display_name, user.avatar] if s]
    for entry in db.query(AuditEntry).filter_by(entity_type='user', entity_id=str(user_id)):
        if entry.action in {'user.created','user.login_changed','user.name_changed','user.telegram_changed'}:
            tokens.extend(value for key, value in entry.data.items()
                          if key in {'old','new','login','display_name','telegram_username'} and isinstance(value,str) and value)
    pattern = re.compile(r'(?<![\w])(?:' + '|'.join(re.escape(s) for s in sorted(set(tokens), key=len, reverse=True)) + r')(?![\w])', re.IGNORECASE)
    def scrub(value: Any, key: str = '') -> Any:
        if isinstance(value, str):
            if key in {'role','state','status','target_type','event_type','mode','provider','trigger',
                       'freshness','significance','semantic','column_key','column_semantic','timezone',
                       'result','captain_intervention'}:
                return value
            return pattern.sub('Удалённый пользователь', value)
        if isinstance(value, list):
            return [scrub(v, key) for v in value]
        if isinstance(value, dict):
            cleaned = {k: scrub(v, k) for k, v in value.items()}
            if key in ('participants', 'users', 'assignees') and value.get('id') == user_id:
                cleaned['id'] = tombstone.id
            if value.get('target_type') == 'user' and value.get('target_id') == user_id:
                cleaned['target_id'] = tombstone.id
            return cleaned
        if isinstance(value, int) and not isinstance(value, bool) and value == user_id and (key.endswith('user_id') or key.endswith('user_ids') or key in ('assignee_ids','author_id','actor_id','owner_id','status_by')):
            return tombstone.id
        return value
    # Known copied text and JSON (AI snapshots, notifications, audit revisions, outbox).
    for table in Base.metadata.sorted_tables:
        if table.name == 'users':
            continue
        fields = [c for c in table.columns if isinstance(c.type, (JSON, Text)) or (table.name == 'login_events' and c.name == 'login')]
        if not fields or 'id' not in table.c:
            continue
        for row in db.execute(select(table)).mappings().all():
            changes = {c.name: scrub(row[c.name]) for c in fields if scrub(row[c.name]) != row[c.name]}
            if changes:
                if table.name == 'telegram_deliveries' and row['state'] in ('sending', 'pending') and (row['message_ids'] or row['state'] == 'sending'):
                    # Chunk boundaries can shift after redaction. Require an explicit whole-message retry.
                    changes.update(state='uncertain', error_code='CONTENT_CHANGED', lease_token=None, lease_until=None)
                db.execute(update(table).where(table.c.id == row['id']).values(**changes))
    # Remove stale in-memory ORM copies before committing Core redactions.
    db.expire_all()
    db.execute(delete(User).where(User.id == user_id))
    write_audit(db, action='user.deleted', actor_id=actor_id, entity_type='user', entity_id=tombstone.id,
                data={'identity': 'Удалённый пользователь', 'limits': LIMITS})
    db.commit()
