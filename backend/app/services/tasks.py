"""Сериализация задач и вспомогательные выборки."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.db.models import (
    BoardColumn,
    ChecklistItem,
    Task,
    TaskAssignee,
    TaskDependency,
    TaskTimer,
    User,
    Incident, IncidentTarget,
)
from app.schemas import AssigneeOut, ChecklistItemOut, PredecessorOut, TaskOut, TimerOut
from app.services.timers import current_elapsed, get_timer


@dataclass
class TaskRelations:
    columns: dict[int, BoardColumn]
    assignees: dict[int, list[AssigneeOut]]
    predecessors: dict[int, list[PredecessorOut]]
    checklists: dict[int, list[ChecklistItemOut]]
    timers: dict[int, TaskTimer]
    incidents: dict[int, list[dict]]


def serialize_tasks(db: Session, tasks: list[Task]) -> list[TaskOut]:
    if not tasks:
        return []
    ids = [t.id for t in tasks]
    related = TaskRelations(
        columns={c.id: c for c in db.query(BoardColumn).filter(BoardColumn.id.in_({t.column_id for t in tasks})).all()},
        assignees=defaultdict(list), predecessors=defaultdict(list), checklists=defaultdict(list),
        timers={t.task_id: t for t in db.query(TaskTimer).filter(TaskTimer.task_id.in_(ids)).all()},
        incidents=defaultdict(list),
    )
    for assignment, user in db.query(TaskAssignee, User).join(User, User.id == TaskAssignee.user_id).filter(TaskAssignee.task_id.in_(ids)).all():
        related.assignees[assignment.task_id].append(AssigneeOut(user_id=user.id, login=user.login,
            display_name=user.display_name, is_primary=assignment.is_primary))
    for link in db.query(TaskDependency).filter(TaskDependency.task_id.in_(ids)).all():
        related.predecessors[link.task_id].append(PredecessorOut(task_id=link.predecessor_id, link_type=link.link_type))
    for item in db.query(ChecklistItem).filter(ChecklistItem.task_id.in_(ids)).order_by(ChecklistItem.position).all():
        related.checklists[item.task_id].append(ChecklistItemOut.model_validate(item))
    for incident, target in db.query(Incident, IncidentTarget).join(IncidentTarget, IncidentTarget.incident_id == Incident.id).filter(
        Incident.status != 'resolved', IncidentTarget.target_type == 'task', IncidentTarget.target_id.in_(ids),
        Incident.project_id.in_({t.project_id for t in tasks}),
    ).all():
        related.incidents[target.target_id].append({'id':incident.id, 'number':incident.number,
            'title':incident.title, 'level':incident.level, 'status':incident.status})
    return [serialize_task(db, task, related) for task in tasks]


def serialize_task(db: Session, task: Task, related: TaskRelations | None = None) -> TaskOut:
    column = related.columns.get(task.column_id) if related else db.get(BoardColumn, task.column_id)

    assignees: list[AssigneeOut] = []
    for ta, user in ([] if related else (
        db.query(TaskAssignee, User)
        .join(User, User.id == TaskAssignee.user_id)
        .filter(TaskAssignee.task_id == task.id)
        .all()
    )):
        assignees.append(
            AssigneeOut(user_id=user.id, login=user.login, display_name=user.display_name, is_primary=ta.is_primary)
        )

    assignees = related.assignees.get(task.id, []) if related else assignees
    predecessors = related.predecessors.get(task.id, []) if related else [
        PredecessorOut(task_id=d.predecessor_id, link_type=d.link_type)
        for d in db.query(TaskDependency).filter(TaskDependency.task_id == task.id).all()
    ]

    checklist = related.checklists.get(task.id, []) if related else [
        ChecklistItemOut.model_validate(c)
        for c in db.query(ChecklistItem)
        .filter(ChecklistItem.task_id == task.id)
        .order_by(ChecklistItem.position)
        .all()
    ]

    timer = related.timers.get(task.id) if related else get_timer(db, task.id)
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
        blocking_incidents=related.incidents.get(task.id, []) if related else [{'id':i.id, 'number':i.number, 'title':i.title, 'level':i.level, 'status':i.status}
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
