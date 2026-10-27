"""Инциденты: список, создание, эскалация, закрытие, журнал."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.errors import api_error
from app.db.models import Incident, Role, User
from app.deps import active_roles, ensure_project_active, get_current_user, get_db
from app.schemas import CommentIncident, ConfirmRed, IncidentCreate, IncidentOut, ResolveIncident
from app.services import incidents as incidents_svc
from app.services import notifications as notify_svc

router = APIRouter(tags=["incidents"])


def _get_incident(db: Session, incident_id: int) -> Incident:
    incident = db.get(Incident, incident_id)
    if incident is None:
        raise api_error(404, "NOT_FOUND", "Инцидент не найден")
    return incident


def _roles(db: Session, user: User) -> set[Role]:
    return {a.role for a in active_roles(db, user.id)}


def _is_captain(db: Session, user: User) -> bool:
    return bool(_roles(db, user) & {Role.captain, Role.admin})


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
            db, project_id=project_id, user_ids=notify_svc.captains(db), ntype="incident_red_created",
            payload=payload, telegram_text=f"🔴 Запрос на эскалацию: {incident.title}",
        )
    else:
        recipients = {body.owner_id, *notify_svc.captains(db)} - {None}
        notify_svc.notify_users(
            db, project_id=project_id, user_ids=list(recipients), ntype="incident_yellow_created",
            payload=payload, telegram_text=f"🟡 Блокер: {incident.title}",
        )
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
    if not _is_captain(db, user):
        raise api_error(403, "FORBIDDEN", "Подтверждать может только капитан")
    incident = _get_incident(db, incident_id)
    ensure_project_active(db, incident.project_id)
    incidents_svc.confirm_red(db, incident, user.id, body.confirm, body.comment)
    if body.confirm:
        notify_svc.notify_users(
            db, project_id=incident.project_id, user_ids=notify_svc.team(db), ntype="incident_red_confirmed",
            payload={"incident_id": incident.id, "title": incident.title},
            telegram_text=f"🔴 Глобальная проблема: {incident.title}",
        )
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
        if not _is_captain(db, user):
            raise api_error(403, "FORBIDDEN", "Красный инцидент закрывает капитан")
    else:
        if incident.owner_id != user.id and not _is_captain(db, user):
            raise api_error(403, "FORBIDDEN", "Жёлтый инцидент закрывает ответственный или капитан")

    incidents_svc.resolve_incident(db, incident, user.id, body.resolution)
    recipients = {incident.author_id, incident.owner_id} - {None}
    notify_svc.notify_users(
        db, project_id=incident.project_id, user_ids=list(recipients), ntype="incident_resolved",
        payload={"incident_id": incident.id, "title": incident.title, "resolution": body.resolution},
        telegram_text=f"✅ Инцидент закрыт: {incident.title}",
    )
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
