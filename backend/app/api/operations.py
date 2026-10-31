"""Операции: резервные копии, восстановление, завершение проекта, фоновые задачи."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.errors import api_error
from app.config import settings
from app.db.models import CompletionVote, Project, ProjectState, User
from app.deps import active_roles, get_db, require_captain_or_admin
from app.services import backup as backup_svc
from app.services import jobs, notifications as notify_svc
from app.services.audit import write_audit

router = APIRouter(tags=["operations"])


class RestoreRequest(BaseModel):
    confirm: bool = False


class CompletionVoteRequest(BaseModel):
    action: str = Field(pattern="^(complete|reopen)$")


class BackupOutSchema(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    path: str
    checksum: str
    size_bytes: int
    kind: str
    created_at: datetime


def _is_captain(db: Session, user: User) -> bool:
    from app.db.models import Role

    return bool({a.role for a in active_roles(db, user.id)} & {Role.captain, Role.admin})


@router.post("/admin/backups", response_model=BackupOutSchema)
def create_backup(db: Session = Depends(get_db), _u: User = Depends(require_captain_or_admin)) -> BackupOutSchema:
    if settings.app_managed:
        raise api_error(409, "LOCAL_PANEL_REQUIRED", "Создайте зашифрованную копию в локальной панели управления")
    record = backup_svc.create_backup(db, kind="manual")
    return BackupOutSchema.model_validate(record)


@router.get("/admin/backups", response_model=list[BackupOutSchema])
def list_backups(db: Session = Depends(get_db), _u: User = Depends(require_captain_or_admin)) -> list[BackupOutSchema]:
    return [BackupOutSchema.model_validate(r) for r in backup_svc.list_backups(db)]


@router.post("/admin/backups/{backup_id}/restore")
def restore_backup(
    backup_id: int,
    body: RestoreRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_captain_or_admin),
) -> dict:
    if settings.app_managed:
        raise api_error(409, "LOCAL_PANEL_REQUIRED", "Восстановление доступно только через локальную панель при остановленной платформе")
    if not body.confirm:
        raise api_error(422, "CONFIRM_REQUIRED", "Восстановление требует явного подтверждения")
    record = backup_svc.restore_backup(db, backup_id)
    return {"status": "ok", "backup_id": record.id}


@router.post("/projects/{project_id}/completion-votes")
def completion_vote(
    project_id: int,
    body: CompletionVoteRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_captain_or_admin),
) -> dict:
    project = db.get(Project, project_id)
    if project is None:
        raise api_error(404, "NOT_FOUND", "Проект не найден")

    existing = db.query(CompletionVote).filter(
        CompletionVote.project_id == project_id,
        CompletionVote.user_id == user.id,
        CompletionVote.action == body.action,
    ).first()
    if existing is None:
        db.add(CompletionVote(project_id=project_id, user_id=user.id, action=body.action))
        db.commit()

    captain_ids = set(notify_svc.captains(db, project_id))
    votes = {
        v.user_id
        for v in db.query(CompletionVote).filter(
            CompletionVote.project_id == project_id, CompletionVote.action == body.action
        ).all()
    }
    if captain_ids and captain_ids.issubset(votes):
        new_state = ProjectState.completed if body.action == "complete" else ProjectState.preparation
        project.state = new_state
        db.query(CompletionVote).filter(CompletionVote.project_id == project_id).delete()
        write_audit(db, action=f"project.{body.action}d", actor_id=user.id, project_id=project_id,
                    entity_type="project", entity_id=project_id, data={"state": new_state.value})
        db.commit()
        db.refresh(project)

    return {"state": project.state, "votes": len(votes), "required": len(captain_ids)}


@router.post("/admin/jobs/run")
def run_jobs(db: Session = Depends(get_db), _u: User = Depends(require_captain_or_admin)) -> dict:
    return jobs.run_all_jobs(db)
