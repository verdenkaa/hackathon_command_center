"""Isolated, explicitly synthetic data for inspecting analytics."""
from datetime import timedelta
from sqlalchemy.orm import Session
from app.db.models import Project, ProjectState, Module, Task, TaskAssignee, TaskTimer, TimerSegment
from app.schemas import IncidentTargetIn
from app.services.board import create_default_columns, get_column_by_key
from app.services.sandbox import get_team
from app.services.audit import write_audit
from app.services.incidents import create_incident
from app.services.notifications import notify_users
from app.timeutil import utcnow


def prepare_analytics_demo(db: Session, actor_id: int) -> Project:
    for project in db.query(Project).all():
        if (project.settings or {}).get('analytics_demo_v1'):
            return project
    now=utcnow()
    start=now-timedelta(hours=12)
    project=Project(name='Демо аналитики · 12 задач',state=ProjectState.active,
                    created_at=start,deadline_msk=now+timedelta(hours=12),settings={'analytics_demo_v1':True})
    db.add(project)
    db.flush()
    create_default_columns(db,project.id)
    team=get_team(db,project)
    owners=[team['alice'],team['bob'],team['cap']]
    modules=[Module(project_id=project.id,name='Платформа'),Module(project_id=project.id,name='Продукт')]
    db.add_all(modules)
    db.flush()
    titles=['Авторизация','Схема базы данных','API проектов','Карточки задач','Kanban-доска','Интеграция уведомлений','Настройки команды',
            'Экран аналитики','Обработка блокеров','Мобильная версия','Финальная проверка','Подготовка презентации']
    actuals=[3600,2700,4500,1800,3600,9000,1800,1800,1200,600,0,0]
    tasks: list[Task]=[]
    for index,(title,seconds) in enumerate(zip(titles,actuals)):
        key='done' if index<7 else 'in_progress' if index<10 else 'todo'
        task=Task(project_id=project.id,column_id=get_column_by_key(db,project.id,key).id,
                  module_id=modules[index%2].id,title=title,description='Демонстрационная задача',estimate_seconds=7200,
                  priority='high' if index==8 else 'medium',created_at=start,
                  deadline=now-timedelta(minutes=30) if index==8 else now+timedelta(hours=10))
        db.add(task)
        db.flush()
        tasks.append(task)
        db.add(TaskAssignee(task_id=task.id,user_id=owners[index%3].id,is_primary=True))
        event=write_audit(db,action='task.created',actor_id=actor_id,project_id=project.id,entity_type='task',entity_id=task.id,
                         data={'title':title,'column_semantic':'normal','demo':True})
        event.created_at=start
        if index<7:
            moved=write_audit(db,action='task.moved',actor_id=owners[index%3].id,project_id=project.id,entity_type='task',entity_id=task.id,
                              data={'from_title':'В работе','to_title':'Завершено','from_semantic':'active','to_semantic':'done','key':'done','demo':True})
            moved.created_at=start+timedelta(hours=2+index)
        elif index<10:
            moved=write_audit(db,action='task.moved',actor_id=owners[index%3].id,project_id=project.id,entity_type='task',entity_id=task.id,
                              data={'from_semantic':'normal','to_semantic':'active','key':'in_progress','demo':True})
            moved.created_at=start+timedelta(hours=9)
        running=7<=index<10
        accumulated=seconds-120 if running else seconds
        if seconds:
            db.add(TaskTimer(task_id=task.id,state='running' if running else 'stopped',accumulated_seconds=accumulated,
                             last_started_at=now-timedelta(seconds=120) if running else None))
            segment_start=start+timedelta(hours=1+index%5)
            db.add(TimerSegment(task_id=task.id,started_at=segment_start,ended_at=segment_start+timedelta(seconds=accumulated)))
            if running:
                db.add(TimerSegment(task_id=task.id,started_at=now-timedelta(seconds=120)))
    db.flush()
    for level,title,index in [('yellow','Нет ответа от тестового API',8),('red','Нужна проверка мобильного сценария',9)]:
        incident=create_incident(db,project_id=project.id,author_id=actor_id,owner_id=owners[index%3].id,
                                 level=level,title=title,description='Тестовый блокер для проверки перехода из уведомления',
                                 impact=None,urgency='high',targets=[IncidentTargetIn(target_type='task',target_id=tasks[index].id)])
        notify_users(db,project_id=project.id,user_ids=[actor_id,*[u.id for u in owners]],ntype=f'incident_{level}_created',payload={'incident_id':incident.id,'title':title})
    db.commit()
    return project
