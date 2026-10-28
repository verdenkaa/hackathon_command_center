"""Таймеры задач: start/pause/stop, расчёт времени и пересечений."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.api.errors import api_error
from app.db.models import Task, TaskTimer, TimerSegment


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def get_timer(db: Session, task_id: int) -> TaskTimer | None:
    return db.query(TaskTimer).filter(TaskTimer.task_id == task_id).first()


def current_elapsed(timer: TaskTimer | None) -> int:
    if timer and timer.state == "running" and timer.last_started_at:
        return max(0, int((_now() - timer.last_started_at).total_seconds()))
    return 0


def total_seconds(timer: TaskTimer | None) -> int:
    if timer is None:
        return 0
    return timer.accumulated_seconds + current_elapsed(timer)


def start_timer(db: Session, task_id: int, *, commit: bool = True) -> TaskTimer:
    from app.services.dependencies import require_ready
    task = db.get(Task, task_id)
    if task:
        require_ready(db, task)
    timer = get_timer(db, task_id)
    if timer and timer.state == "running":
        raise api_error(409, "TIMER_RUNNING", "Таймер уже запущен")
    now = _now()
    task = db.get(Task, task_id)
    if task and task.actual_started_at is None:
        task.actual_started_at = now
    if timer is None:
        timer = TaskTimer(task_id=task_id, state="running", accumulated_seconds=0, last_started_at=now)
        db.add(timer)
    else:
        timer.state = "running"
        timer.last_started_at = now
    db.add(TimerSegment(task_id=task_id, started_at=now))
    if commit:
        db.commit()
        db.refresh(timer)
    else:
        db.flush()
    return timer


def _close_running_segment(db: Session, task_id: int, timer: TaskTimer, now: datetime) -> None:
    segment = (
        db.query(TimerSegment)
        .filter(TimerSegment.task_id == task_id, TimerSegment.ended_at.is_(None))
        .first()
    )
    if segment is not None:
        segment.ended_at = now
        timer.accumulated_seconds += max(0, int((now - segment.started_at).total_seconds()))


def pause_timer(db: Session, task_id: int) -> TaskTimer:
    timer = get_timer(db, task_id)
    if timer is None or timer.state != "running":
        raise api_error(409, "TIMER_NOT_RUNNING", "Таймер не запущен")
    now = _now()
    _close_running_segment(db, task_id, timer, now)
    timer.state = "paused"
    timer.last_started_at = None
    db.commit()
    db.refresh(timer)
    return timer


def stop_timer(db: Session, task_id: int, *, commit: bool = True) -> TaskTimer:
    timer = get_timer(db, task_id)
    if timer is None or timer.state == "stopped":
        raise api_error(409, "TIMER_NOT_ACTIVE", "Таймер не активен")
    if timer.state == "running":
        _close_running_segment(db, task_id, timer, _now())
        timer.last_started_at = None
    timer.state = "stopped"
    if commit:
        db.commit()
        db.refresh(timer)
    else:
        db.flush()
    return timer


def adjust_time(db: Session, task_id: int, accumulated_seconds: int) -> TaskTimer:
    timer = get_timer(db, task_id)
    if timer is None:
        timer = TaskTimer(task_id=task_id, state="stopped", accumulated_seconds=accumulated_seconds)
        db.add(timer)
    else:
        timer.accumulated_seconds = accumulated_seconds
    db.commit()
    db.refresh(timer)
    return timer


def merge_intervals(intervals: list[tuple[datetime, datetime]]) -> int:
    """Суммарная длительность непересекающихся интервалов (секунды)."""
    if not intervals:
        return 0
    intervals = sorted(intervals, key=lambda x: x[0])
    total = 0
    cur_start, cur_end = intervals[0]
    for start, end in intervals[1:]:
        if start <= cur_end:
            cur_end = max(cur_end, end)
        else:
            total += (cur_end - cur_start).total_seconds()
            cur_start, cur_end = start, end
    total += (cur_end - cur_start).total_seconds()
    return int(total)


def project_segments(db: Session, project_id: int) -> list[TimerSegment]:
    return (
        db.query(TimerSegment)
        .join(Task, Task.id == TimerSegment.task_id)
        .filter(Task.project_id == project_id)
        .all()
    )


def project_calendar_seconds(db: Session, project_id: int) -> int:
    intervals = [
        (s.started_at, s.ended_at or _now())
        for s in project_segments(db, project_id)
        if (s.ended_at or _now()) >= s.started_at
    ]
    return merge_intervals(intervals)
