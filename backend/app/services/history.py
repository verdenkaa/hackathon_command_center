"""Readable presentation, keeping original audit records intact."""
from sqlalchemy.orm import Session
from app.db.models import AuditEntry, BoardColumn, User

LABELS = {'title':'название', 'description':'описание', 'priority':'приоритет', 'module_id':'модуль',
          'estimate_seconds':'оценка времени (сек.)', 'deadline':'срок', 'tags':'теги', 'parent_id':'родительская задача'}
ACTIONS = {'task.created':'создал задачу', 'task.updated':'изменил свойства задачи',
           'task.assignees_set':'изменил исполнителей', 'task.dependency_added':'добавил связь задач',
           'task.dependency_removed':'удалил связь задач', 'task.checklist_added':'добавил пункт чек-листа',
           'timer.started':'запустил таймер', 'timer.paused':'приостановил таймер', 'timer.stopped':'остановил таймер',
           'timer.adjusted':'скорректировал фактическое время', 'task.time_adjusted':'скорректировал фактическое время'}


def history_text(db: Session, entry: AuditEntry) -> str:
    actor = db.get(User, entry.actor_id) if entry.actor_id else None
    who = actor.display_name if actor else 'Пользователь (имя недоступно)'
    data = entry.data or {}
    if entry.action == 'task.moved':
        def title(prefix: str) -> str:
            if data.get(f'{prefix}_title'):
                return data[f'{prefix}_title']
            col = db.get(BoardColumn, data[f'{prefix}_column']) if data.get(f'{prefix}_column') else None
            return col.title if col else 'удалённая колонка'
        return f'{who} переместил задачу из «{title("from")}» в «{title("to")}»'
    text = f'{who} {ACTIONS.get(entry.action, "выполнил действие с задачей")}'
    if entry.action == 'task.updated':
        text += ': ' + '; '.join(f'{LABELS.get(k, "свойство")}: {v.get("old") if v.get("old") is not None else "не задано"} → {v.get("new") if v.get("new") is not None else "не задано"}' for k,v in data.get('changes', {}).items())
    if entry.action == 'task.assignees_set':
        users = [db.get(User, uid) for uid in data.get('user_ids', [])]
        text += ': ' + (', '.join(u.display_name if u else 'имя недоступно' for u in users) or 'не назначены')
    return text
