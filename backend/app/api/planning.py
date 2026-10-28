"""Planning is a view of shared tasks, edited only by project captains/admins."""
from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session

from app.api.errors import api_error
from app.db.models import PlanningBaseline, Module as PlanningLane, Task, TaskDependency, TaskPlacement, User
from app.deps import get_db, require_captain_or_admin, require_member
from app.planning_schemas import PlanningCommand
from app.services import planning as svc
from app.services.audit import write_audit
from app.timeutil import to_naive_utc

router = APIRouter(tags=['planning'])


@router.get('/projects/{project_id}/planning')
def read_plan(project_id: int, db: Session = Depends(get_db), _user: User = Depends(require_member)) -> dict:
    return svc.read(db, project_id)


@router.post('/projects/{project_id}/planning')
def edit_plan(project_id: int, body: PlanningCommand, db: Session = Depends(get_db),
              user: User = Depends(require_captain_or_admin), x_planning_confirm: str | None = Header(None)) -> dict:
    change = svc.begin(db, project_id, body.revision)
    g = svc.graph(db, project_id)
    lanes = {l.id:l for l in g['lanes']}

    def lane(lane_id: int | None) -> PlanningLane:
        if lane_id not in lanes:
            raise api_error(422, 'INVALID_LANE', 'Дорожка не принадлежит этому проекту')
        return lanes[lane_id]

    def task(task_id: int | None) -> Task:
        if task_id not in g['tasks']:
            raise api_error(422, 'INVALID_TASK', 'Выберите задачу этого проекта вне корзины')
        return g['tasks'][task_id]

    if body.op in {'lane_create','lane_rename'}:
        if not body.name or not body.name.strip():
            raise api_error(422, 'INVALID_NAME', 'Введите название дорожки')
        if body.op == 'lane_create':
            db.add(PlanningLane(project_id=project_id, name=body.name.strip(), position=len(lanes)))
        else:
            lane(body.lane_id).name = body.name.strip()
    elif body.op == 'lane_reorder':
        if len(body.lane_ids) != len(lanes) or set(body.lane_ids) != set(lanes):
            raise api_error(422, 'INVALID_ORDER', 'Укажите все дорожки проекта ровно один раз')
        for position, lane_id in enumerate(body.lane_ids):
            lanes[lane_id].position = position
    elif body.op == 'lane_delete':
        removed = lane(body.lane_id)
        if body.target_lane_id is not None:
            if lane(body.target_lane_id).id == removed.id:
                raise api_error(422, 'INVALID_LANE', 'Выберите другую дорожку')
        for p in db.query(TaskPlacement).filter_by(lane_id=removed.id).all():
            p.lane_id = body.target_lane_id
            db.get(Task, p.task_id).module_id = body.target_lane_id
        for t in db.query(Task).filter_by(module_id=removed.id).all():
            t.module_id = body.target_lane_id
        db.flush()
        db.delete(removed)
    elif body.op in {'place', 'unplace'}:
        t = task(body.task_id)
        t.version += 1
        p = db.get(TaskPlacement, t.id)
        if body.op == 'unplace':
            t.module_id = None
            if p:
                p.lane_id = None
        else:
            lane(body.lane_id)
            t.module_id = body.lane_id
            if body.start is None:
                raise api_error(422, 'INVALID_START', 'Задайте время начала')
            if body.estimate_seconds is not None:
                t.estimate_seconds = body.estimate_seconds
                t.version += 1
            t.estimate_seconds = t.estimate_seconds or 3600
            if p is None:
                p = TaskPlacement(task_id=t.id, start=to_naive_utc(body.start), pinned=False)
                db.add(p)
            p.lane_id, p.start = body.lane_id, to_naive_utc(body.start)
            if body.pinned is not None:
                p.pinned = body.pinned
    elif body.op in {'link','unlink','set_blocker'}:
        source, target = task(body.source_id), task(body.target_id)
        if body.op == 'link':
            svc.validate_link(db, project_id, source.id, target.id)
            db.add(TaskDependency(task_id=target.id, predecessor_id=source.id, link_type='after'))
        elif body.op == 'set_blocker':
            if body.blocking is None:
                raise api_error(422, 'INVALID_LINK', 'Укажите тип связи')
            matching = [e for e in g['edges'] if e['source'] == source.id and e['target'] == target.id]
            if not matching:
                raise api_error(404, 'NOT_FOUND', 'Связь уже удалена')
            for edge in matching:
                db.query(TaskDependency).filter_by(task_id=edge['task_id'], predecessor_id=edge['predecessor_id']).delete()
            db.flush()
            db.add(TaskDependency(task_id=target.id, predecessor_id=source.id,
                                  link_type='blocked_by' if body.blocking else 'after'))
        else:
            for edge in g['edges']:
                if edge['source'] == source.id and edge['target'] == target.id:
                    db.query(TaskDependency).filter_by(task_id=edge['task_id'], predecessor_id=edge['predecessor_id']).delete()
        source.version += 1
        target.version += 1
    elif body.op == 'baseline':
        if db.query(PlanningBaseline).filter_by(project_id=project_id).first():
            svc.require_preview(change, 'baseline', [], ['Повторная фиксация изменит основу сравнения. Предыдущие снимки сохраняются.'], x_planning_confirm)
        snapshot = {str(tid):{'start':p.start.isoformat(), 'end':(p.start+timedelta(seconds=g['tasks'][tid].estimate_seconds)).isoformat(),
                               'estimate_seconds':g['tasks'][tid].estimate_seconds, 'lane_id':p.lane_id} for tid,p in g['placements'].items()}
        db.add(PlanningBaseline(project_id=project_id, actor_id=user.id, snapshot=snapshot))
    warnings = svc.finish(db, change, x_planning_confirm, {body.task_id} if body.op == 'place' else None)
    write_audit(db, action='planning.'+body.op, actor_id=user.id, project_id=project_id, data=body.model_dump(mode='json'))
    db.commit()
    return {**svc.read(db, project_id), 'warnings':warnings}
