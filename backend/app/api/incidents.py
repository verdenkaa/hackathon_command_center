"""Инциденты: список, создание, эскалация, закрытие, журнал."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.errors import api_error
from app.db.models import Incident, Role, User
from app.deps import project_roles, project_member_ids, ensure_project_active, get_current_user, get_db
from app.schemas import CommentIncident, ConfirmRed, IncidentCreate, IncidentOut, ResolveIncident
from app.services import incidents as incidents_svc
from app.services import notifications as notify_svc
from app.services.ai import maybe_recommend

router = APIRouter(tags=["incidents"])


def _get_incident(db: Session, incident_id: int) -> Incident:
    incident = db.get(Incident, incident_id)
    if incident is None:
        raise api_error(404, "NOT_FOUND", "Инцидент не найден")
    return incident


def _roles(db: Session, user: User, project_id: int) -> set[Role]:
    return project_roles(db, user.id, project_id)


def _is_captain(db: Session, user: User, project_id: int) -> bool:
    return bool(_roles(db, user, project_id) & {Role.captain, Role.admin})


@router.get("/projects/{project_id}/incidents", response_model=list[IncidentOut])
def list_incidents(
    project_id: int,
    db: Session = Depends(get_db),
    _u: User = Depends(get_current_user),
    status: str | None = Query(None),
    level: str | None = Query(None),
) -> list[IncidentOut]:
    q = db.query(Incident).filter(Incident.project_id == project_id)
    if status:
        q = q.filter(Incident.status == status)
    if level:
        q = q.filter(Incident.level == level)
    rows = q.order_by(Incident.created_at.desc()).all()
    return [incidents_svc.serialize_incident(db, i) for i in rows]


@router.post("/projects/{project_id}/incidents", response_model=IncidentOut)
def create_incident(
    project_id: int,
    body: IncidentCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> IncidentOut:
    ensure_project_active(db, project_id)
    members = project_member_ids(db, project_id)
    if body.owner_id is not None and body.owner_id not in members:
        raise api_error(422, "VALIDATION_ERROR", "Ответственный не участник проекта")
    from app.db.models import Task, Module
    for target in body.targets:
        if target.target_type == 'user':
            valid = target.target_id in members
        else:
            model = {'task': Task, 'module': Module}.get(target.target_type)
            entity = db.get(model, target.target_id) if model else None
            valid = entity is not None and entity.project_id == project_id
        if not valid:
            raise api_error(422, "VALIDATION_ERROR", "Цель не принадлежит проекту")
    if body.level not in ("yellow", "red"):
        raise api_error(422, "VALIDATION_ERROR", "Уровень должен быть yellow или red")
    for t in body.targets:
        if t.target_type not in ("task", "module", "user"):
            raise api_error(422, "VALIDATION_ERROR", "Неверный тип цели инцидента")

    incident = incidents_svc.create_incident(
        db,
        project_id=project_id,
        author_id=user.id,
        level=body.level,
        title=body.title,
        description=body.description,
        impact=body.impact,
        urgency=body.urgency,
        owner_id=body.owner_id,
        targets=body.targets,
    )

    payload = {"incident_id": incident.id, "title": incident.title, "level": incident.level}
    if body.level == "red":
        notify_svc.notify_users(
            db, project_id=project_id, user_ids=notify_svc.captains(db, project_id), ntype="incident_red_created",
            payload=payload, telegram_text=f"🔴 Запрос на эскалацию: {incident.title}",
        )
    else:
        recipients = {body.owner_id, *notify_svc.captains(db, project_id)} - {None}
        notify_svc.notify_users(
            db, project_id=project_id, user_ids=list(recipients), ntype="incident_yellow_created",
            payload=payload, telegram_text=f"🟡 Блокер: {incident.title}",
        )
    if body.level == 'yellow':
        maybe_recommend(db, project_id, 'blocker_created')
    db.commit()
    db.refresh(incident)
    return incidents_svc.serialize_incident(db, incident)


@router.get("/incidents/{incident_id}", response_model=IncidentOut)
def get_incident(incident_id: int, db: Session = Depends(get_db), _u: User = Depends(get_current_user)) -> IncidentOut:
    return incidents_svc.serialize_incident(db, _get_incident(db, incident_id))


@router.post("/incidents/{incident_id}/confirm-red", response_model=IncidentOut)
def confirm_red(
    incident_id: int,
    body: ConfirmRed,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> IncidentOut:
    incident = _get_incident(db, incident_id)
    if not _is_captain(db, user, incident.project_id):
        raise api_error(403, "FORBIDDEN", "Подтверждать может только капитан")
    ensure_project_active(db, incident.project_id)
    incidents_svc.confirm_red(db, incident, user.id, body.confirm, body.comment)
    if body.confirm:
        notify_svc.notify_users(
            db, project_id=incident.project_id, user_ids=notify_svc.team(db, incident.project_id), ntype="incident_red_confirmed",
            payload={"incident_id": incident.id, "title": incident.title},
            telegram_text=f"🔴 Глобальная проблема: {incident.title}",
        )
        maybe_recommend(db, incident.project_id, 'red_confirmed')
    db.commit()
    db.refresh(incident)
    return incidents_svc.serialize_incident(db, incident)


@router.post("/incidents/{incident_id}/resolve", response_model=IncidentOut)
def resolve_incident(
    incident_id: int,
    body: ResolveIncident,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> IncidentOut:
    incident = _get_incident(db, incident_id)
    ensure_project_active(db, incident.project_id)
    if incident.level == "red":
        if not _is_captain(db, user, incident.project_id):
            raise api_error(403, "FORBIDDEN", "Красный инцидент закрывает капитан")
    else:
        if incident.owner_id != user.id and not _is_captain(db, user, incident.project_id):
            raise api_error(403, "FORBIDDEN", "Жёлтый инцидент закрывает ответственный или капитан")

    incidents_svc.resolve_incident(db, incident, user.id, body.resolution)
    recipients = {incident.author_id, incident.owner_id} - {None}
    notify_svc.notify_users(
        db, project_id=incident.project_id, user_ids=list(recipients), ntype="incident_resolved",
        payload={"incident_id": incident.id, "title": incident.title, "resolution": body.resolution},
        telegram_text=f"✅ Инцидент закрыт: {incident.title}",
    )
    maybe_recommend(db, incident.project_id, 'blocker_closed')
    db.commit()
    db.refresh(incident)
    return incidents_svc.serialize_incident(db, incident)


@router.post("/incidents/{incident_id}/events", response_model=IncidentOut)
def add_comment(
    incident_id: int,
    body: CommentIncident,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> IncidentOut:
    incident = _get_incident(db, incident_id)
    incidents_svc.add_comment(db, incident, user.id, body.text)
    db.commit()
    db.refresh(incident)
    return incidents_svc.serialize_incident(db, incident)
