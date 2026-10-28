"""Фоновые задачи: просрочки, очистка блокировок."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models import (
    BoardColumn,
    DocumentLock,
    Notification,
    Project,
    Task,
)
from app.services.notifications import notify_users, team
from app.timeutil import utcnow


def cleanup_locks(db: Session) -> int:
    from datetime import timedelta

    from app.services.documents import LOCK_TTL

    expired = (
        db.query(DocumentLock)
        .filter(DocumentLock.last_activity_at < utcnow() - LOCK_TTL)
        .all()
    )
    for lock in expired:
        db.delete(lock)
    if expired:
        db.commit()
    return len(expired)


def check_overdue(db: Session, project_id: int | None = None) -> int:
    created = 0
    query = db.query(Project).filter(Project.state != "completed")
    if project_id is not None:
        query = query.filter(Project.id == project_id)
    projects = query.all()
    now = utcnow()
    for project in projects:
        done_ids = {
            c.id
            for c in db.query(BoardColumn)
            .filter(BoardColumn.project_id == project.id, BoardColumn.semantic.in_(['done', 'trash']))
            .all()
        }
        overdue = (
            db.query(Task)
            .filter(
                Task.project_id == project.id,
                Task.column_id.notin_(done_ids),
                Task.deadline.isnot(None),
                Task.deadline < now,
            )
            .all()
        )
        existing = (
            db.query(Notification)
            .filter(Notification.project_id == project.id, Notification.type == "task_overdue")
            .all()
        )
        notified_ids = {n.payload.get("task_id") for n in existing}
        for task in overdue:
            if task.id in notified_ids:
                continue
            notify_users(
                db,
                project_id=project.id,
                user_ids=team(db, project.id),
                ntype="task_overdue",
                payload={"task_id": task.id, "title": task.title},
                telegram_text=f"⏰ Просрочена задача: {task.title}",
            )
            created += 1
            from app.services.ai import maybe_recommend
            maybe_recommend(db, project.id, 'overdue')
        db.commit()
    return created


def run_all_jobs(db: Session) -> dict:
    return {
        "locks_cleaned": cleanup_locks(db),
        "overdue_notified": check_overdue(db),
        'deadline_ai': check_deadline_ai(db),
    }


def check_deadline_ai(db: Session) -> int:
    from datetime import timedelta
    from app.services.ai import maybe_recommend
    now = utcnow()
    projects = db.query(Project).filter(Project.state != 'completed', Project.deadline_msk > now,
        Project.deadline_msk <= now + timedelta(hours=6)).all()
    count = sum(int(maybe_recommend(db, p.id, 'deadline_6h')) for p in projects)
    db.commit()
    return count
