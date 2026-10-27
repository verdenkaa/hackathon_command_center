"""ИИ-советник: настройки, рекомендации, ручной запуск."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.errors import api_error
from app.db.models import AiRecommendation, AiSettings, User
from app.deps import get_current_user, get_db, require_captain_or_admin
from app.schemas import AiRecommendationOut, AiRunRequest, AiSettingsOut, AiSettingsPatch
from app.services import ai as ai_svc

router = APIRouter(tags=["ai"])


@router.get('/projects/{project_id}/ai/preview')
@router.post('/projects/{project_id}/ai/preview')
def preview(project_id: int, body: AiRunRequest | None = None, db: Session = Depends(get_db),
            _u: User = Depends(get_current_user)) -> dict:
    request = body or AiRunRequest()
    return ai_svc.preview_request(db, project_id, request.trigger, request.question)


@router.get("/projects/{project_id}/ai/settings", response_model=AiSettingsOut)
def get_settings(project_id: int, db: Session = Depends(get_db), _u=Depends(get_current_user)) -> AiSettingsOut:
    return AiSettingsOut.model_validate(ai_svc.get_settings(db, project_id))


@router.patch("/projects/{project_id}/ai/settings", response_model=AiSettingsOut)
def patch_settings(
    project_id: int,
    body: AiSettingsPatch,
    db: Session = Depends(get_db),
    _u: User = Depends(require_captain_or_admin),
) -> AiSettingsOut:
    settings = ai_svc.get_settings(db, project_id)
    updates = body.model_dump(exclude_unset=True, exclude_none=True)
    if 'triggers' in updates and set(updates['triggers']) - set(ai_svc.DEFAULT_TRIGGERS):
        raise api_error(422, 'VALIDATION_ERROR', 'Неизвестный триггер ИИ')
    for field, value in updates.items():
        setattr(settings, field, value)
    db.commit()
    db.refresh(settings)
    return AiSettingsOut.model_validate(settings)


@router.get("/projects/{project_id}/ai/recommendations", response_model=list[AiRecommendationOut])
def list_recommendations(
    project_id: int,
    db: Session = Depends(get_db),
    _u=Depends(get_current_user),
    limit: int = Query(50, ge=1, le=200),
) -> list[AiRecommendationOut]:
    rows = (
        db.query(AiRecommendation)
        .filter(AiRecommendation.project_id == project_id)
        .order_by(AiRecommendation.created_at.desc())
        .limit(limit)
        .all()
    )
    return [AiRecommendationOut.model_validate(r) for r in rows]


@router.post("/projects/{project_id}/ai/run", response_model=AiRecommendationOut)
def run_recommendation(
    project_id: int,
    body: AiRunRequest,
    db: Session = Depends(get_db),
    _u=Depends(get_current_user),
) -> AiRecommendationOut:
    rec = ai_svc.run_recommendation(db, project_id, body.trigger, body.question)
    db.commit()
    db.refresh(rec)
    return AiRecommendationOut.model_validate(rec)


@router.post("/projects/{project_id}/ai/recommendations/{rec_id}/exclude", response_model=AiRecommendationOut)
def toggle_exclude(
    project_id: int,
    rec_id: int,
    db: Session = Depends(get_db),
    _u: User = Depends(require_captain_or_admin),
) -> AiRecommendationOut:
    rec = db.get(AiRecommendation, rec_id)
    if rec is None or rec.project_id != project_id:
        raise api_error(404, "NOT_FOUND", "Рекомендация не найдена")
    rec.excluded = not rec.excluded
    db.commit()
    db.refresh(rec)
    return AiRecommendationOut.model_validate(rec)
