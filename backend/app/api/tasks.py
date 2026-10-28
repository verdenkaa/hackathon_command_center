"""Задачи: CRUD, перемещение, исполнители, зависимости, чек-лист."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Header
from sqlalchemy.orm import Session

from app.api.errors import api_error
from app.db.models import (
    AuditEntry,
    BoardColumn,
    ChecklistItem,
    Module,
    Task,
    TaskAssignee,
    TaskDependency,
    User,
)
from app.deps import ensure_project_active, get_db, require_member
from app.schemas import (
    AssigneesSet,
    ChecklistCreate,
    ChecklistItemOut,
    ChecklistPatch,
    DependencyCreate,
    TaskCreate,
    TaskMove,
    TaskOut,
    TaskPatch,
)
from app.services.audit import write_audit
from app.services.history import history_text as _history_text
from app.services.board import get_column_by_key
from app.services.notifications import notify_users
from app.services.tasks import serialize_task
from app.services import planning
from app.timeutil import to_naive_utc
from app.cascade_schemas import CascadeOut

router = APIRouter(tags=["tasks"])


@router.get('/tasks/{task_id}/incident-cascade', response_model=CascadeOut)
def incident_cascade(task_id: int, db: Session = Depends(get_db), _u=Depends(require_member)) -> CascadeOut:
    from app.services.cascade import analyse
    task = _get_task(db, task_id)
    if db.get(BoardColumn, task.column_id).semantic == 'trash':
        raise api_error(422, 'TASK_TRASHED', 'Исходная задача находится в корзине')
    return analyse(db, task.project_id, [task_id])


@router.get('/tasks/{task_id}/incident-impact')
def incident_impact(task_id: int, depth: int = Query(1, ge=1, le=100), db: Session = Depends(get_db), _u=Depends(require_member)) -> dict:
    task = _get_task(db, task_id)
    eligible = {t.id for t in db.query(Task).join(BoardColumn, Task.column_id == BoardColumn.id)
                .filter(Task.project_id == task.project_id, BoardColumn.semantic != 'trash').all()}
    if task_id not in eligible:
        raise api_error(422, 'TASK_TRASHED', 'Исходная задача находится в корзине')
    edges: dict[int, set[int]] = {}
    for link in db.query(TaskDependency).filter(TaskDependency.task_id.in_(eligible), TaskDependency.predecessor_id.in_(eligible)).all():
        source, target = (link.task_id, link.predecessor_id) if link.link_type == 'before' else (link.predecessor_id, link.task_id)
        edges.setdefault(source, set()).add(target)
    visited, frontier = {task_id}, {task_id}
    for _ in range(depth):
        frontier = {child for parent in frontier for child in edges.get(parent, set())} - visited
        visited.update(frontier)
        if not frontier:
            break
    users = {a.user_id for a in db.query(TaskAssignee).filter(TaskAssignee.task_id.in_(visited)).all()}
    from app.deps import project_member_ids
    return {'task_ids':sorted(visited), 'user_ids':sorted(users & set(project_member_ids(db, task.project_id)))}


def _get_task(db: Session, task_id: int) -> Task:
    task = db.get(Task, task_id)
    if task is None:
        raise api_error(404, "NOT_FOUND", "Задача не найдена")
    return task


def _check_version(task: Task, version: int) -> None:
    if task.version != version:
        raise api_error(409, "VERSION_CONFLICT", "Задача изменена другим пользователем")


def _validate_module(db: Session, project_id: int, module_id: int | None) -> None:
    if module_id is None:
        return
    module = db.get(Module, module_id)
    if module is None or module.project_id != project_id:
        raise api_error(422, "VALIDATION_ERROR", "Модуль не принадлежит проекту")


@router.get("/projects/{project_id}/tasks", response_model=list[TaskOut])
def list_tasks(
    project_id: int,
    db: Session = Depends(get_db),
    _u=Depends(require_member),
    assignee_id: int | None = Query(None),
    module_id: int | None = Query(None),
    column_key: str | None = Query(None),
    tag: str | None = Query(None),
) -> list[TaskOut]:
    tasks = db.query(Task).filter(Task.project_id == project_id).order_by(Task.id).all()

    if column_key is not None:
        column = db.query(BoardColumn).filter(
            BoardColumn.project_id == project_id, BoardColumn.key == column_key
        ).first()
        if column is None:
            return []
        tasks = [t for t in tasks if t.column_id == column.id]
    if module_id is not None:
        tasks = [t for t in tasks if t.module_id == module_id]
    if assignee_id is not None:
        ids = {
            a.task_id
            for a in db.query(TaskAssignee).filter(TaskAssignee.user_id == assignee_id).all()
        }
        tasks = [t for t in tasks if t.id in ids]
    if tag is not None:
        tasks = [t for t in tasks if tag in (t.tags or [])]

    return [serialize_task(db, t) for t in tasks]


@router.post("/projects/{project_id}/tasks", response_model=TaskOut)
def create_task(
    project_id: int,
    body: TaskCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_member),
) -> TaskOut:
    ensure_project_active(db, project_id)
    plan_change = planning.begin(db, project_id)
    if body.column_key == 'backlog' and not db.query(BoardColumn).filter_by(project_id=project_id, key='backlog').first():
        column = db.query(BoardColumn).filter(BoardColumn.project_id == project_id, BoardColumn.semantic.notin_(['done', 'trash'])).order_by(BoardColumn.position).first()
        column = column or db.query(BoardColumn).filter_by(project_id=project_id).order_by(BoardColumn.position).first()
        if column is None:
            raise api_error(409, 'NO_COLUMNS', 'Сначала создайте колонку проекта')
    else:
        column = get_column_by_key(db, project_id, body.column_key)
    _validate_module(db, project_id, body.module_id)
    if body.parent_id is not None:
        parent = db.get(Task, body.parent_id)
        if parent is None or parent.project_id != project_id:
            raise api_error(422, "VALIDATION_ERROR", "Родительская задача не принадлежит проекту")

    task = Task(
        project_id=project_id,
        column_id=column.id,
        module_id=body.module_id,
        parent_id=body.parent_id,
        title=body.title,
        description=body.description,
        priority=body.priority,
        estimate_seconds=body.estimate_seconds,
        deadline=to_naive_utc(body.deadline) if body.deadline else None,
        tags=body.tags,
        version=1,
    )
    db.add(task)
    db.flush()
    planning.assign_track(db, task)
    planning.finish(db, plan_change)
    write_audit(db, action="task.created", actor_id=user.id, project_id=project_id, entity_type="task", entity_id=task.id,
                data={"title": task.title, 'column_semantic':column.semantic})
    db.commit()
    db.refresh(task)
    return serialize_task(db, task)


@router.get("/tasks/{task_id}", response_model=TaskOut)
def get_task(task_id: int, db: Session = Depends(get_db), _u=Depends(require_member)) -> TaskOut:
    return serialize_task(db, _get_task(db, task_id))


@router.get("/tasks/{task_id}/history")
def task_history(task_id: int, db: Session = Depends(get_db), _u=Depends(require_member)) -> list[dict]:
    task = _get_task(db, task_id)
    rows = (
        db.query(AuditEntry)
        .filter(AuditEntry.entity_type == "task", AuditEntry.entity_id == str(task.id))
        .order_by(AuditEntry.created_at.desc())
        .limit(100)
        .all()
    )
    return [
        {
            "action": r.action,
            "actor_id": r.actor_id,
            "data": r.data,
            "created_at": r.created_at.isoformat(),
            "text": _history_text(db, r),
        }
        for r in rows
    ]


@router.patch("/tasks/{task_id}", response_model=TaskOut)
def patch_task(
    task_id: int,
    body: TaskPatch,
    db: Session = Depends(get_db),
    user: User = Depends(require_member),
    x_planning_confirm: str | None = Header(None),
) -> TaskOut:
    task = _get_task(db, task_id)
    plan_change = planning.begin(db, task.project_id)
    db.refresh(task)
    _check_version(task, body.version)
    updates = body.model_dump(exclude_unset=True, exclude={"version"})
    changes = {field: {'old': str(getattr(task, field)) if field == 'deadline' and getattr(task, field) else getattr(task, field),
                       'new': str(value) if field == 'deadline' and value else value} for field, value in updates.items()}
    if "module_id" in updates:
        _validate_module(db, task.project_id, updates["module_id"])
    if updates.get('parent_id') is not None:
        parent = db.get(Task, updates['parent_id'])
        seen = {task.id}
        while parent is not None:
            if parent.id in seen or parent.project_id != task.project_id or db.get(BoardColumn, parent.column_id).semantic == 'trash':
                raise api_error(422, 'INVALID_PARENT', 'Выберите задачу этого проекта вне корзины, без цикла подзадач')
            seen.add(parent.id)
            parent = db.get(Task, parent.parent_id) if parent.parent_id else None
        if db.get(Task, updates['parent_id']) is None:
            raise api_error(422, 'INVALID_PARENT', 'Родительская задача не найдена')
    if "deadline" in updates and updates["deadline"] is not None:
        updates["deadline"] = to_naive_utc(updates["deadline"])
    for field, value in updates.items():
        setattr(task, field, value)
    task.version += 1
    if 'module_id' in updates or 'estimate_seconds' in updates:
        planning.assign_track(db, task)
    if 'deadline' in updates and task.deadline is not None:
        from app.db.models import TaskPlacement
        from datetime import timedelta
        placement = db.get(TaskPlacement, task.id)
        if placement and placement.lane_id is not None:
            placement.start = task.deadline - timedelta(seconds=task.estimate_seconds or 3600)
    planning.finish(db, plan_change, x_planning_confirm)
    write_audit(db, action="task.updated", actor_id=user.id, project_id=task.project_id, entity_type="task", entity_id=task.id, data={'changes':changes})
    db.commit()
    db.refresh(task)
    return serialize_task(db, task)


@router.post("/tasks/{task_id}/move", response_model=TaskOut)
def move_task(
    task_id: int,
    body: TaskMove,
    db: Session = Depends(get_db),
    user: User = Depends(require_member),
    x_planning_confirm: str | None = Header(None),
) -> TaskOut:
    task = _get_task(db, task_id)
    plan_change = planning.begin(db, task.project_id)
    db.refresh(task)
    ensure_project_active(db, task.project_id)
    _check_version(task, body.version)
    column = get_column_by_key(db, task.project_id, body.column_key)
    if column.semantic in {'active', 'done'} or column.auto_start_timer:
        from app.services.dependencies import require_ready
        require_ready(db, task)
    old = task.column_id
    old_column = db.get(BoardColumn, old)
    task.column_id = column.id
    task.version += 1
    if column.semantic == 'done' and task.actual_completed_at is None:
        task.actual_completed_at = planning.now()
    elif column.semantic not in {'done', 'trash'} and task.actual_completed_at is not None:
        task.actual_completed_at = None
    if column.semantic == 'active' and task.actual_started_at is None:
        task.actual_started_at = planning.now()
    planning.finish(db, plan_change, x_planning_confirm)
    write_audit(db, action="task.moved", actor_id=user.id, project_id=task.project_id, entity_type="task", entity_id=task.id,
                data={"from_column": old, "to_column": column.id, "key": body.column_key, 'from_title':old_column.title, 'to_title':column.title, 'from_semantic':old_column.semantic, 'to_semantic':column.semantic})

    # Правила колонки: авто-старт / авто-остановка таймера.
    from app.services import timers as timers_svc

    timer = timers_svc.get_timer(db, task_id)
    if column.auto_start_timer and (timer is None or timer.state != "running"):
        timers_svc.start_timer(db, task_id, commit=False)
    elif column.auto_stop_timer and timer is not None and timer.state == "running":
        timers_svc.stop_timer(db, task_id, commit=False)

    db.commit()
    db.refresh(task)
    return serialize_task(db, task)


@router.put("/tasks/{task_id}/assignees", response_model=TaskOut)
def set_assignees(
    task_id: int,
    body: AssigneesSet,
    db: Session = Depends(get_db),
    user: User = Depends(require_member),
) -> TaskOut:
    task = _get_task(db, task_id)
    ensure_project_active(db, task.project_id)
    primaries = [a for a in body.assignees if a.is_primary]
    if body.assignees and len(primaries) != 1:
        raise api_error(422, "VALIDATION_ERROR", "Должен быть ровно один основной исполнитель")
    for a in body.assignees:
        from app.deps import project_member_ids
        if a.user_id not in project_member_ids(db, task.project_id):
            raise api_error(422, "VALIDATION_ERROR", f"Пользователь {a.user_id} не участник проекта")

    db.query(TaskAssignee).filter(TaskAssignee.task_id == task_id).delete()
    for a in body.assignees:
        db.add(TaskAssignee(task_id=task_id, user_id=a.user_id, is_primary=a.is_primary))
    task.version += 1
    write_audit(db, action="task.assignees_set", actor_id=user.id, project_id=task.project_id, entity_type="task", entity_id=task.id,
                data={"user_ids": [a.user_id for a in body.assignees]})
    if body.assignees:
        assigned_ids = [a.user_id for a in body.assignees]
        names = [db.get(User, uid).telegram_username for uid in assigned_ids]
        notify_users(
            db,
            project_id=task.project_id,
            user_ids=assigned_ids,
            ntype="task_assigned",
            payload={"task_id": task.id, "title": task.title},
            telegram_text=f"📌 Назначена задача: {task.title}",
            mention_usernames=[n for n in names if n],
        )
    db.commit()
    db.refresh(task)
    return serialize_task(db, task)


@router.post("/tasks/{task_id}/dependencies", response_model=TaskOut)
def add_dependency(
    task_id: int,
    body: DependencyCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_member),
    x_planning_confirm: str | None = Header(None),
) -> TaskOut:
    task = _get_task(db, task_id)
    plan_change = planning.begin(db, task.project_id)
    ensure_project_active(db, task.project_id)
    if body.predecessor_id == task_id:
        raise api_error(422, "VALIDATION_ERROR", "Задача не может зависеть от самой себя")
    if body.link_type not in ("blocked_by", "after", "before"):
        raise api_error(422, "VALIDATION_ERROR", "Неверный тип связи")
    predecessor = db.get(Task, body.predecessor_id)
    if predecessor is None or predecessor.project_id != task.project_id:
        raise api_error(422, "VALIDATION_ERROR", "Предшествующая задача не принадлежит проекту")
    if any(db.get(BoardColumn, t.column_id).semantic == 'trash' for t in (task, predecessor)):
        raise api_error(422, 'TASK_TRASHED', 'Задачи из корзины нельзя добавлять в связи')
    source, target = (task_id, body.predecessor_id) if body.link_type == 'before' else (body.predecessor_id, task_id)
    planning.validate_link(db, task.project_id, source, target)
    exists = db.query(TaskDependency).filter(
        TaskDependency.task_id == task_id, TaskDependency.predecessor_id == body.predecessor_id
    ).first()
    if exists is None:
        db.add(TaskDependency(task_id=task_id, predecessor_id=body.predecessor_id, link_type=body.link_type))
        task.version += 1
        planning.finish(db, plan_change, x_planning_confirm)
        write_audit(db, action="task.dependency_added", actor_id=user.id, project_id=task.project_id, entity_type="task", entity_id=task.id,
                    data={"predecessor_id": body.predecessor_id, "link_type": body.link_type})
        db.commit()
    return serialize_task(db, task)


@router.delete("/tasks/{task_id}/dependencies/{predecessor_id}", response_model=TaskOut)
def remove_dependency(
    task_id: int,
    predecessor_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_member),
    x_planning_confirm: str | None = Header(None),
) -> TaskOut:
    task = _get_task(db, task_id)
    plan_change = planning.begin(db, task.project_id)
    row = db.query(TaskDependency).filter(
        TaskDependency.task_id == task_id, TaskDependency.predecessor_id == predecessor_id
    ).first()
    if row is not None:
        db.delete(row)
        task.version += 1
        planning.finish(db, plan_change, x_planning_confirm)
        write_audit(db, action="task.dependency_removed", actor_id=user.id, project_id=task.project_id, entity_type="task", entity_id=task.id,
                    data={"predecessor_id": predecessor_id})
        db.commit()
    return serialize_task(db, task)


@router.post("/tasks/{task_id}/checklist", response_model=ChecklistItemOut)
def add_checklist_item(
    task_id: int,
    body: ChecklistCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_member),
) -> ChecklistItemOut:
    task = _get_task(db, task_id)
    max_pos = (
        db.query(ChecklistItem).filter(ChecklistItem.task_id == task_id).count()
    )
    item = ChecklistItem(task_id=task_id, text=body.text, position=max_pos)
    db.add(item)
    write_audit(db, action="task.checklist_added", actor_id=user.id, project_id=task.project_id, entity_type="task", entity_id=task.id)
    db.commit()
    db.refresh(item)
    return ChecklistItemOut.model_validate(item)


@router.patch("/checklist/{item_id}", response_model=ChecklistItemOut)
def patch_checklist_item(
    item_id: int,
    body: ChecklistPatch,
    db: Session = Depends(get_db),
    _u=Depends(require_member),
) -> ChecklistItemOut:
    item = db.get(ChecklistItem, item_id)
    if item is None:
        raise api_error(404, "NOT_FOUND", "Элемент чек-листа не найден")
    if body.text is not None:
        item.text = body.text
    if body.done is not None:
        item.done = body.done
    db.commit()
    db.refresh(item)
    return ChecklistItemOut.model_validate(item)


@router.delete("/checklist/{item_id}")
def delete_checklist_item(item_id: int, db: Session = Depends(get_db), _u=Depends(require_member)) -> dict:
    item = db.get(ChecklistItem, item_id)
    if item is None:
        raise api_error(404, "NOT_FOUND", "Элемент чек-листа не найден")
    db.delete(item)
    db.commit()
    return {"status": "ok"}
