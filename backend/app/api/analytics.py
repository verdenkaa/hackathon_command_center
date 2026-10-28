"""Аналитика проекта."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.deps import get_current_user, get_db
from app.operational_schemas import OperationalAnalytics as AnalyticsOut
from app.services.analytics import analytics

router = APIRouter(tags=["analytics"])


@router.get("/projects/{project_id}/analytics", response_model=AnalyticsOut)
def get_analytics(project_id: int, db: Session = Depends(get_db), _u=Depends(get_current_user)) -> AnalyticsOut:
    return AnalyticsOut.model_validate(analytics(db, project_id))
