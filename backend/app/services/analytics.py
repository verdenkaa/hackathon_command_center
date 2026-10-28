"""Аналитика: KPI, участники, модули, burn-down, время по участникам, риски."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime

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
from app.operational_schemas import OperationalSummary
from app.services.incidents import traffic_status
from app.services.timers import current_elapsed, get_timer, project_calendar_seconds, total_seconds
from app.timeutil import utcnow
from app.deps import project_member_ids


def _column_ids(db: Session, project_id: int, *keys: str) -> set[int]:
    return {
        c.id
        for c in db.query(BoardColumn)
        .filter(BoardColumn.project_id == project_id, BoardColumn.semantic.in_({'done' if k in ('done','realised') else 'trash' if k == 'trashed' else 'active' if k in ('in_progress','testing','review') else 'normal' for k in keys}))
        .all()
    }


def kpi(db: Session, project_id: int) -> dict:
    project = db.get(Project, project_id)
    now = utcnow()
    tasks = db.query(Task).filter(Task.project_id == project_id).all()
    done_ids = _column_ids(db, project_id, "done", "realised")
    trashed_ids = _column_ids(db, project_id, "trashed")
    active_ids = _column_ids(db, project_id, "in_progress", "testing", "review")

    active_tasks = [t for t in tasks if t.column_id not in trashed_ids]
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
    estimate = sum(t.estimate_seconds or 0 for t in active_tasks)
    actual = sum(total_seconds(get_timer(db, t.id)) for t in active_tasks)
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
        tasks = db.query(Task).filter(Task.project_id == project_id, Task.module_id == m.id,
                                     Task.column_id.notin_(_column_ids(db, project_id, 'trashed'))).all()
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
    events = db.query(AuditEntry).filter(AuditEntry.project_id == project_id,
        AuditEntry.action.in_(['task.created', 'task.moved'])).order_by(AuditEntry.created_at, AuditEntry.id).all()
    if not events:
        return []
    states: dict[str, str | None] = {}
    result: list[dict] = []
    created_count = 0
    for event in events:
        data = event.data or {}
        if event.action == 'task.created':
            created_count += 1
            states[event.entity_id] = data.get('column_semantic')
        else:
            if event.entity_id not in states:
                continue  # Missing creation history cannot be reconstructed reliably.
            key = data.get('key')
            semantic = data.get('to_semantic')
            if semantic is None:
                col = db.get(BoardColumn, data.get('to_column')) if data.get('to_column') else None
                semantic = col.semantic if col else ('done' if key in ('done','realised') else 'trash' if key == 'trashed' else 'normal')
            states[event.entity_id] = semantic
        if all(v is not None for v in states.values()):
            point={'date':event.created_at.isoformat(), 'created':created_count,
                   'completed':sum(v == 'done' for v in states.values()),
                   'remaining':sum(v not in ('done','trash') for v in states.values())}
            if result and result[-1]['date']==point['date']:
                result[-1]=point
            else:
                result.append(point)
    # A current observation is real data; missing historical states are never assumed.
    # Query per task, retaining duplicates when several tasks share a column.
    current = [semantic for (semantic,) in db.query(BoardColumn.semantic).join(Task, Task.column_id == BoardColumn.id).filter(Task.project_id == project_id).all()]
    result.append({'date':utcnow().isoformat(), 'created':len(current), 'completed':current.count('done'),
                   'remaining':sum(v not in ('done','trash') for v in current), 'observation_only':not result})
    # A fixed-scope guide is available only if a deadline follows the first observation.
    project = db.get(Project, project_id)
    start = datetime.fromisoformat(result[0]['date'])
    if not result[0].get('observation_only') and project.deadline_msk and project.deadline_msk > start:
        duration = (project.deadline_msk - start).total_seconds()
        for point in result:
            fraction = (datetime.fromisoformat(point['date']) - start).total_seconds() / duration
            point['ideal'] = max(0, result[0]['remaining'] * (1 - fraction))
    return result


def time_by_user(db: Session, project_id: int) -> list[dict]:
    tasks = db.query(Task).filter(Task.project_id == project_id,
                                 Task.column_id.notin_(_column_ids(db, project_id, 'trashed'))).all()
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
    done_ids = _column_ids(db, project_id, "done", "realised", "trashed")
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


def planning(db: Session, project_id: int, summary: OperationalSummary | None = None) -> dict:
    """Compatibility fields derived from the same current plan as the operational view."""
    from app.services.operational import build_summary
    summary = summary if summary is not None else build_summary(db, project_id)
    remaining = sum(t.estimate_seconds or 0 for t in summary.tasks if t.availability != 'done')
    deviations = []
    now = utcnow()
    for task in summary.tasks:
        actual = task.timer.total_seconds if task.timer else 0
        overrun = max(0, actual - task.estimate_seconds) if task.estimate_seconds is not None else 0
        overdue = max(0, int((now-task.deadline).total_seconds())) if task.availability != 'done' and task.deadline else 0
        if overrun or overdue:
            deviations.append({'task_id':task.id, 'title':task.title, 'actual_seconds':actual,
                               'overrun_seconds':overrun, 'ahead_seconds':0, 'overdue_seconds':overdue,
                               'owners':[a.display_name for a in task.assignees]})
    return {'forecast':{'remaining_seconds':remaining, 'calendar_estimate_seconds':None,
                        'status':summary.plan.status, 'finish':summary.plan.finish,
                        'margin_seconds':-summary.plan.deadline_delta_seconds if summary.plan.deadline_delta_seconds is not None else None,
                        'assumptions':'Текущий план Ганта; таймеры не уменьшают незавершённый объём.'},
            'deviations':deviations}


def analytics(db: Session, project_id: int) -> dict:
    from app.services.operational import build_summary
    summary = build_summary(db, project_id)
    incidents = (
        db.query(Incident)
        .filter(Incident.project_id == project_id, Incident.status != "resolved")
        .all()
    )
    return {
        'summary':summary.model_dump(mode='json'),
        "kpi": kpi(db, project_id),
        **planning(db, project_id, summary),
        "participants": [p.model_dump() for p in participants(db, project_id)],
        "modules": module_progress(db, project_id),
        "burn_down": burn_down(db, project_id),
        "time_by_user": time_by_user(db, project_id),
        "active_incidents": [
            {"id": i.id, "number":i.number, "title": i.title, "level": i.level, "status": i.status}
            for i in incidents
        ],
        "risks": risks(db, project_id),
    }
