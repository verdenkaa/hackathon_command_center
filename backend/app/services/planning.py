"""Project scoped, transactional scheduling. No timer totals are changed here."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
import json
from typing import Any

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.api.errors import api_error
from app.db.models import (BoardColumn, PlanningBaseline, Module as PlanningLane, PlanningState, Project,
                           Task, TaskAssignee, TaskDependency, TaskPlacement, Incident, IncidentTarget)
from app.services.tasks import serialize_task
from app.services.dependencies import pending_blockers
from app.timeutil import utcnow

now = utcnow


def edges(db: Session, project_id: int, eligible: set[int]) -> list[dict[str, Any]]:
    links = db.query(TaskDependency).join(Task, Task.id == TaskDependency.task_id).filter(Task.project_id == project_id).all()
    result = []
    for link in links:
        if link.task_id not in eligible or link.predecessor_id not in eligible:
            continue
        source, target = (link.task_id, link.predecessor_id) if link.link_type == 'before' else (link.predecessor_id, link.task_id)
        if link.link_type in {'before', 'after', 'blocked_by'}:
            result.append({'source': source, 'target': target, 'task_id': link.task_id,
                           'predecessor_id': link.predecessor_id, 'type': link.link_type})
    return result


def graph(db: Session, project_id: int) -> dict[str, Any]:
    db.flush()
    tasks = {t.id: t for t in db.query(Task).join(BoardColumn, BoardColumn.id == Task.column_id)
             .filter(Task.project_id == project_id, BoardColumn.semantic != 'trash').all()}
    lanes = db.query(PlanningLane).filter_by(project_id=project_id).order_by(PlanningLane.position, PlanningLane.id).all()
    lane_ids = {l.id for l in lanes}
    placements = {p.task_id: p for p in db.query(TaskPlacement).filter(TaskPlacement.task_id.in_(tasks)).all()
                  if p.lane_id in lane_ids and (tasks[p.task_id].estimate_seconds or 0) > 0}
    return {'tasks': tasks, 'lanes': lanes, 'placements': placements, 'edges': edges(db, project_id, set(tasks))}


def assign_track(db: Session, task: Task) -> None:
    """One track and one estimate shared with the board; timers remain factual."""
    p = db.get(TaskPlacement, task.id)
    if task.module_id is None:
        if p:
            p.lane_id = None
        return
    task.estimate_seconds = task.estimate_seconds or 3600
    if p is None:
        current = now()
        start = current.replace(minute=(current.minute//15)*15, second=0, microsecond=0)
        if start < current:
            start += timedelta(minutes=15)
        p = TaskPlacement(task_id=task.id, lane_id=task.module_id, start=start, pinned=False)
        db.add(p)
    p.lane_id = task.module_id


def end(task: Task, placement: TaskPlacement) -> datetime:
    return task.actual_completed_at or placement.start + timedelta(seconds=task.estimate_seconds or 0)


def signature(g: dict[str, Any]) -> str:
    data = {
        'tasks': [(t.id, t.version, t.column_id, t.estimate_seconds, str(t.deadline), str(t.actual_started_at)) for t in g['tasks'].values()],
        'placements': [(p.task_id, p.lane_id, str(p.start), p.pinned) for p in g['placements'].values()],
        'lanes': [(l.id, l.name, l.position) for l in g['lanes']], 'edges': g['edges'],
    }
    return json.dumps(data, sort_keys=True, ensure_ascii=False)


@dataclass
class Change:
    project_id: int
    revision: int
    before: str
    starts: dict[int, datetime]
    ends: dict[int, datetime]
    parents: dict[int, set[int]]


def parents_of(g: dict[str, Any]) -> dict[int, set[int]]:
    parents: dict[int, set[int]] = {tid: set() for tid in g['tasks']}
    for edge in g['edges']:
        parents[edge['target']].add(edge['source'])
    return parents


def begin(db: Session, project_id: int, revision: int | None = None) -> Change:
    # First write takes SQLite's writer lock before any scheduling reads.
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert
    db.execute(sqlite_insert(PlanningState).values(project_id=project_id, revision=0).on_conflict_do_nothing())
    current = db.get(PlanningState, project_id)
    expected = current.revision if revision is None else revision
    affected = db.execute(update(PlanningState).where(PlanningState.project_id == project_id,
                          PlanningState.revision == expected).values(revision=expected + 1))
    if affected.rowcount != 1:
        raise api_error(409, 'VERSION_CONFLICT', 'Другой участник сохранил изменение раньше. Данные обновлены автоматически; проверьте их и повторите действие.')
    g = graph(db, project_id)
    return Change(project_id, expected, signature(g), {tid: p.start for tid, p in g['placements'].items()},
                  {tid: end(g['tasks'][tid], p) for tid, p in g['placements'].items()}, parents_of(g))


def order(g: dict[str, Any]) -> tuple[list[int], set[int]]:
    parents = parents_of(g)
    children: dict[int, set[int]] = {tid: set() for tid in parents}
    for child, sources in parents.items():
        for source in sources:
            children[source].add(child)
    ready = sorted(tid for tid, sources in parents.items() if not sources)
    result: list[int] = []
    while ready:
        tid = ready.pop()
        result.append(tid)
        for child in children[tid]:
            parents[child].discard(tid)
            if not parents[child]:
                ready.append(child)
    return result, set(parents) - set(result)


def validate_link(db: Session, project_id: int, source: int, target: int) -> None:
    g = graph(db, project_id)
    if source == target:
        raise api_error(422, 'INVALID_LINK', 'Нельзя соединить задачу с собой')
    if source not in g['tasks'] or target not in g['tasks']:
        raise api_error(422, 'INVALID_LINK', 'Выберите задачи этого проекта вне корзины')
    if any(e['source'] == source and e['target'] == target for e in g['edges']):
        raise api_error(422, 'DUPLICATE_LINK', 'Такая зависимость уже существует')
    adjacency: dict[int, set[int]] = {}
    for e in g['edges']:
        adjacency.setdefault(e['source'], set()).add(e['target'])
    pending, visited = [target], set()
    while pending:
        tid = pending.pop()
        if tid == source:
            raise api_error(422, 'DEPENDENCY_CYCLE', 'Связь создаёт цикл зависимостей')
        if tid not in visited:
            visited.add(tid)
            pending.extend(adjacency.get(tid, set()))


def require_preview(change: Change, after: str, changes: list[dict[str, Any]], conflicts: list[str], confirm: str | None) -> None:
    token = hashlib.sha256(f'{change.project_id}:{change.revision}:{change.before}:{after}'.encode()).hexdigest()
    if confirm != token:
        raise api_error(409, 'PLANNING_PREVIEW', 'Проверьте последствия изменения плана',
                        {'token': token, 'changes': changes, 'conflicts': conflicts})


def finish(db: Session, change: Change, confirm: str | None = None, explicit: set[int] | None = None) -> list[str]:
    g = graph(db, change.project_id)
    intent = signature(g)
    parents = parents_of(g)
    sequence, cyclic = order(g)
    conflicts: list[str] = []
    changes: list[dict[str, Any]] = []
    project = db.get(Project, change.project_id)
    active_columns = {c.id for c in db.query(BoardColumn).filter_by(project_id=change.project_id, semantic='active').all()}
    for tid in sequence:
        p = g['placements'].get(tid)
        if p is None:
            continue
        t = g['tasks'][tid]
        started = t.actual_started_at is not None or t.column_id in active_columns
        sources = parents[tid]
        # Soft links position a newly linked/placed task once. Manual overlaps persist.
        hard_sources = {e['source'] for e in g['edges'] if e['target'] == tid and e['type'] == 'blocked_by'}
        initial = tid not in change.starts or bool(sources - change.parents.get(tid, set()))
        sources = sources if initial and not (explicit and tid in explicit and tid in change.starts) else hard_sources
        available = [end(g['tasks'][s], g['placements'][s]) for s in sources if s in g['placements']]
        desired = p.start
        if sources and len(available) == len(sources):
            boundary = max(available)
            old_parents = change.parents.get(tid, set()) & sources
            old_ends = [change.ends[s] for s in old_parents if s in change.ends]
            if (explicit and tid in explicit) or tid not in change.starts:
                desired = max(p.start, boundary)
            elif old_parents == sources and len(old_ends) == len(sources):
                desired = max(boundary, change.starts[tid] + (boundary - max(old_ends)))
            else:
                desired = boundary
        if t.actual_completed_at:
            desired = p.start
        if started and desired != p.start:
            conflicts.append(f'«{t.title}»: задача уже начата; положение и фактическая история сохраняются, требуется ручная проверка зависимости')
            desired = p.start
        if p.pinned and desired != p.start:
            conflicts.append(f'«{t.title}»: перенос закреплённого начала')
        old_start = change.starts.get(tid)
        old_end = change.ends.get(tid)
        new_end = t.actual_completed_at or desired + timedelta(seconds=t.estimate_seconds or 0)
        if started and (old_start != desired or old_end != new_end) and not t.actual_completed_at:
            conflicts.append(f'«{t.title}»: задача уже начата; изменяется только план, фактическая история сохраняется')
        if old_start != desired or old_end != new_end:
            t.version += 1
            if project.deadline_msk and new_end > project.deadline_msk:
                conflicts.append(f'«{t.title}»: выход за дедлайн проекта')
            changes.append({'task_id':tid, 'title':t.title, 'old_start':old_start.isoformat() if old_start else None,
                            'start':desired.isoformat(), 'old_end':old_end.isoformat() if old_end else None,
                            'end':new_end.isoformat(), 'delta_seconds':int((new_end-old_end).total_seconds()) if old_end else None})
        p.start = desired
        t.deadline = p.start + timedelta(seconds=t.estimate_seconds or 3600)
    if cyclic:
        conflicts.append('В существующих данных есть цикл: его задачи не пересчитываются. Удалите противоречивую связь.')
    db.flush()
    return conflicts


def read(db: Session, project_id: int) -> dict[str, Any]:
    g = graph(db, project_id)
    project = db.get(Project, project_id)
    state = db.get(PlanningState, project_id)
    baselines = db.query(PlanningBaseline).filter_by(project_id=project_id).order_by(PlanningBaseline.id.desc()).all()
    baseline = baselines[0] if baselines else None
    snapshot = baseline.snapshot if baseline else {}
    columns = {c.id:c for c in db.query(BoardColumn).filter_by(project_id=project_id).all()}
    parents = parents_of(g)
    linked = {e[k] for e in g['edges'] for k in ('source', 'target')}
    placements: list[dict[str, Any]] = []
    limitations: list[str] = []
    for tid, p in g['placements'].items():
        t = g['tasks'][tid]
        finish_at = end(t, p)
        base = snapshot.get(str(tid))
        base_end = datetime.fromisoformat(base['end']) if base else None
        overdue = bool(t.deadline and t.deadline < now() and columns[t.column_id].semantic != 'done')
        blocked = bool(pending_blockers(db, t))
        if columns[t.column_id].semantic == 'done' and not t.actual_completed_at:
            limitations.append(f'«{t.title}»: нет достоверного времени завершения')
        if parents[tid] - g['placements'].keys():
            limitations.append(f'«{t.title}»: не все предшественники размещены')
        if not t.actual_completed_at and finish_at < now():
            limitations.append(f'«{t.title}»: плановое окончание прошло, задача не завершена')
        placements.append({'task_id':tid, 'lane_id':p.lane_id, 'start':p.start.isoformat(), 'end':finish_at.isoformat(),
                           'planned_end':(p.start+timedelta(seconds=t.estimate_seconds)).isoformat(),
                           'pinned':p.pinned, 'actual_started_at':t.actual_started_at, 'actual_completed_at':t.actual_completed_at,
                           'baseline':base, 'deviation_seconds':int((finish_at-base_end).total_seconds()) if base_end else None,
                           'blocked':blocked, 'overdue':overdue,
                           'before_start':bool(project.start_msk and p.start < project.start_msk),
                           'beyond_deadline':bool(project.deadline_msk and p.start + timedelta(seconds=t.estimate_seconds) > project.deadline_msk)})
    unplaced = set(g['tasks']) - g['placements'].keys()
    if unplaced:
        limitations.append(f'Не размещено задач: {len(unplaced)}; прогноз охватывает только размещённые задачи')
    sequence, cyclic = order(g)
    if cyclic:
        limitations.append('В старых связях есть цикл — критическая цепочка недоступна')
    latest = max((p['end'] for p in placements), default=None)
    chain: list[int] = []
    if latest and not cyclic and not unplaced:
        cursor = max(g['placements'], key=lambda tid:end(g['tasks'][tid],g['placements'][tid]))
        while True:
            chain.append(cursor)
            candidates = parents[cursor] & g['placements'].keys()
            if not candidates:
                break
            cursor = max(candidates, key=lambda tid:end(g['tasks'][tid],g['placements'][tid]))
        chain.reverse()
    owners: dict[int, set[int]] = {}
    for a in db.query(TaskAssignee).filter(TaskAssignee.task_id.in_(g['tasks'])).all():
        owners.setdefault(a.task_id, set()).add(a.user_id)
    overlaps = []
    for i, a in enumerate(placements):
        for b in placements[i+1:]:
            shared = owners.get(a['task_id'], set()) & owners.get(b['task_id'], set())
            if shared and a['start'] < b['planned_end'] and b['start'] < a['planned_end']:
                overlaps.append({'task_ids':[a['task_id'],b['task_id']], 'user_ids':sorted(shared)})
    track_incidents: dict[int, list[dict[str, Any]]] = {}
    for incident, target in (db.query(Incident, IncidentTarget).join(IncidentTarget, IncidentTarget.incident_id == Incident.id)
                             .filter(Incident.project_id == project_id, Incident.status != 'resolved', IncidentTarget.target_type == 'module').all()):
        track_incidents.setdefault(target.target_id, []).append({'id':incident.id, 'number':incident.number,
                                                               'title':incident.title, 'level':incident.level, 'status':incident.status})
    return {'revision':state.revision if state else 0, 'project':{'id':project.id,'name':project.name,'start':project.start_msk,'deadline':project.deadline_msk,'state':project.state},
            'lanes':[{'id':l.id,'name':l.name,'position':l.position,'incidents':track_incidents.get(l.id, [])} for l in g['lanes']],
            'tasks':[serialize_task(db,t).model_dump(mode='json') for t in g['tasks'].values()], 'placements':placements, 'edges':g['edges'],
            'unplaced_ids':sorted(unplaced), 'unconnected_ids':sorted(set(g['tasks'])-linked), 'overlaps':overlaps,
            'baseline':{'id':baseline.id,'created_at':baseline.created_at} if baseline else None, 'baseline_count':len(baselines),
            'forecast':{'finish':latest, 'deadline_delta_seconds':int((datetime.fromisoformat(latest)-project.deadline_msk).total_seconds()) if latest and project.deadline_msk else None,
                        'critical_chain':chain if not limitations else [], 'limitations':list(dict.fromkeys(limitations))}}
