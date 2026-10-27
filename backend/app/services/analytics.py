"""Аналитика: KPI, участники, модули, burn-down, время по участникам, риски."""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

from sqlalchemy.orm import Session

from app.db.models import (
    AuditEntry,
    BoardColumn,
    Incident,
    Module,
    Project,
    RoleAssignment,
    Task,
    TaskAssignee,
    TaskTimer,
    User,
)
from app.schemas import ParticipantOut
from app.services.incidents import traffic_status
from app.services.timers import current_elapsed, get_timer, project_calendar_seconds, total_seconds
from app.timeutil import utcnow
from app.deps import project_member_ids


def _column_ids(db: Session, project_id: int, *keys: str) -> set[int]:
    return {
        c.id
        for c in db.query(BoardColumn)
        .filter(BoardColumn.project_id == project_id, BoardColumn.key.in_(keys))
        .all()
    }


def kpi(db: Session, project_id: int) -> dict:
    project = db.get(Project, project_id)
    now = utcnow()
    tasks = db.query(Task).filter(Task.project_id == project_id).all()
    done_ids = _column_ids(db, project_id, "done", "realised")
    trashed_id = next(iter(_column_ids(db, project_id, "trashed")), None)
    active_ids = _column_ids(db, project_id, "in_progress", "testing", "review")

    active_tasks = [t for t in tasks if t.column_id != trashed_id]
    completed = [t for t in active_tasks if t.column_id in done_ids]
    in_progress = [t for t in active_tasks if t.column_id in active_ids]
    overdue = [
        t for t in active_tasks
        if t.column_id not in done_ids and t.deadline is not None and t.deadline < now
    ]
    running = (
        db.query(TaskTimer).join(Task, Task.id == TaskTimer.task_id)
        .filter(Task.project_id == project_id, TaskTimer.state == "running").all()
    )
    running_task_ids = {t.task_id for t in running}
    active_participants = len(
        {a.user_id for a in db.query(TaskAssignee).filter(TaskAssignee.task_id.in_(running_task_ids)).all()}
        if running_task_ids
        else set()
    )
    estimate = sum(t.estimate_seconds or 0 for t in tasks)
    actual = sum(total_seconds(get_timer(db, t.id)) for t in tasks)
    calendar = project_calendar_seconds(db, project_id)
    progress = round((len(completed) / len(active_tasks) * 100) if active_tasks else 0.0, 1)
    return {
        "project_id": project_id,
        "name": project.name,
        "state": project.state.value,
        "deadline_msk": project.deadline_msk.isoformat() if project.deadline_msk else None,
        "deadline_seconds_left": int((project.deadline_msk - now).total_seconds()) if project.deadline_msk else None,
        "total_tasks": len(active_tasks),
        "completed_tasks": len(completed),
        "in_progress_tasks": len(in_progress),
        "overdue_tasks": len(overdue),
        "active_timers": len(running_task_ids),
        "active_participants": active_participants,
        "progress_percent": progress,
        "estimate_seconds": estimate,
        "actual_seconds": actual,
        "calendar_seconds": calendar,
    }


def participants(db: Session, project_id: int) -> list[ParticipantOut]:
    member_ids = project_member_ids(db, project_id)
    done_cols = list(_column_ids(db, project_id, "done", "realised", "trashed"))
    result: list[ParticipantOut] = []
    for uid in member_ids:
        user = db.get(User, uid)
        task_ids = [a.task_id for a in db.query(TaskAssignee).join(Task, Task.id == TaskAssignee.task_id)
                    .filter(TaskAssignee.user_id == uid, Task.project_id == project_id).all()]
        running = (
            db.query(TaskTimer).filter(TaskTimer.task_id.in_(task_ids), TaskTimer.state == "running").all()
            if task_ids
            else []
        )
        active_tasks = (
            db.query(Task).filter(Task.id.in_(task_ids), Task.column_id.notin_(done_cols)).count()
            if task_ids
            else 0
        )
        result.append(
            ParticipantOut(
                id=user.id,
                login=user.login,
                display_name=user.display_name,
                telegram_username=user.telegram_username,
                traffic_status=traffic_status(db, "user", user.id, project_id),
                active_tasks=active_tasks,
                active_timer_seconds=sum(current_elapsed(t) for t in running),
            )
        )
    return result


def module_progress(db: Session, project_id: int) -> list[dict]:
    done_ids = _column_ids(db, project_id, "done", "realised")
    result = []
    for m in db.query(Module).filter(Module.project_id == project_id).all():
        tasks = db.query(Task).filter(Task.module_id == m.id).all()
        done = sum(1 for t in tasks if t.column_id in done_ids)
        result.append(
            {
                "id": m.id,
                "name": m.name,
                "total": len(tasks),
                "done": done,
                "progress": round((done / len(tasks) * 100) if tasks else 0.0, 1),
                "traffic_status": traffic_status(db, "module", m.id),
            }
        )
    return result


def burn_down(db: Session, project_id: int) -> list[dict]:
    created = (
        db.query(AuditEntry)
        .filter(AuditEntry.project_id == project_id, AuditEntry.action == "task.created")
        .order_by(AuditEntry.created_at)
        .all()
    )
    moved = (
        db.query(AuditEntry)
        .filter(AuditEntry.project_id == project_id, AuditEntry.action == "task.moved")
        .order_by(AuditEntry.created_at)
        .all()
    )
    completions: dict[str, object] = {}
    for m in moved:
        key = (m.data or {}).get("key")
        if key in ("done", "realised") and m.entity_id not in completions:
            completions[m.entity_id] = m.created_at.date()

    created_by_date: dict[object, int] = defaultdict(int)
    for c in created:
        created_by_date[c.created_at.date()] += 1
    completed_by_date: dict[object, int] = defaultdict(int)
    for d in completions.values():
        completed_by_date[d] += 1

    today = utcnow().date()
    if not created_by_date and not completed_by_date:
        return []
    start = min([*created_by_date.keys(), *completed_by_date.keys()], default=today)
    result = []
    cum_c = cum_d = 0
    d = start
    while d <= today:
        cum_c += created_by_date.get(d, 0)
        cum_d += completed_by_date.get(d, 0)
        result.append(
            {"date": d.isoformat(), "created": cum_c, "completed": cum_d, "remaining": max(0, cum_c - cum_d)}
        )
        d += timedelta(days=1)
    return result


def time_by_user(db: Session, project_id: int) -> list[dict]:
    tasks = db.query(Task).filter(Task.project_id == project_id).all()
    by_user: dict[int | None, int] = defaultdict(int)
    for t in tasks:
        secs = total_seconds(get_timer(db, t.id))
        if secs <= 0:
            continue
        primary = (
            db.query(TaskAssignee)
            .filter(TaskAssignee.task_id == t.id, TaskAssignee.is_primary.is_(True))
            .first()
        )
        by_user[primary.user_id if primary else None] += secs
    result = []
    for uid, secs in by_user.items():
        if uid is None:
            result.append({"user_id": None, "login": "", "display_name": "Без исполнителя", "seconds": secs})
        else:
            u = db.get(User, uid)
            result.append({"user_id": uid, "login": u.login, "display_name": u.display_name, "seconds": secs})
    result.sort(key=lambda x: -x["seconds"])
    return result


def risks(db: Session, project_id: int) -> list[dict]:
    now = utcnow()
    done_ids = _column_ids(db, project_id, "done", "realised")
    tasks = db.query(Task).filter(Task.project_id == project_id, Task.column_id.notin_(done_ids)).all()
    result = [
        {"type": "overdue", "task_id": t.id, "title": t.title,
         "deadline": t.deadline.isoformat() if t.deadline else None}
        for t in tasks
        if t.deadline is not None and t.deadline < now
    ]
    incidents = db.query(Incident).filter(Incident.project_id == project_id, Incident.status != "resolved").all()
    result.extend(
        {"type": "incident", "incident_id": i.id, "title": i.title, "level": i.level, "status": i.status}
        for i in incidents
    )
    return result


def analytics(db: Session, project_id: int) -> dict:
    incidents = (
        db.query(Incident)
        .filter(Incident.project_id == project_id, Incident.status != "resolved")
        .all()
    )
    return {
        "kpi": kpi(db, project_id),
        "participants": [p.model_dump() for p in participants(db, project_id)],
        "modules": module_progress(db, project_id),
        "burn_down": burn_down(db, project_id),
        "time_by_user": time_by_user(db, project_id),
        "active_incidents": [
            {"id": i.id, "title": i.title, "level": i.level, "status": i.status}
            for i in incidents
        ],
        "risks": risks(db, project_id),
    }
