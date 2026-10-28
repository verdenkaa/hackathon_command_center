"""ИИ-советник: снимок проекта, rate-limit, mock-провайдер (реальный — после ключей)."""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy.orm import Session

from app.api.errors import api_error
from app.db.models import (
    AiRecommendation,
    AiSettings,
    BoardColumn,
    Incident,
    Project,
    Task,
    TaskAssignee,
)
from app.timeutil import utcnow

DEFAULT_PROMPT = (
    "Ты — советник команды хакатона. На основе снимка проекта предложи одно "
    "конкретное действие с причиной и риском. Не меняй данные сам."
)

DEFAULT_TRIGGERS = {
    "red_confirmed": True,
    "blocker_created": True,
    "blocker_closed": True,
    "overdue": True,
    "deadline_6h": True,
}

def get_settings(db: Session, project_id: int) -> AiSettings:
    settings = db.query(AiSettings).filter(AiSettings.project_id == project_id).first()
    if settings is None:
        settings = AiSettings(
            project_id=project_id,
            enabled=False,
            priority_provider="gemini",
            prompt=DEFAULT_PROMPT,
            interval_minutes=30,
            triggers=DEFAULT_TRIGGERS,
        )
        db.add(settings)
        db.flush()
    return settings


def build_snapshot(db: Session, project_id: int) -> dict:
    from app.services.operational import build_summary
    project = db.get(Project, project_id)
    if project is None:
        raise api_error(404, 'NOT_FOUND', 'Проект не найден')
    columns = {c.id: c.key for c in db.query(BoardColumn).filter(BoardColumn.project_id == project_id).all()}
    trash_ids = {c.id for c in db.query(BoardColumn).filter_by(project_id=project_id, semantic='trash').all()}
    tasks = [t for t in db.query(Task).filter(Task.project_id == project_id).order_by(Task.id).all()
             if t.column_id not in trash_ids]
    done_ids = {
        c.id
        for c in db.query(BoardColumn)
        .filter(BoardColumn.project_id == project_id, BoardColumn.semantic == 'done')
        .all()
    }
    now = utcnow()
    overdue = [
        t.title
        for t in tasks
        if t.column_id not in done_ids and t.deadline is not None and t.deadline < now
    ]
    active_incidents = (
        db.query(Incident)
        .filter(Incident.project_id == project_id, Incident.status != "resolved")
        .all()
    )
    return {
        'analytics_summary':build_summary(db, project_id).model_dump(mode='json'),
        "project": project.name,
        "deadline": project.deadline_msk.isoformat() if project.deadline_msk else None,
        "tasks_total": len(tasks),
        "tasks_done": sum(1 for t in tasks if t.column_id in done_ids),
        "overdue": overdue,
        "active_incidents": [{"title": i.title, "level": i.level, "status": i.status} for i in active_incidents],
        'tasks': [{'id': t.id, 'title': t.title, 'description': t.description,
                   'column': columns.get(t.column_id), 'priority': t.priority, 'tags': t.tags,
                   'estimate_seconds': t.estimate_seconds,
                   'deadline': t.deadline.isoformat() if t.deadline else None,
                   'assignee_ids': [a.user_id for a in db.query(TaskAssignee).filter(TaskAssignee.task_id == t.id).all()]}
                  for t in tasks],
        'previous_recommendations': [{'summary': r.summary, 'content': r.content}
            for r in db.query(AiRecommendation).filter(AiRecommendation.project_id == project_id,
                AiRecommendation.excluded.is_(False)).order_by(AiRecommendation.id.desc()).limit(5).all()],
    }


def preview_request(db: Session, project_id: int, trigger: str = 'manual', question: str = '') -> dict:
    settings = get_settings(db, project_id)
    return {'mode': 'mock', 'provider': settings.priority_provider, 'prompt': settings.prompt,
            'trigger': trigger, 'question': question, 'snapshot': build_snapshot(db, project_id)}


def _mock_recommendation(snapshot: dict) -> tuple[str, str]:
    """Mock-провайдер: формирует рекомендацию по снимку без внешнего API."""
    if snapshot["active_incidents"]:
        summary = "Есть активные блокеры — разберите их до наращивания работ."
        content = (
            f"Причина: {len(snapshot['active_incidents'])} активных инцидентов. "
            "Риск: работа команды замедляется. Действие: капитану закрыть или эскалировать блокеры."
        )
    elif snapshot["overdue"]:
        summary = f"Просрочено задач: {len(snapshot['overdue'])}."
        content = (
            f"Причина: просрочены {', '.join(snapshot['overdue'][:3])}. "
            "Риск: срыв дедлайна. Действие: перераспределите ресурсы или пересмотрите дедлайны."
        )
    else:
        summary = "Команда идёт по плану, явных рисков нет."
        content = "Причина: нет просрочек и активных блокеров. Действие: продолжать по текущему плану."
    return summary, content


def run_recommendation(db: Session, project_id: int, trigger: str, question: str = '') -> AiRecommendation:
    settings = get_settings(db, project_id)
    if not settings.enabled:
        raise api_error(409, "AI_DISABLED", "ИИ-советник выключен")
    if trigger != 'manual':
        if not settings.triggers.get(trigger, False):
            raise api_error(409, 'TRIGGER_DISABLED', 'Триггер ИИ выключен')
        last = db.query(AiRecommendation).filter(AiRecommendation.project_id == project_id).order_by(AiRecommendation.created_at.desc()).first()
        if last is not None and utcnow() - last.created_at < timedelta(minutes=settings.interval_minutes):
            raise api_error(429, "RATE_LIMITED", "Частота запусков ИИ ограничена")

    context = preview_request(db, project_id, trigger, question)
    snapshot = context['snapshot']
    # Mock-провайдер (реальные Gemini/DeepSeek подключатся после передачи ключей).
    summary, content = _mock_recommendation(snapshot)
    rec = AiRecommendation(
        project_id=project_id,
        provider=settings.priority_provider,
        trigger=trigger,
        summary=summary,
        content=content,
        request_context=context,
    )
    db.add(rec)
    db.flush()
    from app.services.notifications import notify_users, team
    notify_users(db, project_id=project_id, user_ids=team(db, project_id), ntype='ai_recommendation',
                 payload={'recommendation_id': rec.id, 'title': summary},
                 telegram_text=f'🤖 Мок-рекомендация ИИ: {summary}')
    return rec


def maybe_recommend(db: Session, project_id: int, trigger: str) -> bool:
    """Legacy mock events are disabled; the advisor has a persistent interval scheduler."""
    return False
