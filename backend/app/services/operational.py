"""Read-only operational view using the existing plan and escalation algorithms."""
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import Incident, Project, Task
from app.deps import project_member_ids
from app.db.models import User
from app.operational_schemas import OperationalSummary
from app.services import planning
from app.services.cascade import analyse
from app.services.incidents import serialize_incident, traffic_status
from app.services.dependencies import pending_blockers
from app.timeutil import utcnow


def measure(numerator: int, denominator: int, missing: int = 0) -> dict[str, Any]:
    return {'numerator':numerator, 'denominator':denominator,
            'percent':round(numerator / denominator * 100, 1) if denominator else None,
            'missing_count':missing, 'incomplete':bool(missing),
            'unknown_reason':None if denominator else 'Нет данных для знаменателя'}


def build_summary(db: Session, project_id: int) -> OperationalSummary:
    now = utcnow()
    project = db.get(Project, project_id)
    plan = planning.read(db, project_id)
    tasks = plan['tasks']
    by_id = {t['id']:t for t in tasks}
    placements = {p['task_id']:p for p in plan['placements']}
    start, deadline = project.start_msk, project.deadline_msk
    duration = int((deadline-start).total_seconds()) if start and deadline else None
    elapsed = max(0, min(duration, int((now-start).total_seconds()))) if duration is not None else None
    remaining = max(0, int((deadline-now).total_seconds())) if deadline else None
    phase = ('no_deadline' if not deadline else 'overdue' if now >= deadline else
             'unknown_start' if not start else 'before_start' if now < start else 'running')
    period = {'start':start, 'deadline':deadline, 'phase':phase, 'duration_seconds':duration,
              'elapsed_seconds':elapsed, 'remaining_seconds':remaining,
              'until_start_seconds':max(0, int((start-now).total_seconds())) if start else None,
              'overdue_seconds':max(0, int((now-deadline).total_seconds())) if deadline else None,
              'percent':round(elapsed/duration*100, 1) if duration else None,
              'unknown_reason':'Дедлайн не задан' if not deadline else 'Начало проекта не задано' if not start else None}
    attention: list[dict[str, Any]] = []
    incidents: list[dict[str, Any]] = []
    unfinished = {t['id'] for t in tasks if t['column_semantic'] != 'done'}
    for incident in db.query(Incident).filter(Incident.project_id == project_id, Incident.status != 'resolved').order_by(Incident.id).all():
        info = serialize_incident(db, incident)
        depth = min(max(info.cascade_depth, 1), len(info.cascade.levels))
        level = info.cascade.levels[depth-1] if depth else None
        direct = {t.target_id for t in info.targets if t.target_type == 'task'} & unfinished
        hard = set(level.hard_task_ids) if level else set()
        potential = set(level.potential_task_ids) if level else set()
        affected = direct | hard | potential | set(info.cascade.source_ids)
        limits = list(info.cascade.limitations)
        if info.cascade_depth > len(info.cascade.levels) and info.cascade.levels:
            limits.append('Алгоритм эскалации охватывает только первые четыре уровня')
        track_ids = {by_id[tid]['module_id'] for tid in affected if tid in by_id and by_id[tid]['module_id'] is not None}
        track_ids.update(t.target_id for t in info.targets if t.target_type == 'module' and t.target_id in {l['id'] for l in plan['lanes']})
        incidents.append({'id':info.id, 'number':info.number, 'title':info.title, 'level':info.level,
                          'status':info.status, 'source_task_id':info.source_task_id, 'cascade_depth':info.cascade_depth,
                          'targets':[t.model_dump() for t in info.targets], 'direct_task_ids':sorted(direct),
                          'affected_task_ids':sorted(affected),
                          'hard_task_ids':sorted(hard), 'potential_task_ids':sorted(potential),
                          'track_ids':sorted(track_ids), 'limitations':limits})
        attention.append({'code':'incident', 'reason':f'Открытый инцидент #{info.number}: {info.title}', 'incident_id':info.id})
    blocked: dict[int, list[str]] = {}
    for task in db.query(Task).filter(Task.id.in_(by_id)).all():
        blocked[task.id] = [f"Сначала завершите #{p.id} «{p.title}»" for p in pending_blockers(db, task)]
    result_tasks = []
    for task in tasks:
        tid = task['id']
        reasons = blocked.get(tid, [])
        missing = [label for absent, label in [(task['module_id'] is None, 'Нет трека'),
                   (not task['assignees'], 'Нет исполнителя'), (task['estimate_seconds'] is None, 'Нет длительности'),
                   (tid not in placements, 'Нет размещения')] if absent]
        availability = ('done' if task['column_semantic'] == 'done' else 'active' if task['column_semantic'] == 'active'
                        else 'waiting' if reasons else 'ready')
        result_tasks.append({**task, 'track_name':next((l['name'] for l in plan['lanes'] if l['id'] == task['module_id']), None),
                             'availability':availability, 'waiting_reasons':reasons, 'missing':missing})
        checks = [('missing_plan', '; '.join(missing), bool(missing))]
        if tid in unfinished:
            checks.extend([('overdue', 'Просрочен срок задачи', bool(task['deadline'] and datetime.fromisoformat(task['deadline']) < now)),
                           ('exhausted', 'Длительность исчерпана по таймеру; задача не завершена', task['estimate_seconds'] is not None and task['timer'] is not None and task['timer']['total_seconds'] >= task['estimate_seconds'])])
        p = placements.get(tid)
        if p:
            checks.extend([('before_start', 'Задача начинается раньше начала проекта', bool(start and datetime.fromisoformat(p['start']) < start)),
                           ('beyond_deadline', 'Плановое окончание за дедлайном проекта', bool(deadline and datetime.fromisoformat(p['planned_end']) > deadline))])
        attention.extend({'code':code, 'reason':reason, 'task_ids':[tid]} for code, reason, exists in checks if exists)
    overlaps = [o for o in plan['overlaps'] if all(tid in unfinished for tid in o['task_ids'])]
    for overlap in overlaps:
        attention.append({'code':'overlap', 'reason':'Пересечение задач одного участника в плане', **overlap})
    tracks = []
    for lane in [*plan['lanes'], {'id':None, 'name':'Без трека'}]:
        group = [t for t in result_tasks if t['module_id'] == lane['id']]
        done = sum(t['availability'] == 'done' for t in group)
        ids = {t['id'] for t in group}
        tracks.append({'id':lane['id'], 'name':lane['name'], 'task_ids':sorted(ids), 'done':done, 'total':len(group),
                       'percent':round(done/len(group)*100, 1) if group else None,
                       'active':sum(t['availability'] == 'active' for t in group),
                       'waiting':sum(t['availability'] == 'waiting' for t in group),
                       'overdue':len({tid for a in attention if a['code'] == 'overdue' for tid in a['task_ids']} & ids),
                       'blocked':sum(bool(t['waiting_reasons'] or t['blocking_incidents']) for t in group if t['id'] in unfinished),
                       'incident_ids':[i['id'] for i in incidents if lane['id'] in i['track_ids'] or ids & set(i['direct_task_ids'])]})
    people = []
    for uid in sorted(project_member_ids(db, project_id)):
        own = [t for t in result_tasks if any(a['user_id'] == uid for a in t['assignees'])]
        active = [t['id'] for t in own if t['availability'] == 'active']
        own_ids = {t['id'] for t in own}
        own_tracks = {t['module_id'] for t in own if t['module_id'] is not None}
        related = [i['id'] for i in incidents if any(t['target_type'] == 'user' and t['target_id'] == uid for t in i['targets'])
                   or any(t['target_type'] == 'module' and t['target_id'] in own_tracks for t in i['targets'])
                   or own_ids & (set(i['direct_task_ids']) | set(i['hard_task_ids']) | set(i['potential_task_ids']) | {i['source_task_id']})]
        people.append({'id':uid, 'display_name':db.get(User, uid).display_name, 'traffic_status':traffic_status(db, 'user', uid, project_id),
                       'task_ids':[t['id'] for t in own], 'active_ids':active,
                       'ready_ids':[t['id'] for t in own if t['availability'] == 'ready'],
                       'waiting_ids':[t['id'] for t in own if t['availability'] == 'waiting'], 'incident_ids':related,
                       'overlaps':[o['task_ids'] for o in overlaps if uid in o['user_ids']],
                       'downstream':analyse(db, project_id, active)})
    forecast = plan['forecast']
    restrictions = list(forecast['limitations'])
    if not tasks:
        restrictions.append('В проекте нет задач: охват плана неизвестен')
    if any(t['missing'] for t in result_tasks):
        restrictions.append('Есть задачи без трека, исполнителя, длительности или размещения')
    status = ('completed' if project.state == 'completed' else 'overdue' if deadline and now >= deadline else
              'no_deadline' if not deadline else 'incomplete' if restrictions or not forecast['finish'] else
              'late' if forecast['deadline_delta_seconds'] > 0 else 'on_track')
    # Missing assignment is an explicit coverage limitation, even for a fully placed plan.
    limitations = list(dict.fromkeys([*restrictions,
        'План не моделирует рабочие смены и реальную доступность людей.',
        'Жёсткие зависимости запрещают старт; мягкие связи отражают порядок в плане.',
        'Инциденты показаны по сохранённым целям и действующему алгоритму эскалации; возможное влияние не означает блокировку старта.',
        'Влияние по зависимостям рассчитано существующим алгоритмом до четырёх уровней.']))
    known = [t for t in tasks if t['estimate_seconds'] is not None]
    return OperationalSummary.model_validate({
        'project_id':project_id, 'generated_at':now, 'project_state':project.state, 'period':period,
        'progress':{'tasks':measure(len(tasks)-len(unfinished), len(tasks)),
                    'duration':measure(sum(t['estimate_seconds'] for t in known if t['id'] not in unfinished),
                                       sum(t['estimate_seconds'] for t in known), len(tasks)-len(known))},
        'plan':{'status':status, 'incomplete':bool(restrictions), 'finish':forecast['finish'], 'deadline_delta_seconds':forecast['deadline_delta_seconds'],
                'covered_tasks':len(placements), 'total_tasks':len(tasks), 'limitations':limitations},
        'tasks':result_tasks, 'tracks':tracks, 'incidents':incidents, 'participants':people, 'attention':attention,
        'unassigned_ids':[t['id'] for t in tasks if not t['assignees']], 'limitations':limitations})
