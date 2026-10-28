"""Дашборд проекта: KPI, прогресс, план/факт, риски."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.errors import api_error
from app.db.models import BoardColumn, Project, Task, TaskAssignee, TaskTimer, User
from app.deps import get_db, require_member
from app.schemas import DashboardOut, ProjectOut
from app.services import timers as timer_svc
from app.timeutil import utcnow

router = APIRouter(tags=["dashboard"])


def _column_id(db: Session, project_id: int, key: str) -> int | None:
    col = db.query(BoardColumn).filter(BoardColumn.project_id == project_id, BoardColumn.key == key).first()
    return col.id if col else None


@router.get("/projects/{project_id}/dashboard", response_model=DashboardOut)
def dashboard(project_id: int, db: Session = Depends(get_db), _u=Depends(require_member)) -> DashboardOut:
    project = db.get(Project, project_id)
    if project is None:
        raise api_error(404, "NOT_FOUND", "Проект не найден")

    from app.services.analytics import kpi, risks
    return DashboardOut(project=ProjectOut.model_validate(project),
                        risks=[r for r in risks(db, project_id) if r['type'] == 'overdue'],
                        **kpi(db, project_id))
