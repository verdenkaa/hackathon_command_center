"""Внутренние уведомления текущего пользователя."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.errors import api_error
from app.db.models import Notification, User, Task, Incident, BoardColumn
from app.deps import get_current_user, get_db, visible_project_ids
from app.schemas import NotificationOut
from app.timeutil import utcnow

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.post('/{notification_id}/open')
def open_notification(notification_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    notification = db.get(Notification, notification_id)
    if notification is None or notification.user_id != user.id:
        raise api_error(404, 'NOT_FOUND', 'Уведомление не найдено')
    notification.read_at = notification.read_at or utcnow()
    kinds = {'task_assigned':('task', Task), 'task_overdue':('task', Task),
             **{key:('incident', Incident) for key in ('incident_yellow_created','incident_red_created','incident_red_confirmed','incident_resolved')}}
    kind = kinds.get(notification.type)
    target, message = None, 'Для этого уведомления переход не предусмотрен'
    if kind:
        entity_type, model = kind
        raw_id = notification.payload.get(f'{entity_type}_id')
        entity = db.get(model, raw_id) if isinstance(raw_id, int) else None
        if entity is not None and entity.project_id == notification.project_id and entity.project_id in visible_project_ids(db, user.id):
            if entity_type == 'task' and db.get(BoardColumn, entity.column_id).semantic == 'trash':
                message = 'Задача находится в корзине. Восстановите её на доске проекта'
            else:
                target = {'type':entity_type, 'id':entity.id, 'project_id':entity.project_id}
                message = ''
        else:
            message = 'Связанный объект удалён или недоступен'
    db.commit()
    return {'target':target, 'message':message}


@router.get("", response_model=list[NotificationOut])
def list_notifications(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    unread_only: bool = Query(False),
    limit: int = Query(100, ge=1, le=500),
) -> list[NotificationOut]:
    q = db.query(Notification).filter(Notification.user_id == user.id)
    q = q.filter(Notification.project_id.is_(None) | Notification.project_id.in_(visible_project_ids(db, user.id)))
    if unread_only:
        q = q.filter(Notification.read_at.is_(None))
    rows = q.order_by(Notification.created_at.desc()).limit(limit).all()
    return [NotificationOut.model_validate(n) for n in rows]


@router.post("/{notification_id}/read", response_model=NotificationOut)
def mark_read(notification_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> NotificationOut:
    notification = db.get(Notification, notification_id)
    if notification is None or notification.user_id != user.id:
        raise api_error(404, "NOT_FOUND", "Уведомление не найдено")
    if notification.read_at is None:
        notification.read_at = utcnow()
        db.commit()
        db.refresh(notification)
    return NotificationOut.model_validate(notification)


@router.post("/read-all")
def mark_all_read(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    db.query(Notification).filter(
        Notification.user_id == user.id, Notification.read_at.is_(None)
    ).update({Notification.read_at: utcnow()})
    db.commit()
    return {"status": "ok"}


@router.delete("/{notification_id}")
def delete_notification(notification_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    notification = db.get(Notification, notification_id)
    if notification is None or notification.user_id != user.id:
        raise api_error(404, "NOT_FOUND", "Уведомление не найдено")
    db.delete(notification)
    db.commit()
    return {"status": "ok"}


@router.delete("")
def clear_all(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    db.query(Notification).filter(Notification.user_id == user.id).delete()
    db.commit()
    return {"status": "ok"}
