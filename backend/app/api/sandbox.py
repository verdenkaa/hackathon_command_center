"""Административная песочница: сценарии и журнал."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.models import SandboxRun, User, TelegramDelivery
from datetime import datetime
from app.deps import get_db, require_admin
from app.services import sandbox as sandbox_svc
from app.services.sandbox_checks import CHECKS, CheckResult, run_checks
from app.services.sandbox_workspace import workspace_summary, reset_workspace
from app.api.errors import api_error
from threading import Lock
from time import perf_counter

router = APIRouter(prefix="/admin/sandbox", tags=["sandbox"], dependencies=[Depends(require_admin)])
_operation_lock = Lock()


class SandboxRunRequest(BaseModel):
    scenario: str = Field(min_length=1)


class SandboxRunOut(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    scenario: str
    status: str
    logs: list[str]
    run_by: int | None
    created_at: datetime
    checks: list[CheckResult]
    duration_ms: int


class SandboxTeamMember(BaseModel):
    user_id: int
    login: str
    display_name: str
    role: str
    active: bool


class WorkspaceOut(BaseModel):
    project_id: int | None
    project_name: str | None
    state: str | None
    counts: dict[str, int]
    team: list[SandboxTeamMember]


class ResetRequest(BaseModel):
    project_id: int = Field(gt=0)
    confirm: bool = False


class ResetOut(BaseModel):
    status: str
    archive_path: str
    workspace: WorkspaceOut


@router.get('/workspace', response_model=WorkspaceOut)
def workspace(db: Session = Depends(get_db)) -> WorkspaceOut:
    return WorkspaceOut.model_validate(workspace_summary(db))


@router.get('/checks')
def check_catalog() -> dict[str, str]:
    return CHECKS


@router.post('/reset', response_model=ResetOut)
def reset(body: ResetRequest, db: Session = Depends(get_db), user: User = Depends(require_admin)) -> ResetOut:
    if not body.confirm:
        raise api_error(422, 'CONFIRM_REQUIRED', 'Подтвердите очистку тестового проекта')
    if not _operation_lock.acquire(blocking=False):
        raise api_error(409, 'SANDBOX_BUSY', 'Дождитесь завершения проверки или сценария')
    try:
        archive = reset_workspace(db, body.project_id, user.id)
        return ResetOut(status='ok', archive_path=str(archive), workspace=WorkspaceOut.model_validate(workspace_summary(db)))
    finally:
        _operation_lock.release()


class TelegramDeliveryOut(BaseModel):
    model_config = {'from_attributes': True}
    id: int
    project_id: int | None
    event_type: str
    text: str
    mentions: list[str]
    mode: str
    created_at: datetime


@router.get('/telegram', response_model=list[TelegramDeliveryOut])
def telegram_deliveries(db: Session = Depends(get_db), project_id: int | None = None,
                       limit: int = Query(100, ge=1, le=500)) -> list[TelegramDeliveryOut]:
    query = db.query(TelegramDelivery)
    if project_id is not None:
        query = query.filter(TelegramDelivery.project_id == project_id)
    return [TelegramDeliveryOut.model_validate(row) for row in
            query.order_by(TelegramDelivery.created_at.desc(), TelegramDelivery.id.desc()).limit(limit).all()]


@router.get("/scenarios")
def list_scenarios() -> dict[str, str]:
    return sandbox_svc.SCENARIOS


@router.post("/run", response_model=SandboxRunOut)
def run_scenario(
    body: SandboxRunRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
) -> SandboxRunOut:
    group = body.scenario.removeprefix('check:') if body.scenario.startswith('check:') else None
    if body.scenario not in sandbox_svc.SCENARIOS and body.scenario != 'full_check' and group not in CHECKS:
        raise api_error(422, 'UNKNOWN_SCENARIO', 'Неизвестный сценарий песочницы')
    if not _operation_lock.acquire(blocking=False):
        raise api_error(409, 'SANDBOX_BUSY', 'Дождитесь завершения проверки или сценария')
    started = perf_counter()
    checks: list[CheckResult] = []
    try:
        try:
            if body.scenario == 'full_check' or group is not None or body.scenario == 'integration_failure':
                checks = run_checks('ai' if body.scenario == 'integration_failure' else group)
                ok = all(c.status == 'passed' for c in checks)
                logs = ['Изолированная временная БД. Рабочие проекты, аккаунты и файлы не изменялись.']
            else:
                ok, logs = sandbox_svc.run_scenario(db, body.scenario, user.id)
        except Exception as exc:  # noqa: BLE001 — ошибка видна в журнале песочницы
            db.rollback()
            ok, logs = False, [f"Ошибка сценария: {type(exc).__name__}: {exc}"]
        run = sandbox_svc.record_run(db, body.scenario, "ok" if ok else "error", logs, user.id,
            checks=[c.model_dump() for c in checks], duration_ms=max(1,int((perf_counter()-started)*1000)))
        return SandboxRunOut.model_validate(run)
    finally:
        _operation_lock.release()


@router.get("/runs", response_model=list[SandboxRunOut])
def list_runs(db: Session = Depends(get_db)) -> list[SandboxRunOut]:
    rows = db.query(SandboxRun).order_by(SandboxRun.created_at.desc()).limit(100).all()
    return [SandboxRunOut.model_validate(r) for r in rows]
