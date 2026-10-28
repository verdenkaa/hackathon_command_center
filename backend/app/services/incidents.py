"""Инциденты: создание, эскалация, закрытие, светофор."""
from __future__ import annotations

from sqlalchemy.orm import Session
from sqlalchemy import update

from app.api.errors import api_error
from app.db.models import Incident, IncidentEvent, IncidentTarget, Project
from app.schemas import IncidentEventOut, IncidentOut, IncidentTargetOut
from app.timeutil import utcnow


def create_incident(
    db: Session,
    *,
    project_id: int,
    author_id: int,
    level: str,
    title: str,
    description: str | None,
    impact: str | None,
    urgency: str | None,
    owner_id: int | None,
    targets: list,
    source_task_id: int | None = None,
    cascade_depth: int = 1,
) -> Incident:
    # Atomic write serializes concurrent creators, and survives record deletion.
    number = db.execute(update(Project).where(Project.id == project_id).values(incident_counter=Project.incident_counter + 1).returning(Project.incident_counter)).scalar_one()
    incident = Incident(
        number=number,
        project_id=project_id,
        level=level,
        status="open",
        title=title,
        description=description,
        impact=impact,
        urgency=urgency,
        author_id=author_id,
        owner_id=owner_id if owner_id is not None else author_id,
    )
    db.add(incident)
    db.flush()
    for t in targets:
        db.add(IncidentTarget(incident_id=incident.id, target_type=t.target_type, target_id=t.target_id))
    db.add(
        IncidentEvent(
            incident_id=incident.id,
            actor_id=author_id,
            event_type="created",
            data={"level": level, "title": title, "owner_id": owner_id,
                  "source_task_id":source_task_id, "cascade_depth":cascade_depth},
        )
    )
    db.flush()
    return incident


def confirm_red(db: Session, incident: Incident, actor_id: int, confirm: bool, comment: str | None) -> Incident:
    if incident.level != "red":
        raise api_error(422, "VALIDATION_ERROR", "Подтверждать можно только красный инцидент")
    if incident.status != "open":
        raise api_error(409, "INVALID_STATE", "Инцидент уже обработан")
    if confirm:
        incident.status = "confirmed"
        incident.confirmed_at = utcnow()
        db.add(IncidentEvent(incident_id=incident.id, actor_id=actor_id, event_type="confirmed", data={"comment": comment}))
    else:
        incident.status = "resolved"
        incident.resolution = comment or "Эскалация отклонена"
        incident.resolved_at = utcnow()
        db.add(IncidentEvent(incident_id=incident.id, actor_id=actor_id, event_type="rejected", data={"comment": comment}))
    db.flush()
    return incident


def resolve_incident(db: Session, incident: Incident, actor_id: int, resolution: str) -> Incident:
    if incident.status == "resolved":
        raise api_error(409, "INVALID_STATE", "Инцидент уже закрыт")
    incident.status = "resolved"
    incident.resolution = resolution
    incident.resolved_at = utcnow()
    db.add(
        IncidentEvent(
            incident_id=incident.id,
            actor_id=actor_id,
            event_type="resolved",
            data={"resolution": resolution},
        )
    )
    db.flush()
    return incident


def add_comment(db: Session, incident: Incident, actor_id: int, text: str) -> None:
    db.add(IncidentEvent(incident_id=incident.id, actor_id=actor_id, event_type="comment", data={"text": text}))
    db.flush()


def traffic_status(db: Session, target_type: str, target_id: int, project_id: int | None = None) -> str:
    active = (
        db.query(Incident)
        .join(IncidentTarget, IncidentTarget.incident_id == Incident.id)
        .filter(
            IncidentTarget.target_type == target_type,
            IncidentTarget.target_id == target_id,
            Incident.status != "resolved",
            *([Incident.project_id == project_id] if project_id is not None else []),
        )
        .all()
    )
    if any(i.level == "red" and i.status == "confirmed" for i in active):
        return "red"
    if any(i.level == 'red' and i.status == 'open' for i in active):
        return 'purple'
    if any(i.level == "yellow" for i in active):
        return "yellow"
    return "green"


def serialize_incident(db: Session, incident: Incident) -> IncidentOut:
    from app.services.cascade import analyse
    targets = db.query(IncidentTarget).filter(IncidentTarget.incident_id == incident.id).all()
    events = (
        db.query(IncidentEvent)
        .filter(IncidentEvent.incident_id == incident.id)
        .order_by(IncidentEvent.created_at, IncidentEvent.id)
        .all()
    )
    created = next((e.data for e in events if e.event_type == 'created'), {})
    source_id = created.get('source_task_id')
    seeds = [source_id] if source_id is not None else [t.target_id for t in targets if t.target_type == 'task']
    cascade = analyse(db, incident.project_id, seeds)
    if source_id is None:
        cascade.limitations.insert(0, 'Исходная задача не задана: расчёт от отмеченных задач.')
    return IncidentOut(
        source_task_id=source_id,
        cascade_depth=created.get('cascade_depth', 1),
        cascade=cascade,
        id=incident.id,
        number=incident.number,
        project_id=incident.project_id,
        level=incident.level,
        status=incident.status,
        title=incident.title,
        description=incident.description,
        impact=incident.impact,
        urgency=incident.urgency,
        author_id=incident.author_id,
        owner_id=incident.owner_id,
        resolution=incident.resolution,
        created_at=incident.created_at,
        confirmed_at=incident.confirmed_at,
        resolved_at=incident.resolved_at,
        age_seconds=max(0, int((utcnow() - incident.created_at).total_seconds())),
        targets=[IncidentTargetOut.model_validate(t) for t in targets],
        events=[IncidentEventOut.model_validate(e) for e in events],
    )
