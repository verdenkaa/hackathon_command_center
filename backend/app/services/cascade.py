"""Read-only, deduplicated dependency reach and delay scenarios."""
from datetime import datetime, timedelta
from sqlalchemy.orm import Session

from app.cascade_schemas import CascadeLevel, CascadeOut, DelayScenario
from app.db.models import BoardColumn, TaskAssignee
from app.services.planning import graph, order


def analyse(db: Session, project_id: int, source_ids: list[int]) -> CascadeOut:
    g = graph(db, project_id)
    columns = {c.id:c.semantic for c in db.query(BoardColumn).filter_by(project_id=project_id).all()}
    tasks = {tid:t for tid,t in g['tasks'].items() if columns[t.column_id] != 'done'}
    roots = set(source_ids) & tasks.keys()
    result = CascadeOut(source_ids=sorted(roots))
    if not roots:
        result.limitations.append('Нет исходных незавершённых задач для расчёта.')
        return result
    hard: dict[int, set[int]] = {}
    all_links: dict[int, set[int]] = {}
    for e in g['edges']:
        if e['source'] in tasks and e['target'] in tasks:
            all_links.setdefault(e['source'], set()).add(e['target'])
            if e['type'] == 'blocked_by':
                hard.setdefault(e['source'], set()).add(e['target'])
    owners: dict[int, set[int]] = {}
    for a in db.query(TaskAssignee).filter(TaskAssignee.task_id.in_(tasks)).all():
        owners.setdefault(a.task_id, set()).add(a.user_id)
    reached_hard, reached_all = set(roots), set(roots)
    previous_hard, previous_potential = set(), set()
    for depth in range(1, 5):
        reached_hard |= {child for parent in list(reached_hard) for child in hard.get(parent, set())}
        reached_all |= {child for parent in list(reached_all) for child in all_links.get(parent, set())}
        hard_ids, potential = reached_hard - roots, reached_all - reached_hard
        affected = (reached_all - roots)
        placed = [g['placements'][tid] for tid in affected if tid in g['placements']]
        result.levels.append(CascadeLevel(
            depth=depth, hard_task_ids=sorted(hard_ids), potential_task_ids=sorted(potential),
            new_hard_count=len(hard_ids-previous_hard), new_potential_count=len(potential-previous_potential),
            user_ids=sorted({uid for tid in affected for uid in owners.get(tid, set())}),
            track_ids=sorted({tasks[tid].module_id for tid in affected if tasks[tid].module_id is not None}),
            start=min((p.start for p in placed), default=None),
            end=max((p.start+timedelta(seconds=tasks[p.task_id].estimate_seconds or 3600) for p in placed), default=None)))
        previous_hard, previous_potential = set(hard_ids), set(potential)
    sequence, cyclic = order(g)
    if cyclic:
        result.limitations.append('В графе есть цикл: сценарии для него не рассчитываются.')
    if tasks.keys() - g['placements'].keys():
        result.limitations.append('Есть неразмещённые задачи: временной прогноз частичный.')
    if any(columns[t.column_id] == 'active' or t.actual_started_at for t in tasks.values()):
        result.limitations.append('Сдвиги — оценка плана; фактическая работа и таймеры не изменяются.')
    starts = {tid:p.start for tid,p in g['placements'].items() if tid in tasks}
    durations = {tid:timedelta(seconds=tasks[tid].estimate_seconds or 3600) for tid in starts}
    parents: dict[int, set[int]] = {}
    for parent, children in hard.items():
        for child in children:
            parents.setdefault(child, set()).add(parent)

    def simulate(delay: int) -> dict[int, datetime]:
        ends = {tid:start+durations[tid] for tid,start in starts.items()}
        for tid in sequence:
            if tid not in starts:
                continue
            start = starts[tid] + (timedelta(seconds=delay) if tid in roots else timedelta())
            available = [ends[p] for p in parents.get(tid, set()) if p in ends]
            ends[tid] = max([start, *available]) + durations[tid]
        return ends

    baseline = simulate(0)
    baseline_finish = max(baseline.values(), default=None)
    for delay in (900, 3600, 14400):
        delayed = simulate(delay)
        finish = max(delayed.values(), default=None)
        result.scenarios.append(DelayScenario(
            delay_seconds=delay, task_ids=sorted(tid for tid in delayed if tid not in roots and delayed[tid] > baseline[tid]),
            finish_shift_seconds=int((finish-baseline_finish).total_seconds()) if finish and baseline_finish else 0))
    return result
