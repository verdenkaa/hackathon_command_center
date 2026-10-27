"""Persistent sandbox identity, summary and project-scoped cleanup."""
from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path
from uuid import uuid4
from contextlib import closing

from sqlalchemy.orm import Session

from app.api.errors import api_error
from app.config import settings
from app.db.models import (Project, ProjectState, Task, BoardColumn, Module, TaskAssignee,
    TaskDependency, ChecklistItem, TaskTimer, TimerSegment, Incident, IncidentTarget, IncidentEvent,
    Document, DocumentLock, AuditEntry, AuditRevision, Notification, AiSettings, AiRecommendation,
    TelegramDelivery, CompletionVote, SandboxRun, User)
from app.services.audit import write_audit
from app.services.board import create_default_columns


def find_workspace(db: Session) -> Project | None:
    return db.query(Project).filter(Project.settings['sandbox'].as_boolean().is_(True)).order_by(Project.id).first()


def workspace_summary(db: Session) -> dict:
    project = find_workspace(db)
    if project is None:
        return {'project_id': None, 'project_name': None, 'state': None, 'counts': {}, 'team': []}
    pid = project.id
    counts = {name: db.query(model).filter(model.project_id == pid).count()
              for name, model in [('tasks', Task), ('columns', BoardColumn), ('modules', Module),
                  ('incidents', Incident), ('recommendations', AiRecommendation),
                  ('telegram', TelegramDelivery), ('notifications', Notification)]}
    counts['running_timers'] = db.query(TaskTimer).join(Task, Task.id == TaskTimer.task_id).filter(
        Task.project_id == pid, TaskTimer.state == 'running').count()
    counts['runs'] = db.query(SandboxRun).count()
    team: list[dict] = []
    for role_key, uid in project.settings.get('sandbox_team', {}).items():
        user = db.get(User, uid)
        if user is not None:
            team.append({'user_id': user.id, 'login': user.login, 'display_name': user.display_name,
                         'role': 'captain' if role_key == 'cap' else 'participant', 'active': user.active})
    return {'project_id': pid, 'project_name': project.name, 'state': project.state.value, 'counts': counts, 'team': team}


def reset_workspace(db: Session, project_id: int, actor_id: int) -> Path:
    project = find_workspace(db)
    if project is None or project.id != project_id:
        raise api_error(409, 'NOT_SANDBOX', 'Очистка разрешена только для зарегистрированной песочницы')
    task_ids = [t[0] for t in db.query(Task.id).filter(Task.project_id == project_id).all()]
    # A corrupt legacy link must not cause a mutation in another project.
    foreign_link = db.query(TaskDependency).filter(
        TaskDependency.task_id.in_(task_ids) != TaskDependency.predecessor_id.in_(task_ids)).first()
    foreign_child = db.query(Task).filter(Task.project_id != project_id, Task.parent_id.in_(task_ids)).first()
    if foreign_link or foreign_child:
        raise api_error(409, 'SANDBOX_REFERENCED', 'Есть межпроектная связь; очистка отменена')
    bind = db.get_bind()
    if bind.dialect.name != 'sqlite' or not bind.engine.url.database:
        raise api_error(409, 'BACKUP_UNAVAILABLE', 'Для безопасной очистки нужна файловая SQLite')
    db.commit()
    archives = (settings.data_dir / 'sandbox-archives').resolve()
    archives.mkdir(parents=True, exist_ok=True)
    archive = archives / f'reset-{project_id}-{uuid4().hex}.db'
    with closing(sqlite3.connect(bind.engine.url.database)) as source, closing(sqlite3.connect(archive)) as target:
        source.backup(target)
        if target.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
            raise api_error(409, 'BACKUP_FAILED', 'Проверка резервной копии не пройдена')
    incident_ids = [i[0] for i in db.query(Incident.id).filter(Incident.project_id == project_id).all()]
    document_ids = [d[0] for d in db.query(Document.id).filter(Document.project_id == project_id).all()]
    audit_ids = [a[0] for a in db.query(AuditEntry.id).filter(AuditEntry.project_id == project_id).all()]
    documents_root = (settings.data_dir / 'documents').resolve()
    documents = (documents_root / str(project_id)).resolve()
    saved_documents = archive.with_suffix('') / 'documents'
    if documents.parent != documents_root or not saved_documents.resolve().is_relative_to(archives):
        raise api_error(409, 'INVALID_ARCHIVE_PATH', 'Некорректный путь архива')
    moved = False
    try:
        if documents.exists():
            saved_documents.parent.mkdir(parents=True)
            shutil.move(str(documents), str(saved_documents))
            moved = True
        for model, condition in [
            (TaskDependency, TaskDependency.task_id.in_(task_ids)),
            (TaskAssignee, TaskAssignee.task_id.in_(task_ids)), (ChecklistItem, ChecklistItem.task_id.in_(task_ids)),
            (TimerSegment, TimerSegment.task_id.in_(task_ids)), (TaskTimer, TaskTimer.task_id.in_(task_ids)),
            (IncidentEvent, IncidentEvent.incident_id.in_(incident_ids)),
            (IncidentTarget, IncidentTarget.incident_id.in_(incident_ids)),
            (DocumentLock, DocumentLock.document_id.in_(document_ids)),
            (AuditRevision, AuditRevision.audit_entry_id.in_(audit_ids))]:
            db.query(model).filter(condition).delete(synchronize_session=False)
        db.query(Task).filter(Task.project_id == project_id).update({Task.parent_id: None}, synchronize_session=False)
        for model in [Task, Incident, Document, Notification, TelegramDelivery, AiRecommendation,
                      AiSettings, CompletionVote, AuditEntry, Module, BoardColumn]:
            db.query(model).filter(model.project_id == project_id).delete(synchronize_session=False)
        db.query(SandboxRun).delete(synchronize_session=False)
        project.state = ProjectState.active
        project.deadline_msk = None
        project.settings = {'sandbox': True, 'sandbox_team': project.settings.get('sandbox_team', {})}
        create_default_columns(db, project_id)
        write_audit(db, action='sandbox.reset', actor_id=actor_id,
                    data={'project_id': project_id, 'archive': archive.name})
        db.commit()
    except Exception:
        db.rollback()
        if moved:
            shutil.move(str(saved_documents), str(documents))
        raise
    return archive
