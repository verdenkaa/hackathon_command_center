"""Административная песочница: сценарии и журнал."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.models import SandboxRun, User
from app.deps import get_db, require_admin
from app.services import sandbox as sandbox_svc

router = APIRouter(prefix="/admin/sandbox", tags=["sandbox"], dependencies=[Depends(require_admin)])


class SandboxRunRequest(BaseModel):
    scenario: str = Field(min_length=1)


class SandboxRunOut(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    scenario: str
    status: str
    logs: list[str]
    run_by: int | None
    created_at: object


@router.get("/scenarios")
def list_scenarios() -> dict[str, str]:
    return sandbox_svc.SCENARIOS


@router.post("/run", response_model=SandboxRunOut)
def run_scenario(
    body: SandboxRunRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
) -> SandboxRunOut:
    try:
        ok, logs = sandbox_svc.run_scenario(db, body.scenario, user.id)
    except Exception as exc:  # noqa: BLE001 — ошибка видна в журнале песочницы
        db.rollback()
        ok, logs = False, [f"Ошибка сценария: {type(exc).__name__}: {exc}"]
    run = sandbox_svc.record_run(db, body.scenario, "ok" if ok else "error", logs, user.id)
    return SandboxRunOut.model_validate(run)


@router.get("/runs", response_model=list[SandboxRunOut])
def list_runs(db: Session = Depends(get_db)) -> list[SandboxRunOut]:
    rows = db.query(SandboxRun).order_by(SandboxRun.created_at.desc()).limit(100).all()
    return [SandboxRunOut.model_validate(r) for r in rows]
