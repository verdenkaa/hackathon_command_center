"""Hard dependencies guard every entry point that starts work."""
from sqlalchemy.orm import Session

from app.api.errors import api_error
from app.db.models import BoardColumn, Task, TaskDependency


def pending_blockers(db: Session, task: Task) -> list[Task]:
    return (db.query(Task).join(TaskDependency, TaskDependency.predecessor_id == Task.id)
                .join(BoardColumn, BoardColumn.id == Task.column_id)
                .filter(TaskDependency.task_id == task.id, TaskDependency.link_type == 'blocked_by',
                        Task.project_id == task.project_id, BoardColumn.semantic != 'done').all())


def require_ready(db: Session, task: Task) -> None:
    blockers = pending_blockers(db, task)
    if blockers:
        names = ', '.join(f'#{t.id} «{t.title}»' for t in blockers)
        raise api_error(409, 'TASK_BLOCKED', f'Сначала завершите блокеры: {names}')
