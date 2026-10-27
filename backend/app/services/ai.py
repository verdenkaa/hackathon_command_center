"""ИИ-советник: снимок проекта, rate-limit, mock-провайдер (реальный — после ключей)."""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.api.errors import api_error
from app.db.models import (
    AiRecommendation,
    AiSettings,
    BoardColumn,
    Incident,
    Project,
    Task,
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

# Простейший ограничитель частоты (in-memory).
_last_run: dict[int, datetime] = {}


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


def rate_limited(project_id: int, interval_minutes: int) -> bool:
    last = _last_run.get(project_id)
    return last is not None and (utcnow() - last) < timedelta(minutes=interval_minutes)


def mark_run(project_id: int) -> None:
    _last_run[project_id] = utcnow()


def build_snapshot(db: Session, project_id: int) -> dict:
    project = db.get(Project, project_id)
    tasks = db.query(Task).filter(Task.project_id == project_id).all()
    done_ids = {
        c.id
        for c in db.query(BoardColumn)
        .filter(BoardColumn.project_id == project_id, BoardColumn.key.in_(["done", "realised"]))
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
        "project": project.name,
        "deadline": project.deadline_msk.isoformat() if project.deadline_msk else None,
        "tasks_total": len(tasks),
        "tasks_done": sum(1 for t in tasks if t.column_id in done_ids),
        "overdue": overdue,
        "active_incidents": [{"title": i.title, "level": i.level, "status": i.status} for i in active_incidents],
    }


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


def run_recommendation(db: Session, project_id: int, trigger: str) -> AiRecommendation:
    settings = get_settings(db, project_id)
    if not settings.enabled:
        raise api_error(409, "AI_DISABLED", "ИИ-советник выключен")
    if trigger != "manual" and rate_limited(project_id, settings.interval_minutes):
        raise api_error(429, "RATE_LIMITED", "Частота запусков ИИ ограничена")
    mark_run(project_id)

    snapshot = build_snapshot(db, project_id)
    # Mock-провайдер (реальные Gemini/DeepSeek подключатся после передачи ключей).
    summary, content = _mock_recommendation(snapshot)
    rec = AiRecommendation(
        project_id=project_id,
        provider=settings.priority_provider,
        trigger=trigger,
        summary=summary,
        content=content,
    )
    db.add(rec)
    db.flush()
    return rec
