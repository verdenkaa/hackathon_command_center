"""Durable project change numbers, written in the same transaction as the edit."""
from __future__ import annotations

from sqlalchemy import event
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session, SessionTransaction

from app.db.models import PlanningState, Project, Task


@event.listens_for(Session, 'before_flush')
def mark_changes(db: Session, _context: object, _instances: object) -> None:
    projects: set[int] = set()
    for obj in list(db.new) + list(db.dirty) + list(db.deleted):
        if obj in db.dirty and not db.is_modified(obj, include_collections=False):
            continue
        project_id = obj.id if isinstance(obj, Project) else getattr(obj, 'project_id', None)
        task_id = getattr(obj, 'task_id', None)
        if project_id is None and task_id is not None:
            task = db.get(Task, task_id)
            project_id = task.project_id if task else None
        if project_id is not None:
            projects.add(project_id)
    marked: set[int] = db.info.setdefault('realtime_projects', set())
    for project_id in projects - marked:
        # A new project is not yet inserted at before_flush time.
        if db.get(Project, project_id) is None:
            continue
        stmt = insert(PlanningState).values(project_id=project_id, revision=1)
        db.execute(stmt.on_conflict_do_update(index_elements=['project_id'],
                   set_={'revision':PlanningState.revision + 1}))
        state = db.get(PlanningState, project_id)
        if state is not None:
            db.expire(state)
        marked.add(project_id)


@event.listens_for(Session, 'after_transaction_end')
def clear_changes(db: Session, transaction: SessionTransaction) -> None:
    if transaction.parent is None:
        db.info.pop('realtime_projects', None)
