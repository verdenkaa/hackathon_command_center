"""Сериализация задач и вспомогательные выборки."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models import (
    BoardColumn,
    ChecklistItem,
    Task,
    TaskAssignee,
    TaskDependency,
    User,
    Incident, IncidentTarget,
)
from app.schemas import AssigneeOut, ChecklistItemOut, PredecessorOut, TaskOut, TimerOut
from app.services.timers import current_elapsed, get_timer


def serialize_task(db: Session, task: Task) -> TaskOut:
    column = db.get(BoardColumn, task.column_id)

    assignees: list[AssigneeOut] = []
    for ta, user in (
        db.query(TaskAssignee, User)
        .join(User, User.id == TaskAssignee.user_id)
        .filter(TaskAssignee.task_id == task.id)
        .all()
    ):
        assignees.append(
            AssigneeOut(user_id=user.id, login=user.login, display_name=user.display_name, is_primary=ta.is_primary)
        )

    predecessors = [
        PredecessorOut(task_id=d.predecessor_id, link_type=d.link_type)
        for d in db.query(TaskDependency).filter(TaskDependency.task_id == task.id).all()
    ]

    checklist = [
        ChecklistItemOut.model_validate(c)
        for c in db.query(ChecklistItem)
        .filter(ChecklistItem.task_id == task.id)
        .order_by(ChecklistItem.position)
        .all()
    ]

    timer = get_timer(db, task.id)
    timer_out = None
    if timer is not None:
        elapsed = current_elapsed(timer)
        timer_out = TimerOut(
            state=timer.state,
            accumulated_seconds=timer.accumulated_seconds,
            elapsed_seconds=elapsed,
            total_seconds=timer.accumulated_seconds + elapsed,
        )

    return TaskOut(
        actual_started_at=task.actual_started_at,
        actual_completed_at=task.actual_completed_at,
        id=task.id,
        project_id=task.project_id,
        column_id=task.column_id,
        column_key=column.key if column else "",
        column_title=column.title if column else 'Колонка недоступна',
        column_semantic=column.semantic if column else 'normal',
        blocking_incidents=[{'id':i.id, 'number':i.number, 'title':i.title, 'level':i.level, 'status':i.status}
                            for i in db.query(Incident).join(IncidentTarget, IncidentTarget.incident_id == Incident.id)
                            .filter(Incident.project_id == task.project_id, Incident.status != 'resolved', IncidentTarget.target_type == 'task', IncidentTarget.target_id == task.id).all()],
        module_id=task.module_id,
        parent_id=task.parent_id,
        title=task.title,
        description=task.description,
        priority=task.priority,
        estimate_seconds=task.estimate_seconds,
        deadline=task.deadline,
        tags=task.tags or [],
        version=task.version,
        created_at=task.created_at,
        updated_at=task.updated_at,
        assignees=assignees,
        predecessors=predecessors,
        checklist=checklist,
        timer=timer_out,
    )
