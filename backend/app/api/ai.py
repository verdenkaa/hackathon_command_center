"""ИИ-советник: настройки, рекомендации, ручной запуск."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.errors import api_error
from app.db.models import AiRecommendation, AiSettings, User, AdvisorJob
from app.deps import get_current_user, get_db, require_captain_or_admin, require_admin
from app.advisor_schemas import AdvisorRequest, Decision, JobOut, ProviderPatch
from app.services import advisor
from app.schemas import AiRecommendationOut, AiRunRequest, AiSettingsOut, AiSettingsPatch
from app.services import ai as ai_svc

router = APIRouter(tags=["ai"])


def recommendation_out(db: Session, rec: AiRecommendation) -> AiRecommendationOut:
    author = db.get(User, rec.status_by) if rec.status_by else None
    return AiRecommendationOut.model_validate(rec).model_copy(update={'status_by_name': author.display_name if author else None})


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
    if 'auto_enabled' in updates or 'interval_minutes' in updates:
        from app.timeutil import utcnow
        from datetime import timedelta
        settings.next_run_at = utcnow() + timedelta(minutes=settings.interval_minutes) if settings.auto_enabled else None
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
    return [recommendation_out(db, r) for r in rows]


@router.post("/projects/{project_id}/ai/run", response_model=JobOut, status_code=202)
def run_recommendation(
    project_id: int,
    body: AiRunRequest,
    db: Session = Depends(get_db),
    _u: User = Depends(require_captain_or_admin),
) -> JobOut:
    if body.trigger != 'manual':
        raise api_error(422, 'VALIDATION_ERROR', 'Автоматические запуски доступны только серверному таймеру')
    request = AdvisorRequest(kind='question' if body.question.strip() else 'analysis', question=body.question)
    return JobOut.model_validate(advisor.enqueue(db, project_id, _u.id, request.kind, request.question))


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
    return recommendation_out(db, rec)


@router.patch('/projects/{project_id}/ai/recommendations/{rec_id}', response_model=AiRecommendationOut)
def decision(project_id: int, rec_id: int, body: Decision, db: Session = Depends(get_db),
             user: User = Depends(require_captain_or_admin)) -> AiRecommendationOut:
    from app.timeutil import utcnow
    rec = db.get(AiRecommendation, rec_id)
    if rec is None or rec.project_id != project_id:
        raise api_error(404, 'NOT_FOUND', 'Рекомендация не найдена')
    rec.status, rec.comment, rec.status_by, rec.status_at = body.status, body.comment, user.id, utcnow()
    db.commit()
    return recommendation_out(db, rec)


@router.post('/projects/{project_id}/ai/requests', response_model=JobOut, status_code=202)
def enqueue(project_id: int, body: AdvisorRequest, db: Session = Depends(get_db),
            user: User = Depends(require_captain_or_admin)) -> JobOut:
    return JobOut.model_validate(advisor.enqueue(db, project_id, user.id, body.kind, body.question))


@router.get('/projects/{project_id}/ai/requests', response_model=list[JobOut])
def requests(project_id: int, db: Session = Depends(get_db),
             _user: User = Depends(get_current_user)) -> list[JobOut]:
    return [JobOut.model_validate(j) for j in db.query(AdvisorJob).filter_by(project_id=project_id)
            .order_by(AdvisorJob.id.desc()).limit(30).all()]


@router.get('/projects/{project_id}/ai/requests/{job_id}', response_model=JobOut)
def request_status(project_id: int, job_id: int, db: Session = Depends(get_db),
                   _user: User = Depends(get_current_user)) -> JobOut:
    job = db.get(AdvisorJob, job_id)
    if job is None or job.project_id != project_id:
        raise api_error(404, 'NOT_FOUND', 'Запрос не найден')
    return JobOut.model_validate(job)


@router.get('/projects/{project_id}/ai/quota')
def quota(project_id: int, db: Session = Depends(get_db), _user: User = Depends(get_current_user)) -> dict:
    value = advisor.quota(db)
    db.commit()
    return value


@router.get('/ai/provider')
def provider_settings(db: Session = Depends(get_db), _user: User = Depends(require_admin)) -> dict:
    cfg = advisor.config(db)
    value = {key: getattr(cfg, key) for key in ProviderPatch.model_fields}
    value.update(key_saved=advisor.vault.is_saved(), vault_available=advisor.vault.available())
    db.commit()
    return value


@router.patch('/ai/provider')
def patch_provider(body: ProviderPatch, db: Session = Depends(get_db),
                   _user: User = Depends(require_admin)) -> dict:
    cfg = advisor.lock(db)
    for key, value in body.model_dump(exclude_none=True).items():
        setattr(cfg, key, value)
    db.commit()
    return provider_settings(db, _user)


@router.delete('/ai/provider/key')
def delete_key(_user: User = Depends(require_admin)) -> dict:
    try:
        advisor.vault.delete()
    except (advisor.vault.VaultUnavailable, OSError):
        raise api_error(409, 'VAULT_UNAVAILABLE', 'Хранилище Windows недоступно') from None
    return {'key_saved': False}
