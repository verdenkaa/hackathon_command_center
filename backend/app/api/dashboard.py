"""Дашборд проекта: KPI, прогресс, план/факт, риски."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.errors import api_error
from app.db.models import BoardColumn, Project, Task, TaskAssignee, TaskTimer, User
from app.deps import get_db, require_member
from app.schemas import DashboardOut, ProjectOut
from app.services import timers as timer_svc
from app.timeutil import utcnow

router = APIRouter(tags=["dashboard"])


def _column_id(db: Session, project_id: int, key: str) -> int | None:
    col = db.query(BoardColumn).filter(BoardColumn.project_id == project_id, BoardColumn.key == key).first()
    return col.id if col else None


@router.get("/projects/{project_id}/dashboard", response_model=DashboardOut)
def dashboard(project_id: int, db: Session = Depends(get_db), _u=Depends(require_member)) -> DashboardOut:
    project = db.get(Project, project_id)
    if project is None:
        raise api_error(404, "NOT_FOUND", "Проект не найден")

    now = utcnow()
    tasks = db.query(Task).filter(Task.project_id == project_id).all()

    done_id = _column_id(db, project_id, "done")
    realised_id = _column_id(db, project_id, "realised")
    trashed_id = _column_id(db, project_id, "trashed")
    in_progress_ids = {
        _column_id(db, project_id, k)
        for k in ("in_progress", "testing", "review")
    }

    active_tasks = [t for t in tasks if t.column_id != trashed_id]
    completed = [t for t in active_tasks if t.column_id in (done_id, realised_id)]
    in_progress = [t for t in active_tasks if t.column_id in in_progress_ids]

    overdue = [
        t for t in active_tasks
        if t.column_id not in (done_id, realised_id) and t.deadline is not None and t.deadline < now
    ]

    running_timers = (
        db.query(TaskTimer).join(Task, Task.id == TaskTimer.task_id)
        .filter(Task.project_id == project_id, TaskTimer.state == "running").all()
    )
    running_task_ids = {t.task_id for t in running_timers}
    active_participants = len(
        {
            a.user_id
            for a in db.query(TaskAssignee).filter(TaskAssignee.task_id.in_(running_task_ids)).all()
        }
        if running_task_ids
        else []
    )

    estimate_seconds = sum(t.estimate_seconds or 0 for t in tasks)
    actual_seconds = sum(
        timer_svc.total_seconds(timer_svc.get_timer(db, t.id)) for t in tasks
    )
    calendar_seconds = timer_svc.project_calendar_seconds(db, project_id)

    progress = round((len(completed) / len(active_tasks) * 100) if active_tasks else 0.0, 1)

    risks = [
        {"task_id": t.id, "title": t.title, "deadline": t.deadline.isoformat() if t.deadline else None, "type": "overdue"}
        for t in overdue
    ]

    return DashboardOut(
        project=ProjectOut.model_validate(project),
        deadline_seconds_left=int((project.deadline_msk - now).total_seconds()) if project.deadline_msk else None,
        total_tasks=len(active_tasks),
        completed_tasks=len(completed),
        in_progress_tasks=len(in_progress),
        overdue_tasks=len(overdue),
        active_timers=len(running_task_ids),
        active_participants=active_participants,
        progress_percent=progress,
        estimate_seconds=estimate_seconds,
        actual_seconds=actual_seconds,
        calendar_seconds=calendar_seconds,
        risks=risks,
    )
