"""Reproducible isolated browser fixture; never opens the working database."""
from __future__ import annotations

import os
from pathlib import Path
from datetime import datetime, timedelta, timezone

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / 'backend/tests/.tmp/planning-ui'
DATA.mkdir(parents=True, exist_ok=True)
os.environ.update(APP_DATA_DIR=str(DATA), DATABASE_URL=f"sqlite:///{(DATA/'hackathon.db').as_posix()}",
                  APP_FIRST_ADMIN_LOGIN='admin', APP_FIRST_ADMIN_PASSWORD='planning-ui-pass', APP_ENV='test')

from app.main import run_migrations
from app.db.session import SessionLocal
from app.db.models import (BoardColumn, PlanningLane, PlanningState, Project, ProjectState, Role,
                           RoleAssignment, Task, TaskAssignee, TaskDependency, TaskPlacement, User)
from app.security import hash_password
from app.services.bootstrap import bootstrap
from app.services.board import create_default_columns


def main() -> None:
    run_migrations()
    with SessionLocal() as db:
        bootstrap(db)
        if db.query(Task).count():
            print('Isolated planning fixture already exists')
            return
        start = datetime.now(timezone.utc).replace(tzinfo=None, minute=0, second=0, microsecond=0) + timedelta(hours=1)
        primary = db.get(Project, 1)
        primary.name, primary.deadline_msk = 'Проверка планирования', start+timedelta(hours=48)
        reader = User(login='reader', display_name='Участник', password_hash=hash_password('planning-ui-pass'), active=True)
        db.add(reader)
        db.flush()
        db.add(RoleAssignment(user_id=reader.id, project_id=1, role=Role.participant))
        for project, count in [(primary, 4), (Project(name='100 задач — нагрузочная проверка', state=ProjectState.active, deadline_msk=start+timedelta(hours=48)),100)]:
            if project.id is None:
                db.add(project);db.flush();create_default_columns(db,project.id)
            lanes = [PlanningLane(project_id=project.id,name=n,position=i) for i,n in enumerate(['Проектирование','Разработка','Интерфейс','Проверка','Релиз'][:2 if count==4 else 5])]
            db.add_all(lanes);db.flush()
            column = db.query(BoardColumn).filter_by(project_id=project.id,key='backlog').one()
            tasks = []
            for i in range(count):
                t=Task(project_id=project.id,column_id=column.id,title=(['Архитектура','API','Интерфейс','Без оценки'][i] if count==4 else f'Задача {i+1:03d}'),estimate_seconds=None if count==4 and i==3 else 3600,description='Изолированные данные для проверки планирования',version=1)
                db.add(t);db.flush();tasks.append(t)
                db.add(TaskAssignee(task_id=t.id,user_id=1,is_primary=True))
                if t.estimate_seconds:
                    db.add(TaskPlacement(task_id=t.id,lane_id=lanes[i%len(lanes)].id,start=start+timedelta(hours=i//len(lanes)),pinned=False))
            if count==100:
                for i in range(5,100):
                    db.add(TaskDependency(task_id=tasks[i].id,predecessor_id=tasks[(i-5)//2].id,link_type='after'))
            db.add(PlanningState(project_id=project.id,revision=0))
        db.commit()
    print('Isolated planning fixture ready')


if __name__ == '__main__':
    main()
