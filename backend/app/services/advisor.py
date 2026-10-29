"""Persistent advisor queue, shared quotas and validated, project-scoped results."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, time, timezone
import hashlib
import json
import random
from typing import Any, Callable
from uuid import uuid4
from zoneinfo import ZoneInfo

from pydantic import ValidationError
from sqlalchemy import func, update
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session, sessionmaker

from app.advisor_schemas import AnalysisReply, QuestionReply, Related
from app.api.errors import api_error
from app.db.models import (AdvisorAttempt, AdvisorJob, AdvisorProviderSettings,
                           AiRecommendation, AiSettings, Incident, Project, ProjectState)
from app.services import advisor_vault as vault
from app.services.advisor_prompts import ANALYSIS, QUESTION, VERSION
from app.timeutil import utcnow

PENDING = ('queued', 'waiting', 'running')


class ContextTooLarge(ValueError):
    pass


class ProviderError(Exception):
    def __init__(self, code: str, retry_after: float = 0) -> None:
        self.code, self.retry_after = code, retry_after


@dataclass
class ProviderReply:
    data: dict[str, Any]
    input_tokens: int | None = None
    output_tokens: int | None = None
    thinking_tokens: int | None = None


def config(db: Session) -> AdvisorProviderSettings:
    # In this application SQLite is the supported persistent store.
    db.execute(insert(AdvisorProviderSettings).values(id=1).on_conflict_do_nothing(index_elements=['id']))
    cfg = db.get(AdvisorProviderSettings, 1, populate_existing=True)
    assert cfg is not None
    return cfg


def lock(db: Session) -> AdvisorProviderSettings:
    cfg = config(db)
    db.execute(update(AdvisorProviderSettings).where(AdvisorProviderSettings.id == 1)
               .values(lock_version=AdvisorProviderSettings.lock_version + 1))
    return cfg


def day_window(now: datetime) -> tuple[datetime, datetime]:
    local = now.replace(tzinfo=timezone.utc).astimezone(ZoneInfo('America/Los_Angeles'))
    start = datetime.combine(local.date(), time(), local.tzinfo)
    end = datetime.combine(local.date() + timedelta(days=1), time(), local.tzinfo)
    return (start.astimezone(timezone.utc).replace(tzinfo=None),
            end.astimezone(timezone.utc).replace(tzinfo=None))


def quota(db: Session, now: datetime | None = None) -> dict[str, Any]:
    now = now or utcnow()
    cfg = config(db)
    start, end = day_window(now)
    day_used = db.query(AdvisorAttempt).filter(AdvisorAttempt.created_at >= start,
                                               AdvisorAttempt.created_at < end).count()
    minute = db.query(AdvisorAttempt).filter(AdvisorAttempt.created_at > now - timedelta(minutes=1)).all()
    tokens = sum(max(a.reserved_tokens, a.actual_input or 0) for a in minute)
    return {'day_used': day_used, 'day_limit': cfg.rpd, 'day_remaining': max(0, cfg.rpd-day_used),
            'reset_at': end.isoformat() + 'Z', 'reset_seconds': max(0, int((end-now).total_seconds())),
            'minute_used': len(minute), 'minute_limit': cfg.rpm, 'minute_tokens': tokens,
            'token_limit': cfg.tpm, 'queued': db.query(AdvisorJob).filter(AdvisorJob.state.in_(PENDING)).count(),
            'approximate': True, 'key_saved': vault.is_saved(), 'vault_available': vault.available()}


def reserve(db: Session, job_id: int, tokens: int) -> tuple[int | None, str | None, datetime]:
    cfg = lock(db)
    now = utcnow()
    q = quota(db, now)
    reason = None
    next_at = now + timedelta(seconds=61)
    day_start, day_end = day_window(now)
    provider_daily = db.query(AdvisorAttempt.id).filter(
        AdvisorAttempt.outcome == 'PROVIDER_DAILY_LIMIT', AdvisorAttempt.created_at >= day_start).first()
    provider_wait = db.query(func.max(AdvisorJob.next_attempt_at)).filter(
        AdvisorJob.error_code == 'PROVIDER_RATE_LIMIT', AdvisorJob.next_attempt_at > now).scalar()
    if tokens > min(cfg.max_input_tokens, int(cfg.tpm * .9)):
        reason = 'CONTEXT_TOO_LARGE'
    elif q['day_remaining'] == 0:
        reason = 'DAILY_LIMIT'
        next_at = day_window(now)[1]
    elif provider_daily:
        reason, next_at = 'PROVIDER_DAILY_LIMIT', day_end
    elif provider_wait:
        reason, next_at = 'PROVIDER_RATE_LIMIT', provider_wait
    elif q['minute_used'] >= cfg.rpm or q['minute_tokens'] + tokens > int(cfg.tpm * .9):
        reason = 'MINUTE_LIMIT'
    if reason:
        db.commit()
        return None, reason, next_at
    attempt = AdvisorAttempt(job_id=job_id, reserved_tokens=tokens, created_at=now)
    db.add(attempt)
    db.commit()
    return attempt.id, None, now


def snapshot(db: Session, project_id: int) -> dict[str, Any]:
    from app.services.operational import build_summary
    from app.services.planning import read
    summary = build_summary(db, project_id).model_dump(mode='json')
    plan = read(db, project_id)
    history = db.query(AiRecommendation).filter_by(project_id=project_id, excluded=False).order_by(
        AiRecommendation.id.desc()).limit(31).all()
    history_limited = len(history) > 30
    history = history[:30]
    incident_ids = [i['id'] for i in summary['incidents']]
    incidents = db.query(Incident).filter(Incident.id.in_(incident_ids)).all()
    value: dict[str, Any] = {
        'schema_version': VERSION, 'generated_at': summary['generated_at'],
        'timezone': 'Europe/Moscow', 'project_id': project_id,
        'project_name': db.get(Project, project_id).name, 'summary': summary,
        'planning': {key: plan[key] for key in ('placements', 'edges', 'overlaps', 'forecast') if key in plan},
        'incident_details': [{'id': i.id, 'created_at': i.created_at.isoformat(),
                              'owner_id': i.owner_id, 'description': i.description,
                              'impact': i.impact, 'urgency': i.urgency} for i in incidents],
        'history': [{'id': r.id, 'structured': r.structured, 'summary': r.summary,
                     'content': r.content if not r.structured else None, 'status': r.status,
                     'comment': r.comment, 'decision_at': r.status_at.isoformat() if r.status_at else None,
                     'snapshot_at': r.snapshot_at.isoformat() if r.snapshot_at else None} for r in history],
        'unknown': ['Цель проекта и требования демо не заданы отдельными полями.',
                    'Навыки, смены и фактическая доступность участников неизвестны.'],
        'coverage': {'incomplete': history_limited, 'omissions': ['История ограничена последними 30 советами'] if history_limited else []},
    }
    from fastapi.encoders import jsonable_encoder
    value = jsonable_encoder(value)
    value['version'] = VERSION + ':' + hashlib.sha256(json.dumps(value, sort_keys=True,
                                                               ensure_ascii=False).encode()).hexdigest()[:20]
    return value


def prepare(snap: dict[str, Any], kind: str, question: str, extra: str,
            max_tokens: int) -> tuple[str, str, int]:
    # UTF-8 bytes plus 10% and schema/system overhead is deliberately conservative.
    data = json.loads(json.dumps(snap))
    system = ANALYSIS if kind == 'analysis' else QUESTION
    schema = AnalysisReply if kind == 'analysis' else QuestionReply
    def encode() -> tuple[str, int]:
        content = json.dumps({'snapshot': data, 'question': question,
                              'team_context': extra}, ensure_ascii=False)
        size = len((content + system + json.dumps(schema.model_json_schema())).encode('utf-8'))
        return content, int(size * 1.1) + 128
    content, tokens = encode()
    while tokens > max_tokens and data.get('history'):
        data['history'].pop()
        data['coverage'] = {'incomplete': True, 'omissions': ['Старая история сокращена по лимиту контекста']}
        content, tokens = encode()
    if tokens > max_tokens:
        raise ContextTooLarge('Минимальный контекст не помещается в настроенный лимит')
    return system, content, tokens


def enqueue(db: Session, project_id: int, user_id: int | None, kind: str,
            question: str = '', trigger: str = 'manual') -> AdvisorJob:
    from app.services.ai import get_settings
    lock(db)
    settings = get_settings(db, project_id)
    if not settings.enabled:
        raise api_error(409, 'AI_DISABLED', 'ИИ-советник выключен')
    if not vault.available():
        raise api_error(409, 'VAULT_UNAVAILABLE', 'Защищённое хранилище Windows недоступно')
    if not vault.is_saved():
        raise api_error(409, 'KEY_MISSING', 'Администратор должен сохранить ключ на компьютере сервера')
    # Repeated clicks reuse an outstanding identical request; automatic backlog is bounded.
    existing = db.query(AdvisorJob).filter_by(project_id=project_id, kind=kind, question=question,
                                              trigger=trigger).filter(AdvisorJob.state.in_(PENDING)).first()
    if existing:
        db.commit()
        return existing
    if db.query(AdvisorJob).filter(AdvisorJob.project_id == project_id, AdvisorJob.state.in_(PENDING)).count() >= 20:
        raise api_error(429, 'QUEUE_FULL', 'Очередь проекта заполнена; дождитесь завершения запросов')
    job = AdvisorJob(project_id=project_id, user_id=user_id, kind=kind, question=question,
                     trigger=trigger, priority=0 if kind == 'question' else 2 if trigger == 'automatic' else 1)
    db.add(job)
    db.commit()
    return job


def schedule(db: Session) -> None:
    lock(db)
    now = utcnow()
    rows = db.query(AiSettings).join(Project, Project.id == AiSettings.project_id).filter(
        AiSettings.enabled.is_(True), AiSettings.auto_enabled.is_(True), Project.state == ProjectState.active,
        (Project.start_msk.is_(None) | (Project.start_msk <= now))).all()
    for settings in rows:
        if settings.next_run_at is not None and settings.next_run_at > now:
            continue
        pending = db.query(AdvisorJob).filter_by(project_id=settings.project_id, trigger='automatic').filter(
            AdvisorJob.state.in_(PENDING)).first()
        if not pending:
            db.add(AdvisorJob(project_id=settings.project_id, kind='analysis', trigger='automatic', priority=2))
        settings.next_run_at = now + timedelta(minutes=settings.interval_minutes)
    db.commit()


def _validate_ids(related: Related, snap: dict[str, Any]) -> None:
    summary = snap['summary']
    for field, group in [('task_ids', 'tasks'), ('track_ids', 'tracks'),
                         ('user_ids', 'participants'), ('incident_ids', 'incidents')]:
        if set(getattr(related, field)) - {item['id'] for item in summary[group] if item['id'] is not None}:
            raise ProviderError('INVALID_RESPONSE')


def provider_schema(model: type[AnalysisReply] | type[QuestionReply]) -> dict[str, Any]:
    """Bound arrays/values after decoding: nested bounds can exceed Gemini grammar limits."""
    bounds = {'minItems', 'maxItems', 'minimum', 'maximum', 'minLength', 'maxLength'}

    def simplify(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: simplify(child) for key, child in value.items() if key not in bounds}
        if isinstance(value, list):
            return [simplify(child) for child in value]
        return value

    return simplify(model.model_json_schema())


def gemini(cfg: AdvisorProviderSettings, kind: str, system: str, content: str) -> ProviderReply:
    """Exactly one SDK attempt. Never log raw exceptions, responses, thoughts or credentials."""
    try:
        from google import genai
        from google.genai import types
        schema = AnalysisReply if kind == 'analysis' else QuestionReply
        with genai.Client(api_key=vault.load(), http_options=types.HttpOptions(
                timeout=90000, retry_options=types.HttpRetryOptions(attempts=1))) as client:
            response = client.models.generate_content(model=cfg.model, contents=content,
                config=types.GenerateContentConfig(system_instruction=system,
                    response_mime_type='application/json', response_json_schema=provider_schema(schema),
                    max_output_tokens=8192, thinking_config=types.ThinkingConfig(include_thoughts=False)))
            parsed = schema.model_validate_json(response.text or '')
            usage = response.usage_metadata
            return ProviderReply(parsed.model_dump(),
                getattr(usage, 'prompt_token_count', None), getattr(usage, 'candidates_token_count', None),
                getattr(usage, 'thoughts_token_count', None))
    except (ValidationError, ValueError):
        raise ProviderError('INVALID_RESPONSE') from None
    except vault.VaultUnavailable:
        raise ProviderError('KEY_UNAVAILABLE') from None
    except ImportError:
        raise ProviderError('SDK_MISSING') from None
    except Exception as exc:
        code = getattr(exc, 'code', None)
        wait = 0.0
        response = getattr(exc, 'response', None)
        header = response.headers.get('retry-after') if response is not None else None
        try:
            wait = min(86400, max(0, float(header))) if header else 0
        except (ValueError, TypeError):
            try:
                from email.utils import parsedate_to_datetime
                wait = max(0, min(86400, (parsedate_to_datetime(header) - datetime.now(timezone.utc)).total_seconds()))
            except (ValueError, TypeError, AttributeError):
                pass
        if code == 429:
            # Quota details are inspected, never stored: distinguish daily exhaustion.
            details = str(getattr(exc, 'details', ''))
            reason = 'PROVIDER_DAILY_LIMIT' if 'perday' in details.lower() or 'per_day' in details.lower() else 'PROVIDER_RATE_LIMIT'
        elif code in (401, 403):
            reason = 'PROVIDER_AUTH'
        elif code in (400, 404):
            reason = 'PROVIDER_CONFIG'
        else:
            reason = 'TEMPORARY'
        raise ProviderError(reason, wait) from None


def _save_result(db: Session, job: AdvisorJob, data: dict[str, Any]) -> None:
    coverage = job.snapshot.get('coverage', {})
    warning = 'Неполный контекст: ' + '; '.join(coverage.get('omissions', [])) if coverage.get('incomplete') else None
    if job.kind == 'question':
        answer = QuestionReply.model_validate(data)
        _validate_ids(answer.related, job.snapshot)
        if warning:
            answer.limitations.append(warning)
        job.answer = answer.model_dump()
        return
    result = AnalysisReply.model_validate(data)
    for item in result.recommendations:
        _validate_ids(item.related, job.snapshot)
        _validate_ids(Related(user_ids=item.action_user_ids), job.snapshot)
        from app.deps import project_member_ids
        if set(item.action_user_ids) - set(project_member_ids(db, job.project_id)):
            raise ProviderError('INVALID_RESPONSE')
        if warning:
            item.freshness = 'uncertain'
            item.limitations.append(warning)
    ids = []
    created = 0
    for item in result.recommendations:
        value = item.model_dump()
        digest = hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        prior = db.query(AiRecommendation).filter_by(project_id=job.project_id, fingerprint=digest).first()
        if prior:
            prior.last_seen_at = utcnow()
            ids.append(prior.id)
            continue
        rec = AiRecommendation(project_id=job.project_id, provider='gemini', trigger=job.trigger,
            summary=item.title, content=item.action, structured=value, fingerprint=digest,
            snapshot_at=job.snapshot_at, snapshot_version=job.snapshot_version, last_seen_at=utcnow(),
            request_context={'mode': 'gemini', 'prompt_version': VERSION, 'snapshot_version': job.snapshot_version})
        db.add(rec)
        db.flush()
        created += 1
        ids.append(rec.id)
        from app.services.notifications import notify_users, team
        notify_users(db, project_id=job.project_id, user_ids=team(db, job.project_id),
                     ntype='ai_recommendation', payload={'recommendation_id': rec.id, 'title': rec.summary})
    job.answer = {'result': 'recommendations' if created else 'no_new_recommendations',
                  'captain_intervention': result.captain_intervention, 'recommendation_ids': ids}
    from app.services.telegram import report
    report(db, job, result.model_dump())


def work_once(factory: sessionmaker[Session], provider: Callable[..., ProviderReply] = gemini) -> bool:
    now = utcnow()
    with factory() as db:
        cfg = lock(db)
        # An expired lease has an uncertain provider outcome: keep its attempt charged and fail safely.
        from app.services.telegram import report
        for expired in db.query(AdvisorJob).filter(AdvisorJob.state == 'running', AdvisorJob.lease_until < now):
            expired.state, expired.error_code, expired.finished_at = 'failed', 'INTERRUPTED', now
            report(db, expired)
        job = db.query(AdvisorJob).filter(AdvisorJob.state.in_(('queued', 'waiting')),
            AdvisorJob.next_attempt_at <= now).order_by(AdvisorJob.priority, AdvisorJob.id).first()
        if job is None:
            db.commit()
            return False
        project = db.get(Project, job.project_id)
        settings = db.query(AiSettings).filter_by(project_id=job.project_id).one()
        if job.user_id is not None:
            from app.deps import project_roles
            from app.db.models import User, Role
            user = db.get(User, job.user_id)
            if user is None or not user.active or not project_roles(db, job.user_id, job.project_id).intersection({Role.admin, Role.captain}):
                job.state, job.error_code, job.finished_at = 'cancelled', 'ACCESS_REVOKED', now
                report(db, job)
                db.commit()
                return True
        if (not settings.enabled or project.state == ProjectState.completed or
            (job.trigger == 'automatic' and (not settings.auto_enabled or project.state != ProjectState.active
             or (project.start_msk is not None and project.start_msk > now)))):
            job.state, job.error_code, job.finished_at = 'cancelled', 'AI_DISABLED', now
            report(db, job)
            db.commit()
            return True
        if not vault.is_saved():
            job.state, job.error_code, job.finished_at = 'failed', 'KEY_MISSING', now
            report(db, job)
            db.commit()
            return True
        # The write lock makes all snapshot reads observe one coherent database state.
        snap = snapshot(db, job.project_id)
        job.snapshot = snap
        job.snapshot_at = datetime.fromisoformat(snap['generated_at'])
        job.snapshot_version = snap['version']
        q = quota(db, now)
        try:
            minimum = min(cfg.max_input_tokens, int(cfg.tpm * .9))
            system, content, tokens = prepare(snap, job.kind, job.question, settings.prompt, minimum)
            available = int(cfg.tpm * .9) - q['minute_tokens']
            if tokens > available:
                try:
                    system, content, tokens = prepare(snap, job.kind, job.question, settings.prompt, available)
                except ContextTooLarge:
                    pass  # Reserve will postpone until the current minute clears.
        except ContextTooLarge:
            job.state, job.error_code, job.finished_at = 'failed', 'CONTEXT_TOO_LARGE', now
            report(db, job)
            db.commit()
            return True
        job.state, job.lease_until, job.lease_token = 'running', now + timedelta(minutes=5), uuid4().hex
        job.snapshot = json.loads(content)['snapshot']
        job_id, token, kind = job.id, job.lease_token, job.kind
        db.commit()
        attempt_id, reason, next_at = reserve(db, job_id, tokens)
        if reason:
            job.state = 'failed' if reason == 'CONTEXT_TOO_LARGE' else 'waiting'
            job.error_code, job.next_attempt_at = reason, next_at
            if job.state == 'failed':
                report(db, job)
            db.commit()
            return True
        job.attempts += 1
        db.commit()
        db.expunge(cfg)
    # No open session or write transaction during the network call.
    result = None
    error = None
    try:
        result = provider(cfg, kind, system, content)
    except ProviderError as exc:
        error = exc
    except Exception:
        error = ProviderError('TEMPORARY')
    with factory() as db:
        lock(db)
        job = db.get(AdvisorJob, job_id)
        attempt = db.get(AdvisorAttempt, attempt_id)
        if job is None or job.lease_token != token or job.state != 'running':
            db.commit()
            return True
        if result is not None:
            attempt.actual_input, attempt.actual_output = result.input_tokens, result.output_tokens
            attempt.actual_thinking = result.thinking_tokens
            try:
                _save_result(db, job, result.data)
            except (ValidationError, ProviderError, ValueError, TypeError):
                error = ProviderError('INVALID_RESPONSE')
        if error is not None:
            attempt.outcome = error.code
            job.error_code = error.code
            retry = error.code in ('TEMPORARY', 'PROVIDER_RATE_LIMIT', 'PROVIDER_DAILY_LIMIT')
            if retry and job.attempts < cfg.max_attempts:
                delay = max(error.retry_after, 2 ** job.attempts + random.uniform(0, 2))
                job.state, job.next_attempt_at = 'waiting', utcnow() + timedelta(seconds=delay)
                if error.code == 'PROVIDER_DAILY_LIMIT':
                    job.next_attempt_at = day_window(utcnow())[1]
            else:
                job.state, job.finished_at = 'failed', utcnow()
        else:
            attempt.outcome = 'succeeded'
            job.state, job.finished_at, job.error_code = 'succeeded', utcnow(), None
        job.lease_until = None
        if job.state == 'failed':
            report(db, job)
        db.commit()
    return True
