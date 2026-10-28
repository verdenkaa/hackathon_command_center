"""Таймеры задач: запуск/пауза/остановка и ручная корректировка."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.errors import api_error
from app.db.models import Task, User
from app.deps import ensure_project_active, get_db, require_captain_or_admin, require_member
from app.schemas import TimeAdjustment, TimerOut
from app.services import timers
from app.services.audit import write_audit

router = APIRouter(tags=["timers"])


def _task(db: Session, task_id: int) -> Task:
    task = db.get(Task, task_id)
    if task is None:
        raise api_error(404, "NOT_FOUND", "Задача не найдена")
    ensure_project_active(db, task.project_id)
    return task


def _out(timer) -> TimerOut:
    elapsed = timers.current_elapsed(timer)
    return TimerOut(
        state=timer.state,
        accumulated_seconds=timer.accumulated_seconds,
        elapsed_seconds=elapsed,
        total_seconds=timer.accumulated_seconds + elapsed,
    )


@router.post("/tasks/{task_id}/timer/start", response_model=TimerOut)
def timer_start(task_id: int, db: Session = Depends(get_db), _u=Depends(require_member)) -> TimerOut:
    from app.services import planning
    task = _task(db, task_id)
    change = planning.begin(db, task.project_id)
    timer = timers.start_timer(db, task_id, commit=False)
    planning.finish(db, change)
    db.commit()
    return _out(timer)


@router.post("/tasks/{task_id}/timer/pause", response_model=TimerOut)
def timer_pause(task_id: int, db: Session = Depends(get_db), _u=Depends(require_member)) -> TimerOut:
    _task(db, task_id)
    return _out(timers.pause_timer(db, task_id))


@router.post("/tasks/{task_id}/timer/stop", response_model=TimerOut)
def timer_stop(task_id: int, db: Session = Depends(get_db), _u=Depends(require_member)) -> TimerOut:
    _task(db, task_id)
    return _out(timers.stop_timer(db, task_id))


@router.post("/tasks/{task_id}/time-adjustment", response_model=TimerOut)
def time_adjustment(
    task_id: int,
    body: TimeAdjustment,
    db: Session = Depends(get_db),
    user: User = Depends(require_captain_or_admin),
) -> TimerOut:
    task = _task(db, task_id)
    timer = timers.adjust_time(db, task_id, body.accumulated_seconds)
    write_audit(db, action="task.time_adjusted", actor_id=user.id, project_id=task.project_id, entity_type="task", entity_id=task.id,
                data={"accumulated_seconds": body.accumulated_seconds})
    db.commit()
    db.refresh(timer)
    return _out(timer)
