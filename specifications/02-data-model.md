# Модель данных (as-built)

Дополнение от 28.10.2026: таблицы планирования, фактические отметки задач и миграция описаны в [Планировании](../docs/14-planning.md). Оно уточняет историческую схему ниже.

Схема прототипа: 27 таблиц SQLAlchemy 2.0.55 на SQLite 3.45.3, миграции Alembic 1.20.1. Источник истины — код `backend/app/db/models.py` и цепочка миграций `backend/alembic/versions/`; продуктовые требования в [docs/02-functional-requirements.md](../docs/02-functional-requirements.md) описывают замысел, а не фактическую схему. Расхождения с прежней версией этого документа и с требованиями — в разделе 9.

## 1. Назначение и источники истины

### 1.1. Что чему соответствует

| Слой | Файл | Что задаёт |
| --- | --- | --- |
| Декларативная база | `backend/app/db/base.py` | `Base(DeclarativeBase)`, единый `Base.metadata` |
| Модели | `backend/app/db/models.py` | 27 классов-таблиц, типы, FK, unique, индексы, Python-defaults, enum-классы |
| Движок и сессии | `backend/app/db/session.py` | URL из `backend/app/config.py`, `PRAGMA journal_mode=WAL`, `PRAGMA foreign_keys=ON`, `SessionLocal(autoflush=False, expire_on_commit=False)` |
| Миграции | `backend/alembic/versions/*.py`, `backend/alembic/env.py` | Фактический DDL; `env.py` берёт URL из настроек приложения, а не из `alembic.ini` |
| DTO | `backend/app/schemas.py` | Pydantic-схемы запросов/ответов; здесь же часть проверок значений |
| Поведение | `backend/app/api/*.py`, `backend/app/services/*.py` | Инварианты, переходы состояний, каскадные действия, которых нет в БД |
| Проверка | `backend/tests/*.py` | 84 pytest-теста; схема в тестах создаётся `Base.metadata.create_all`, а не миграциями |

### 1.2. Состав схемы и история миграций

Таблицы: `users`, `projects`, `role_assignments`, `sessions`, `login_events`, `ip_rules`, `audit_entries`, `audit_revisions`, `board_columns`, `modules`, `tasks`, `task_assignees`, `task_dependencies`, `checklist_items`, `task_timers`, `timer_segments`, `incidents`, `incident_targets`, `incident_events`, `notifications`, `documents`, `document_locks`, `ai_settings`, `ai_recommendations`, `completion_votes`, `backup_records`, `sandbox_runs`. Служебная таблица `alembic_version` создаётся Alembic и в моделях отсутствует.

| Ревизия | down_revision | Что создаёт/меняет |
| --- | --- | --- |
| `ae5d65fc0a23` | — | `projects`, `users`, `role_assignments`, `sessions`, `login_events`, `ip_rules`, `audit_entries`, `audit_revisions` |
| `f0c4c14d1a18` | `ae5d65fc0a23` | `board_columns`, `modules`, `tasks`, `task_assignees`, `task_dependencies`, `checklist_items`, `task_timers`, `timer_segments` |
| `bff78085fd9d` | `f0c4c14d1a18` | `incidents`, `incident_targets`, `incident_events`, `notifications` |
| `435366661053` | `bff78085fd9d` | `documents`, `document_locks`, `ai_settings`, `ai_recommendations` |
| `96cd78ac8062` | `435366661053` | `completion_votes`, `backup_records` |
| `70df8d8dfcdd` | `96cd78ac8062` | `sandbox_runs` |
| `bed2ce42ab1b` | `70df8d8dfcdd` | `task_dependencies.link_type` (NOT NULL без server_default) |
| `38bb310f4d87` (head) | `bed2ce42ab1b` | `board_columns.auto_start_timer`, `board_columns.auto_stop_timer` (NOT NULL, server_default=false) |

При стабилизации 2026-10-27 миграция `38bb310f4d87` исправлена: существующие колонки получают `false` для обоих правил таймера. Рабочая база обновлена до head без пересоздания; обновление заполненной таблицы проверяет `tests/test_migrations.py`. Описанные ниже ограничения этой ревизии относятся к состоянию до исправления; более ранняя `bed2ce42ab1b` в этом проходе не менялась.

### 1.3. Как проверить схему

```powershell
Set-Location backend
..\.venv\Scripts\python.exe -m alembic current          # какая ревизия применена
..\.venv\Scripts\python.exe -m alembic history          # цепочка
..\.venv\Scripts\python.exe -m alembic check            # расхождение metadata и БД (Alembic >= 1.9)
..\.venv\Scripts\python.exe -c "from app.db.base import Base; from app.db import models; print(len(Base.metadata.tables))"
```

Проверка фактического DDL без CLI `sqlite3`:

```python
import sqlite3
c = sqlite3.connect("data/hackathon.db")
for (name,) in c.execute("select name from sqlite_master where type='table' order by name"):
    print(name, [(r[1], r[2], r[3]) for r in c.execute(f"pragma table_info({name})")])
```

Важно: `backend/tests/conftest.py` делает `Base.metadata.drop_all/create_all`, поэтому зелёные 84 теста подтверждают модели, но не миграции. Расхождение моделей и миграций тестами не ловится.

## 2. Принципы хранения

| Принцип | Фактическая реализация | Следствие |
| --- | --- | --- |
| SQLite, WAL | `session.py:_set_sqlite_pragma`: `PRAGMA journal_mode=WAL`, `PRAGMA foreign_keys=ON` на каждом соединении приложения | Параллельные чтения не блокируются; писатель один. Миграции идут через отдельный engine в `alembic/env.py` без этого listener — при DDL `foreign_keys` не включается |
| Foreign keys | `FOREIGN KEY` объявлены у 40+ полей, но нигде нет `ON DELETE`/`ON UPDATE`/`cascade` | Удаление родителя при включённых FK даёт `IntegrityError`, а не каскад; API обходит это ручной переназначкой или soft-delete |
| ORM-связи | Ни одного `relationship()`/`back_populates` | Все join-ы ручные в запросах; ленивых коллекций и каскадов ORM нет |
| Время | `DateTime(timezone=True)`, но SQLite не хранит tzinfo; `models.utcnow()` и `timeutil.utcnow()` возвращают наивное UTC | API-вход `to_naive_utc` переводит aware-datetime в UTC и снимает tzinfo; наивный вход считается уже UTC (MSK-конвертации на backend нет). Поле `deadline_msk` хранит UTC, несмотря на имя |
| JSON | `sa.JSON` в SQLite — TEXT; используется в 7 полях (см. 2.1) | SQL-фильтров по JSON нет: теги и payload фильтруются/читаются в Python. Валидность JSON-структуры БД не проверяет |
| Enum | Только `ProjectState` и `Role` объявлены как `sa.Enum`; на SQLite это `VARCHAR` без CHECK (`create_constraint` по умолчанию False) | Хранится имя члена enum; у этих классов имя совпадает со значением. Остальные «перечисления» — `String` без ограничений |
| Defaults | Все значения по умолчанию — Python-side (`default=`, `onupdate=`); `server_default` нет ни в моделях, ни в миграциях | Вставка сырым SQL обязана задавать все NOT NULL поля; `onupdate=utcnow` срабатывает только при UPDATE через ORM |
| Строки и числа | `String(n)`/`Text`, `Integer`, `Boolean`; CHECK-ограничений нет | SQLite не контролирует длину `VARCHAR`;布尔 хранится как 0/1; отрицательные `accumulated_seconds`/`size_bytes` БД не запрещает |
| Транзакции | `SessionLocal` с `autoflush=False`, `expire_on_commit=False`; коммиты явные в API/сервисах | Часть сервисов коммитит внутри (`start_timer`, `create_session`, `create_backup`), другая часть — в endpoint. Единой UoW-границы нет |

### 2.1. JSON-поля

| Таблица.поле | Что хранится | Кто пишет |
| --- | --- | --- |
| `projects.settings` | объект, по умолчанию `{}` | никто; поле не читается и не изменяется |
| `tasks.tags` | список строк | `api/tasks.py:create_task/patch_task` |
| `audit_entries.data` | произвольный объект события | `services/audit.py:write_audit` и вызовы `write_audit` |
| `incident_events.data` | `{level,title,owner_id}` / `{comment}` / `{resolution}` / `{text}` | `services/incidents.py` |
| `notifications.payload` | `{task_id,title}`, `{incident_id,title,level}` и т.п. | `services/notifications.py:notify_users` |
| `ai_settings.triggers` | объект флагов | `services/ai.py:get_settings`, PATCH настроек |
| `sandbox_runs.logs` | список строк журнала сценария | `services/sandbox.py:record_run` |

### 2.2. Сериализация enum

`ProjectState` и `Role` описывают колонки как `sa.Enum(...)`. На SQLite это `VARCHAR(11)` с именами членов (`preparation`, `participant`, ...), без CHECK. Pydantic отдаёт значения строкой. `ColumnKey`, `Priority`, `TimerState`, `IncidentLevel`, `IncidentStatus`, `TargetType` объявлены в `models.py`, но нигде не используются как типы колонок или валидаторы — соответствующие поля хранятся как `String` (см. раздел 5).

## 3. Справочник таблиц

Обозначения: `PK` — первичный ключ; `FK→table.field` — внешний ключ; `UQ` — unique constraint; `IX` — индекс; `NN` — NOT NULL; `NULL` — допускает NULL; `def` — Python-default; `onupdate` — Python-onupdate. Все `id` — `Integer PRIMARY KEY` (SQLite rowid). Все `DateTime` — `DATETIME`, наивный UTC. Все `def` — только на стороне ORM. Длины строк — декларативные, SQLite их не проверяет.

### 3.1. users — аккаунты

| Поле | Тип | Ограничения/индекс | Смысл |
| --- | --- | --- | --- |
| id | Integer | PK | Идентификатор |
| login | String(128) | NN, UQ (`ix_users_login` unique) | Логин; сравнение точное, без нормализации регистра |
| password_hash | String(255) | NN | bcrypt-хеш (`security.hash_password`) |
| display_name | String(255) | NN | Отображаемое имя |
| telegram_username | String(128) | NULL | Username для упоминаний; API не валидирует формат |
| active | Boolean | NN, def `True` | Деактивация вместо удаления |
| avatar | String(255) | NULL | Поле есть, API его нигде не заполняет |
| created_at | DateTime | NN, def `utcnow()` | Создание |

### 3.2. projects — проекты

| Поле | Тип | Ограничения/индекс | Смысл |
| --- | --- | --- | --- |
| id | Integer | PK | Идентификатор |
| name | String(255) | NN | Название; не уникально |
| deadline_msk | DateTime | NULL | Дедлайн; фактически наивный UTC, имя историческое |
| state | Enum(ProjectState) | NN, def `preparation` | `preparation`/`active`/`completed`; `active` выставляется только песочницей |
| settings | JSON | NN, def `{}` | Не используется |
| created_at | DateTime | NN, def `utcnow()` | Создание |

### 3.3. role_assignments — роли

| Поле | Тип | Ограничения/индекс | Смысл |
| --- | --- | --- | --- |
| id | Integer | PK | Идентификатор назначения |
| user_id | Integer | FK→users.id, NN | Кому выдана роль |
| project_id | Integer | FK→projects.id, NULL | NULL для admin; для participant/captain API тоже допускает NULL |
| role | Enum(Role) | NN | `participant`/`captain`/`admin` |
| granted_by | Integer | FK→users.id, NULL | Кто выдал; у песочницы NULL |
| granted_at | DateTime | NN, def `utcnow()` | Когда выдана |
| revoked_at | DateTime | NULL | Soft-revoke; строка не удаляется |
| — | — | UQ (`user_id`,`project_id`,`role`) `uq_role_assignment`; IX(`user_id`) | Защита от дублей; NULL в SQLite не конфликтует |

### 3.4. sessions — сессии входа

| Поле | Тип | Ограничения/индекс | Смысл |
| --- | --- | --- | --- |
| id | Integer | PK | Идентификатор |
| token_hash | String(64) | NN, UQ (`ix_sessions_token_hash`) | sha256 сырого токена; сам токен только в cookie |
| user_id | Integer | FK→users.id, NN, IX | Владелец |
| ip | String(64) | NULL | IP входа |
| user_agent | String(512) | NULL | User-Agent; длина не ограничивается SQLite |
| created_at | DateTime | NN, def `utcnow()` | Создание |
| expires_at | DateTime | NN | `created_at + 7 дней`; продления нет |
| revoked_at | DateTime | NULL | Logout/сброс пароля/деактивация |

### 3.5. login_events — журнал попыток входа

| Поле | Тип | Ограничения/индекс | Смысл |
| --- | --- | --- | --- |
| id | Integer | PK | Идентификатор |
| login | String(128) | NN | Введённый логин; индекса нет |
| ip | String(64) | NULL | IP попытки |
| user_id | Integer | FK→users.id, NULL | Заполняется только для известного пользователя (деактивация); при неверном пароле NULL |
| success | Boolean | NN, def `False` | Успех |
| reason | String(128) | NULL | `bad_credentials`/`ip_blocked`/`rate_limited`/`deactivated`; при успехе NULL |
| created_at | DateTime | NN, def `utcnow()` | Время |
| — | — | IX(`ip`,`created_at`) `ix_login_event_ip_time` | Окно 15 минут для лимитов |

### 3.6. ip_rules — блокировки IP

| Поле | Тип | Ограничения/индекс | Смысл |
| --- | --- | --- | --- |
| id | Integer | PK | Идентификатор |
| ip | String(64) | NN, UQ (`ix_ip_rules_ip`) | Адрес |
| action | String(16) | NN, def `"block"` | Других действий код не использует |
| created_by | Integer | FK→users.id, NULL | Кто заблокировал |
| created_at | DateTime | NN, def `utcnow()` | Когда |

### 3.7. audit_entries — журнал действий

| Поле | Тип | Ограничения/индекс | Смысл |
| --- | --- | --- | --- |
| id | Integer | PK | Идентификатор |
| project_id | Integer | FK→projects.id, NULL | NULL для глобальных действий (пользователи, роли, IP) |
| actor_id | Integer | FK→users.id, NULL | Автор действия |
| action | String(128) | NN | Строковый код, например `task.moved` |
| entity_type | String(64) | NULL | `user`/`role`/`ip`/`project`/`column`/`module`/`task` |
| entity_id | String(64) | NULL | ID сущности в виде строки; FK нет |
| data | JSON | NN, def `{}` | Детали события |
| created_at | DateTime | NN, def `utcnow()` | Время |
| — | — | IX(`project_id`,`created_at`) | Выборка журнала проекта |

### 3.8. audit_revisions — правки журнала

| Поле | Тип | Ограничения/индекс | Смысл |
| --- | --- | --- | --- |
| id | Integer | PK | Идентификатор |
| audit_entry_id | Integer | FK→audit_entries.id, NN, IX | Какая запись правилась |
| field | String(64) | NN | `action`/`entity_type`/`entity_id` (whitelist в API) |
| old_value | Text | NULL | Прежнее значение |
| new_value | Text | NULL | Новое значение |
| edited_by | Integer | FK→users.id, NULL | Администратор |
| edited_at | DateTime | NN, def `utcnow()` | Время правки |

### 3.9. board_columns — колонки доски

| Поле | Тип | Ограничения/индекс | Смысл |
| --- | --- | --- | --- |
| id | Integer | PK | Идентификатор |
| project_id | Integer | FK→projects.id, NN, IX | Проект |
| key | String(64) | NN | Машинный ключ; для стартовых колонок фиксирован, для пользовательских — slug |
| title | String(128) | NN | Заголовок; у стартовых меняется через PATCH |
| position | Integer | NN | Порядок сортировки; уникальности нет |
| auto_start_timer | Boolean | NN, def `False` | Правило авто-старта таймера при перемещении |
| auto_stop_timer | Boolean | NN, def `False` | Правило авто-стопа |
| — | — | UQ(`project_id`,`key`) `uq_board_column_key` | Ключ уникален в проекте |

### 3.10. modules — модули проекта

| Поле | Тип | Ограничения/индекс | Смысл |
| --- | --- | --- | --- |
| id | Integer | PK | Идентификатор |
| project_id | Integer | FK→projects.id, NN, IX | Проект |
| name | String(255) | NN | Название |
| description | Text | NULL | Описание |
| traffic_status | String(16) | NN, def `"green"` | Поле-анахронизм: после создания не обновляется; API `/modules` отдаёт его, аналитика считает светофор заново |
| created_at | DateTime | NN, def `utcnow()` | Создание |

### 3.11. tasks — задачи

| Поле | Тип | Ограничения/индекс | Смысл |
| --- | --- | --- | --- |
| id | Integer | PK | Идентификатор |
| project_id | Integer | FK→projects.id, NN, IX | Проект |
| column_id | Integer | FK→board_columns.id, NN, IX | Текущая колонка; совпадение проекта с `project_id` БД не проверяет |
| module_id | Integer | FK→modules.id, NULL | Модуль; совпадение проекта проверяет API при создании/патче |
| parent_id | Integer | FK→tasks.id, NULL | Родительская задача; циклы и глубина не проверяются |
| title | String(255) | NN | Название |
| description | Text | NULL | Описание |
| priority | String(16) | NN, def `"medium"` | Свободная строка; API не валидирует |
| estimate_seconds | Integer | NULL | Плановая оценка, секунды; API требует `>= 0` |
| deadline | DateTime | NULL | Дедлайн, наивный UTC |
| tags | JSON | NN, def `[]` | Список строк |
| version | Integer | NN, def `1` | Оптимистическая блокировка для PATCH/move |
| created_at | DateTime | NN, def `utcnow()` | Создание |
| updated_at | DateTime | NN, def `utcnow()`, onupdate `utcnow()` | Обновление |

### 3.12. task_assignees — исполнители

| Поле | Тип | Ограничения/индекс | Смысл |
| --- | --- | --- | --- |
| id | Integer | PK | Идентификатор |
| task_id | Integer | FK→tasks.id, NN, IX | Задача |
| user_id | Integer | FK→users.id, NN, IX | Пользователь; членство в проекте и `active` не проверяются |
| is_primary | Boolean | NN, def `False` | Основной исполнитель; ровно один гарантирует только API |
| — | — | UQ(`task_id`,`user_id`) `uq_task_assignee` | Дубль запрещён |

### 3.13. task_dependencies — зависимости

| Поле | Тип | Ограничения/индекс | Смысл |
| --- | --- | --- | --- |
| id | Integer | PK | Идентификатор |
| task_id | Integer | FK→tasks.id, NN, IX | Зависимая задача |
| predecessor_id | Integer | FK→tasks.id, NN | Предшественник; индекса нет |
| link_type | String(16) | NN, def `"blocked_by"` | `blocked_by`/`after`/`before`; на поведение не влияет |
| — | — | UQ(`task_id`,`predecessor_id`) `uq_task_dependency` | Одна связь на пару |

### 3.14. checklist_items — чек-лист

| Поле | Тип | Ограничения/индекс | Смысл |
| --- | --- | --- | --- |
| id | Integer | PK | Идентификатор |
| task_id | Integer | FK→tasks.id, NN, IX | Задача |
| text | String(500) | NN | Текст пункта |
| done | Boolean | NN, def `False` | Отметка |
| position | Integer | NN, def `0` | Порядок; при добавлении берётся `count()`, поэтому после удаления возможны дубли |

### 3.15. task_timers — таймер задачи

| Поле | Тип | Ограничения/индекс | Смысл |
| --- | --- | --- | --- |
| id | Integer | PK | Идентификатор |
| task_id | Integer | FK→tasks.id, NN, UQ (`ix_task_timers_task_id` unique) | Одна строка на задачу |
| state | String(16) | NN, def `"stopped"` | `running`/`paused`/`stopped`; переходы только в сервисе |
| accumulated_seconds | Integer | NN, def `0` | Накопленное закрытыми сегментами время |
| last_started_at | DateTime | NULL | Начало текущего запуска; NULL в paused/stopped |
| created_at | DateTime | NN, def `utcnow()` | Создание |
| updated_at | DateTime | NN, def `utcnow()`, onupdate `utcnow()` | Обновление |

### 3.16. timer_segments — интервалы таймера

| Поле | Тип | Ограничения/индекс | Смысл |
| --- | --- | --- | --- |
| id | Integer | PK | Идентификатор |
| task_id | Integer | FK→tasks.id, NN, IX(`ix_timer_segment_task`) | Задача; пользователь не хранится |
| started_at | DateTime | NN | Начало сегмента |
| ended_at | DateTime | NULL | Конец; NULL у активного сегмента |

### 3.17. incidents — инциденты

| Поле | Тип | Ограничения/индекс | Смысл |
| --- | --- | --- | --- |
| id | Integer | PK | Идентификатор |
| project_id | Integer | FK→projects.id, NN, IX | Проект |
| level | String(16) | NN | `yellow`/`red`; API валидирует |
| status | String(16) | NN, def `"open"` | `open`/`confirmed`/`resolved`; переходы в сервисе |
| title | String(255) | NN | Заголовок |
| description | Text | NULL | Описание |
| impact | Text | NULL | Влияние |
| urgency | String(32) | NULL | Свободная строка; API не валидирует |
| author_id | Integer | FK→users.id, NN | Автор |
| owner_id | Integer | FK→users.id, NULL | Ответственный; существование/активность не проверяются |
| resolution | Text | NULL | Итог закрытия |
| created_at | DateTime | NN, def `utcnow()` | Создание |
| confirmed_at | DateTime | NULL | Подтверждение красного |
| resolved_at | DateTime | NULL | Закрытие |

### 3.18. incident_targets — цели инцидента

| Поле | Тип | Ограничения/индекс | Смысл |
| --- | --- | --- | --- |
| id | Integer | PK | Идентификатор |
| incident_id | Integer | FK→incidents.id, NN, IX | Инцидент |
| target_type | String(16) | NN | `task`/`module`/`user`; API валидирует |
| target_id | Integer | NN | ID цели; FK нет — связь только логическая, тип полиморфный |
| — | — | UQ(`incident_id`,`target_type`,`target_id`) | Дубли в рамках инцидента запрещены |

### 3.19. incident_events — журнал инцидента

| Поле | Тип | Ограничения/индекс | Смысл |
| --- | --- | --- | --- |
| id | Integer | PK | Идентификатор |
| incident_id | Integer | FK→incidents.id, NN, IX | Инцидент |
| actor_id | Integer | FK→users.id, NULL | Автор события |
| event_type | String(32) | NN | `created`/`confirmed`/`rejected`/`resolved`/`comment` |
| data | JSON | NN, def `{}` | Детали события |
| created_at | DateTime | NN, def `utcnow()` | Время |

### 3.20. notifications — внутренние уведомления

| Поле | Тип | Ограничения/индекс | Смысл |
| --- | --- | --- | --- |
| id | Integer | PK | Идентификатор |
| project_id | Integer | FK→projects.id, NULL | Проект |
| user_id | Integer | FK→users.id, NULL, IX | Получатель; NULL-адресация кодом не используется |
| type | String(64) | NN | Строковый тип (см. раздел 5); уникальности/дедупликации нет |
| payload | JSON | NN, def `{}` | Тело уведомления |
| read_at | DateTime | NULL | Прочитано; статуса доставки в Telegram нет |
| created_at | DateTime | NN, def `utcnow()` | Создание |
| — | — | IX(`user_id`,`read_at`) `ix_notification_user_read` | Непрочитанные |

### 3.21. documents — метаданные документов

| Поле | Тип | Ограничения/индекс | Смысл |
| --- | --- | --- | --- |
| id | Integer | PK | Идентификатор |
| project_id | Integer | FK→projects.id, NN, IX | Проект |
| path | String(512) | NN | Относительный путь в `data/documents/<project_id>/`; API требует `.md` при создании |
| author_id | Integer | FK→users.id, NULL | Автор |
| checksum | String(64) | NN | sha256 содержимого; используется как base для конфликта |
| trashed | Boolean | NN, def `False` | Корзина — флаг, файл остаётся на диске |
| created_at | DateTime | NN, def `utcnow()` | Создание |
| updated_at | DateTime | NN, def `utcnow()`, onupdate `utcnow()` | Обновление; при сохранении ставится вручную |
| — | — | UQ(`project_id`,`path`) `uq_document_path` | Путь уникален, включая корзину |

Содержимое в БД не хранится: только метаданные и checksum; изображения `assets/<uuid>.<ext>` вообще не попадают в `documents`.

### 3.22. document_locks — блокировки редактирования

| Поле | Тип | Ограничения/индекс | Смысл |
| --- | --- | --- | --- |
| id | Integer | PK | Идентификатор |
| document_id | Integer | FK→documents.id, NN, UQ (`ix_document_locks_document_id` unique) | Одна блокировка на документ |
| user_id | Integer | FK→users.id, NN | Держатель |
| acquired_at | DateTime | NN, def `utcnow()` | Когда взята |
| last_activity_at | DateTime | NN, def `utcnow()` | Heartbeat; TTL 5 минут |

### 3.23. ai_settings — настройки ИИ

| Поле | Тип | Ограничения/индекс | Смысл |
| --- | --- | --- | --- |
| id | Integer | PK | Идентификатор |
| project_id | Integer | FK→projects.id, NN, UQ (`ix_ai_settings_project_id` unique) | Одна настройка на проект |
| enabled | Boolean | NN, def `False` | Общий тумблер |
| priority_provider | String(32) | NN, def `"gemini"` | Свободная строка; PATCH принимает любую |
| prompt | Text | NN | Единственный текст промпта; `DEFAULT_PROMPT` подставляется сервисом, в БД default нет |
| interval_minutes | Integer | NN, def `30` | Ограничение частоты; API `5..1440` |
| triggers | JSON | NN, def `{}` | Флаги событий; нормализуется в `DEFAULT_TRIGGERS` сервисом |
| created_at | DateTime | NN, def `utcnow()` | Создание |
| updated_at | DateTime | NN, def `utcnow()`, onupdate `utcnow()` | Обновление |

### 3.24. ai_recommendations — рекомендации ИИ

| Поле | Тип | Ограничения/индекс | Смысл |
| --- | --- | --- | --- |
| id | Integer | PK | Идентификатор |
| project_id | Integer | FK→projects.id, NN, IX | Проект |
| provider | String(32) | NN | Копия `ai_settings.priority_provider`; фактический ответ всегда mock |
| trigger | String(32) | NN, def `"manual"` | Свободная строка из запроса; `manual` не лимитируется |
| summary | String(500) | NN | Краткий вывод |
| content | Text | NN | Полный текст рекомендации |
| excluded | Boolean | NN, def `False` | Исключение из будущего контекста; контекст не собирается |
| created_at | DateTime | NN, def `utcnow()` | Создание |

### 3.25. completion_votes — голоса завершения

| Поле | Тип | Ограничения/индекс | Смысл |
| --- | --- | --- | --- |
| id | Integer | PK | Идентификатор |
| project_id | Integer | FK→projects.id, NN, IX | Проект |
| user_id | Integer | FK→users.id, NN | Голосующий |
| action | String(16) | NN | `complete`/`reopen`; API regex |
| created_at | DateTime | NN, def `utcnow()` | Время |
| — | — | UQ(`project_id`,`user_id`,`action`) `uq_completion_vote` | Один голос на действие |

### 3.26. backup_records — резервные копии

| Поле | Тип | Ограничения/индекс | Смысл |
| --- | --- | --- | --- |
| id | Integer | PK | Идентификатор |
| path | String(512) | NN | Имя zip в `data/backups/`, не абсолютный путь |
| checksum | String(64) | NN | sha256 архива; проверяется при restore |
| size_bytes | Integer | NN, def `0` | Размер архива |
| kind | String(32) | NN, def `"automatic"` | `automatic`/`manual`/`safety` |
| created_at | DateTime | NN, def `utcnow()` | Создание |

### 3.27. sandbox_runs — журнал песочницы

| Поле | Тип | Ограничения/индекс | Смысл |
| --- | --- | --- | --- |
| id | Integer | PK | Идентификатор |
| scenario | String(64) | NN | Имя сценария; неизвестное имя даёт запись `error` |
| status | String(16) | NN, def `"ok"` | `ok`/`error` |
| logs | JSON | NN, def `[]` | Список строк |
| run_by | Integer | FK→users.id, NULL | Администратор |
| created_at | DateTime | NN, def `utcnow()` | Время |

## 4. Связи и кардинальности

Все перечисленные FK — без `ON DELETE`/`ON UPDATE` (см. 2). ORM-коллекций нет.

- `projects` 1—N `role_assignments` (FK `project_id`, nullable), `board_columns`, `modules`, `tasks`, `incidents`, `documents`, `ai_recommendations`, `completion_votes`; `projects` 1—1 `ai_settings` (UQ `project_id`); `projects` 1—N `notifications` и `audit_entries` (nullable).
- `users` 1—N `role_assignments` (FK `user_id`, `granted_by`), `sessions`, `login_events` (nullable), `ip_rules.created_by` (nullable), `audit_entries.actor_id` (nullable), `audit_revisions.edited_by` (nullable), `task_assignees`, `incidents.author_id`/`owner_id` (nullable), `notifications.user_id` (nullable), `documents.author_id` (nullable), `document_locks.user_id`, `completion_votes`, `sandbox_runs.run_by` (nullable).
- `board_columns` 1—N `tasks.column_id`; `modules` 1—N `tasks.module_id` (nullable); `tasks` 1—N `tasks.parent_id` (самоссылка, nullable).
- `tasks` 1—N `task_assignees`, `task_dependencies.task_id`, `task_dependencies.predecessor_id` (две FK на `tasks`), `checklist_items`, `timer_segments`; `tasks` 1—1 `task_timers` (UQ `task_id`).
- `incidents` 1—N `incident_targets`, `incident_events`; `incident_targets.target_id` — только логическая связь с `tasks`/`modules`/`users`, FK нет.
- `documents` 1—1 `document_locks` (UQ `document_id`).
- `audit_entries` 1—N `audit_revisions`.
- `audit_entries.entity_type`/`entity_id`, `notifications.payload.*_id`, `backup_records.path`, `sandbox_runs.scenario` — логические ссылки без FK.
- `role_assignments.project_id` участвует в данных, но проверки прав (`deps.active_roles`, `require_role`) его игнорируют: роль любого проекта действует глобально. Это связь «на бумаге», а не граница доступа.

## 5. Значения перечислений и свободных строк

| Поле/сущность | Значения | Где задано/проверяется |
| --- | --- | --- |
| `Role` | `participant`, `captain`, `admin` | `models.Role`, `sa.Enum`; `admin` хранится с `project_id = NULL` (`api/admin.py:assign_role`) |
| `ProjectState` | `preparation`, `active`, `completed` | `models.ProjectState`, `sa.Enum`; `active` — только `services/sandbox.py:get_sandbox_project`; обычные проекты создания получают `preparation` |
| `BoardColumn.key` (стартовые) | `backlog`, `todo`, `specification_review`, `in_progress`, `testing`, `review`, `done`, `realised`, `trashed` | `services/board.py:DEFAULT_COLUMNS`; `ColumnKey` как тип не используется |
| `BoardColumn.key` (пользовательские) | `[a-z0-9_]+`, при пустом slug — `custom`, далее `custom_2`, `custom_3`, ... | `api/projects.py:_slug`, `create_column` |
| `Priority` | `low`, `medium`, `high`, `critical` | Объявлен `models.Priority`, не используется; `tasks.priority` — свободная строка, API не валидирует |
| `TimerState` | `running`, `paused`, `stopped` | Объявлен, не используется; `task_timers.state` ставит `services/timers.py` |
| `IncidentLevel` | `yellow`, `red` | Объявлен, не используется; `api/incidents.py:create_incident` проверяет строку |
| `IncidentStatus` | `open`, `confirmed`, `resolved` | `services/incidents.py:create_incident/confirm_red/resolve_incident`; `open → confirmed` (только красный), `open → resolved` (жёлтый или отказ от эскалации), `confirmed → resolved` |
| `TargetType` | `task`, `module`, `user` | Объявлен, не используется; `api/incidents.py:create_incident` проверяет строку; `target_id` не существует-проверяется |
| `TaskDependency.link_type` | `blocked_by` (default), `after`, `before` | `api/tasks.py:add_dependency`; семантика не реализована |
| `Notification.type` (фактические) | `task_assigned`, `incident_yellow_created`, `incident_red_created`, `incident_red_confirmed`, `incident_resolved`, `task_overdue` | `api/tasks.py`, `api/incidents.py`, `services/jobs.py`; ограничения в БД нет |
| `AuditEntry.action` (фактические) | `bootstrap.admin_created`, `user.created`, `user.login_changed`, `user.name_changed`, `user.password_reset`, `user.deactivated`, `role.granted`, `role.revoked`, `ip.blocked`, `ip.unblocked`, `ip.limit_reset`, `project.created`, `project.renamed`, `project.deadline_changed`, `project.completed`, `project.reopend`, `column.created`, `column.updated`, `column.deleted`, `module.created`, `module.updated`, `module.deleted`, `task.created`, `task.updated`, `task.moved`, `task.assignees_set`, `task.dependency_added`, `task.dependency_removed`, `task.checklist_added`, `task.time_adjusted` | `services/audit.py` и вызовы; строка не ограничена. Опечатка `project.reopend` — фактическое значение |
| `AuditEntry.entity_type` | `user`, `role`, `ip`, `project`, `column`, `module`, `task`, `NULL` | Там же |
| `BackupRecord.kind` | `automatic` (планировщик, 900 с), `manual` (API), `safety` (перед restore) | `main._scheduler_loop`, `api/operations.py`, `services/backup.py` |
| `CompletionVote.action` | `complete`, `reopen` | `api/operations.py:CompletionVoteRequest` (regex) |
| `AiSettings.triggers` | ключи `red_confirmed`, `blocker_created`, `blocker_closed`, `overdue`, `deadline_6h`; значения bool | `services/ai.py:DEFAULT_TRIGGERS`; PATCH принимает произвольный объект, флаги нигде не исполняются |
| `Project.settings` | произвольный JSON, по умолчанию `{}` | Не читается и не пишется |
| `SandboxRun.status` | `ok`, `error` | `api/sandbox.py:run_scenario`, `services/sandbox.py:record_run` |
| `SandboxRun.scenario` | `create_team`, `simulate_sprint`, `overdue_as_dev`, `incident_as_dev`, `timer_cycle`, `integration_failure` | `services/sandbox.py:SCENARIOS`; API принимает любую строку, неизвестная даёт `error` |
| `IncidentEvent.event_type` | `created`, `confirmed`, `rejected`, `resolved`, `comment` | `services/incidents.py` |
| `Incident.urgency` | свободная строка до 32 символов; песочница использует `high`, `medium` | `api/incidents.py` не валидирует |
| `IpRule.action` | `block` (default); других значений код не проверяет | `services/auth_service.py:is_ip_blocked` |
| `LoginEvent.reason` | `bad_credentials`, `ip_blocked`, `rate_limited`, `deactivated`, `NULL` при успехе | `services/auth_service.py:authenticate` |
| `AiSettings.priority_provider` | `gemini` (default), любая строка через PATCH | `services/ai.py:get_settings`; `settings.ai_priority_provider` из конфига не используется |
| `Task.priority` | любая строка до 16 символов; фактически `medium` | `schemas.TaskCreate/TaskPatch` не ограничивают |
| `Module.traffic_status` | только `green` (default), не обновляется | `models.Module`; светофор считается в `services/incidents.py:traffic_status` |
| `Document.path` | при создании обязан заканчиваться `.md`/`.markdown`; `/` разрешён как разделитель каталогов | `api/documents.py:ALLOWED_EXT` |
| `User.avatar` | всегда `NULL` | API не устанавливает |
| `Session` cookie | имя `session`, HttpOnly, SameSite=Lax, 7 дней, без `Secure` | `api/auth.py:login`, `deps.SESSION_COOKIE` |

## 6. Инварианты

### 6.1. Обеспечены схемой БД

| Инвариант | Механизм |
| --- | --- |
| Логин уникален | `users.login` unique index |
| Хеш токена сессии уникален | `sessions.token_hash` unique index |
| IP-правило уникально | `ip_rules.ip` unique index |
| Роль не дублируется для (user, project, role) | `uq_role_assignment` |
| Ключ колонки уникален в проекте | `uq_board_column_key` |
| Один исполнитель не дублируется в задаче | `uq_task_assignee` |
| Одна зависимость на пару задач | `uq_task_dependency` |
| Один таймер на задачу | `task_timers.task_id` unique |
| Одна цель не дублируется в инциденте | `uq_incident_target` |
| Путь документа уникален в проекте | `uq_document_path` |
| Одна блокировка на документ | `document_locks.document_id` unique |
| Одна настройка ИИ на проект | `ai_settings.project_id` unique |
| Один голос на действие | `uq_completion_vote` |
| Существование родителей | FK при `PRAGMA foreign_keys=ON` в приложении |

### 6.2. Обеспечены API/сервисом (не БД)

| Инвариант | Где именно |
| --- | --- |
| Таймер: нельзя стартовать дважды, пауза только из `running`, стоп только из `running/paused` | `services/timers.py:start_timer/pause_timer/stop_timer` (409 `TIMER_RUNNING`/`TIMER_NOT_RUNNING`/`TIMER_NOT_ACTIVE`) |
| Время задачи = `accumulated_seconds` + текущий сегмент; закрытие сегмента добавляет `max(0, ...)` | `services/timers.py:current_elapsed/_close_running_segment/total_seconds` |
| Календарное время команды не двойное: интервалы объединяются | `services/timers.py:merge_intervals/project_calendar_seconds`; тест `test_merge_intervals` |
| Ручная корректировка времени — только captain/admin | `api/timers.py:time_adjustment` (`require_captain_or_admin`) |
| Ровно один основной исполнитель при непустом наборе | `api/tasks.py:set_assignees`; 422 при 0 или >1 |
| Оптимистическая блокировка задачи | `api/tasks.py:_check_version` + инкремент `version` в `patch_task/move_task/set_assignees` |
| Зависимость: не на себя, не из чужого проекта, допустимый `link_type` | `api/tasks.py:add_dependency` |
| Модуль задачи принадлежит проекту | `api/tasks.py:_validate_module` |
| Родительская задача принадлежит проекту (при создании) | `api/tasks.py:create_task` |
| Стартовые колонки нельзя удалить; задачи пользовательской колонки переезжают в `backlog` | `api/projects.py:delete_column` + `DEFAULT_COLUMN_KEYS` |
| При удалении модуля `tasks.module_id` обнуляется | `api/projects.py:delete_module` |
| Последнего администратора нельзя деактивировать/лишить роли | `api/admin.py:deactivate/revoke_role` (409 `LAST_ADMIN`) |
| `admin` всегда с `project_id = NULL` | `api/admin.py:assign_role` |
| Правка аудита — только 3 поля, с ревизией | `api/admin.py:edit_audit` |
| Лимиты входа: 5 неудач на логин и 10 на IP за 15 минут; блокировка IP; запрет входа деактивированному | `services/auth_service.py:authenticate/failure_counts` |
| Сессия: срок 7 дней, отзыв, проверка `active` | `services/auth_service.py:create_session`, `deps.get_current_user` |
| Документ: только Markdown, checksum-конфликт, TTL блокировки 5 минут | `api/documents.py:create_document/save_content`, `services/documents.py:active_lock/acquire_lock` |
| Инцидент: красный подтверждает только captain/admin, жёлтый закрывает owner или captain/admin, статусы проверяются | `api/incidents.py:confirm_red/resolve_incident`, `services/incidents.py` |
| Светофор: подтверждённый красный → `red`, любой активный жёлтый → `yellow`, иначе `green` | `services/incidents.py:traffic_status` |
| ИИ: выключенный советник не запускается; неручной триггер лимитируется `interval_minutes` | `services/ai.py:run_recommendation/rate_limited` (in-memory) |
| Завершение/открытие проекта — только единогласие всех активных captain+admin | `api/operations.py:completion_vote` |
| Completed-проект частично read-only | `deps.ensure_project_active`; вызовы только в `api/tasks.py` (create/move/assignees/dependency add), `api/timers.py`, `api/incidents.py` (create/confirm/resolve) |
| Просрочка уведомляет один раз на задачу на проект | `services/jobs.py:check_overdue` (дедуп по `payload.task_id`) |
| Бэкап проверяется по sha256; перед restore создаётся safety-копия; `latest.zip` обновляется атомарно | `services/backup.py:create_backup/restore_backup` |
| Песочница: сценарий из whitelist или запись `error` | `services/sandbox.py:run_scenario` |
| Bootstrap создаёт администратора и проект только в пустой БД | `services/bootstrap.py:bootstrap` |

### 6.3. Не обеспечены

| Пробел | Последствие |
| --- | --- |
| «Ровно один основной исполнитель» только в API | Прямая запись в БД или гонка двух PUT даёт 0/2 primary; БД constraint нет |
| `role_assignments.project_id` не проверяется и не влияет на права | Роль, выданная на проект A, действует на всех проектах; participant/captain с `project_id = NULL` — норма (так в тестах и в живой БД) |
| Повторная выдача отозванной роли | `assign_role` ищет только `revoked_at IS NULL` и делает INSERT; старая строка осталась, `uq_role_assignment` даёт `IntegrityError` (500) для проектной роли. Для `project_id = NULL` unique не срабатывает |
| Read-only завершённого проекта | Не блокируются: `PATCH /tasks/{id}`, чек-лист, зависимости (удаление), колонки, модули, документы, комментарии инцидентов, ИИ, бэкапы, голосование |
| `Task.column_id`/`module_id`/`parent_id` принадлежат тому же проекту | Гарантируется только API и только при создании/перемещении; БД допускает межпроектные ссылки |
| Циклы зависимостей и подзадач | Не проверяются; глубина подзадач не ограничена |
| Предупреждение о незавершённой зависимости | Не реализовано: переход не блокируется и не предупреждает |
| Значения `priority`, `urgency`, `notification.type`, `backup.kind`, `sandbox.status`, `link_type`, `event_type` | Нет CHECK/enum в БД; часть проверяется API, часть — нет |
| `ai_settings.triggers` | Произвольный JSON; флаги не исполняются |
| Один открытый `timer_segments` на задачу; `ended_at >= started_at` | Нет constraint; сервис закрывает только первый найденный открытый сегмент |
| `task_assignees.user_id` — член проекта и активен | Не проверяется; можно назначить деактивированного или постороннего |
| `incidents.owner_id`, `incident_targets.target_id` существуют | Не проверяется; FK у цели отсутствует, owner может быть несуществующим (ошибка FK при вставке) |
| Уникальность `module.traffic_status`-поведения | Колонка не обновляется, `/modules` и `/analytics` могут показывать разный светофор |
| Очистка `sessions`, `login_events`, `audit_entries`, старых `backup_records` | Фоновой очистки нет; таблицы растут |
| Неизменяемость аудита | Администратор перезаписывает `action`/`entity_type`/`entity_id`; исходное значение остаётся только в `audit_revisions` |
| Версионирование документов, физическое удаление, снятие блокировки при trashe | Нет; файл и блокировка остаются |
| Проверка владельца/членства для документов, инцидентов, ИИ | Многие чтения/записи доступны любому аутентифицированному (`get_current_user`), а не только члену проекта |
| Лимиты размера документов/изображений | Нет; `UploadFile` читается целиком, тип проверяется только по расширению |
| Уникальность `board_columns.position` и reorder | Нет; порядок задаётся числом, API переупорядочивания отсутствует |
| `Project.settings` | Схема не определена, поле мёртвое |
| `User.avatar` | Не заполняется |
| Атрибуция времени пользователю | `task_timers`/`timer_segments` не содержат `user_id`; отчёты относят время задачи к основному исполнителю |

## 7. Правила изменения и удаления

### 7.1. Колонки

- Создание: любой участник (`require_member`), `key = slug(title)` с суффиксом при коллизии, `position = max(position)+1`; `auto_start_timer`/`auto_stop_timer` задаются сразу (`api/projects.py:create_column`).
- Изменение: `title`, оба флага; `key` и `project_id` неизменяемы (`patch_column`).
- Удаление: только не стартовая колонка (409 `COLUMN_PROTECTED` для 9 ключей). Задачи массово переводятся в `backlog` (`UPDATE tasks SET column_id`), затем строка удаляется; позиции остальных колонок не перенумеровываются.
- Стартовые колонки создаются `services/board.py:create_default_columns` при bootstrap и `POST /projects`; `trashed` — обычная колонка, не удаление задачи.

### 7.2. Модули

- Создание/изменение — любой участник; `name`/`description`; `traffic_status` через API не меняется.
- Удаление — любой участник; `tasks.module_id` обнуляется, строка удаляется, аудит `module.deleted`. Инциденты, ссылающиеся на модуль через `incident_targets.target_id`, остаются с «висячей» целью.
- Отдельного soft-delete нет; имя не уникально.

### 7.3. Пользователи и роли

- Создание — только admin; логин уникален, пароль хешируется bcrypt (`api/admin.py:create_user`).
- Изменение — логин/имя/telegram; смена пароля отзывает все сессии.
- Деактивация — `active = False`, все активные роли получают `revoked_at = now`, все сессии отзываются; запрещена для последнего активного администратора (409 `LAST_ADMIN`). Физического удаления нет, история и FK сохраняются.
- Роли: выдача только admin; `admin` принудительно с `project_id = NULL`; дубль активной роли — 409 `ROLE_EXISTS`; отзыв — soft (`revoked_at`), последнюю admin-роль отозвать нельзя. Повторная выдача после отзыва для проектной роли упирается в unique (см. 6.3).

### 7.4. Документы, корзина и блокировки

- Создание: путь нормализуется `strip().strip("/")`, требуется `.md`/`.markdown`, дубль пути — 409; файл пишется в `data/documents/<project_id>/<path>`, в БД — метаданные и checksum.
- Сохранение: `base_checksum` обязателен; несовпадение — 409 `VERSION_CONFLICT`; файл перезаписывается, checksum и `updated_at` обновляются.
- Корзина: `DELETE /documents/{id}` ставит `trashed = True`, файл и блокировка не трогаются; `restore` снимает флаг. Постоянного удаления нет. UQ(`project_id`,`path`) не даёт создать новый документ с путём, лежащим в корзине.
- Блокировка: одна на документ (UQ), берётся на 5 минут, продлевается heartbeat, снимается вручную или лениво при чтении/фоновой задачей (`jobs.cleanup_locks`, тик 60 с). Чужой захват — 409 `DOCUMENT_LOCKED`.
- Изображения: `POST /projects/{id}/documents/images` пишет `assets/<uuid>.<ext>` в файловую систему без записи в `documents`; отдаются `FileResponse` без проверки членства. Проверка пути (`resolve_path`) использует `str(p).startswith(str(root))`, поэтому путь вида `../10/x.md` для проекта 1 проходит проверку и попадает в каталог проекта 10.

### 7.5. Сессии

- Создаются при логине: сырой токен в HttpOnly-cookie `session`, в БД только sha256, TTL 7 дней (`auth_service.create_session`).
- Logout ставит `revoked_at`; сброс пароля и деактивация отзывают все сессии; `get_current_user` отвергает revoked/expired.
- Продления, ротации, очистки истёкших строк и ограничения числа сессий нет. Восстановление БД из старого бэкапа может «воскресить» сессии, сохранённые в нём.

### 7.6. Завершение проекта

- Голосование `POST /projects/{id}/completion-votes` доступно captain/admin; считается по **всем** активным captain+admin (глобально, без привязки к проекту). При единогласии: `complete → ProjectState.completed`, `reopen → ProjectState.preparation`; все голоса проекта удаляются, пишется аудит.
- Состояние `active` для обычного проекта недостижимо: API нет перехода в него, только песочница создаёт проект сразу `active`.
- Read-only частичный: блокируются создание/перемещение задач, назначение исполнителей, добавление зависимостей, таймеры, создание/подтверждение/закрытие инцидентов. Не блокируются `PATCH /tasks/{id}`, чек-лист, удаление зависимостей, колонки, модули, документы, комментарии, ИИ, бэкапы, голосование.
- Завершённый проект остаётся в списке, дашборд/аналитика читаются; фоновые проверки просрочек его пропускают (`Project.state != "completed"`).

### 7.7. Аудит

- Записи только добавляются (`write_audit` + `flush`); удаления нет.
- Администратор может изменить только `action`, `entity_type`, `entity_id`; старое значение пишется в `audit_revisions` (`edited_by`, `edited_at`). Причина правки не хранится.
- Исходная строка при этом теряет прежнее значение; «неизменяемость» обеспечивается только ревизией. Проектного фильтра в `GET /audit` нет — журнал общий.

### 7.8. Бэкапы

- `POST /admin/backups` (captain/admin) и планировщик каждые 900 с создают zip: `database.sqlite` (sqlite backup API), `documents/`, `manifest.json`; запись в `backup_records` с sha256 и размером.
- Хранится `latest.zip` + последний обычный `backup_*.zip`; старые обычные архивы удаляются, `*_safety.zip` не удаляются никогда. Строки `backup_records` не чистятся и переживают удаление файлов.
- Restore требует `confirm: true`, проверяет sha256, делает safety-копию, закрывает сессию/`engine`, заменяет файл БД и каталог документов, затем `stamp_head()`. Схема восстанавливаемой БД не сверяется: старый бэкап может не соответствовать текущим моделям, а `stamp_head` всё равно помечает его как head.

## 8. Как менять схему

1. Изменить модели в `backend/app/db/models.py`; при необходимости — `schemas.py` и сервисы.
2. Сгенерировать миграцию из `backend`:
   ```powershell
   ..\.venv\Scripts\python.exe -m alembic revision --autogenerate -m "add ..."
   ```
   `env.py` подставит URL из `app.config.settings`, `alembic.ini` для этого не используется.
3. Проверить сгенерированный DDL вручную: Alembic не видит Python-defaults как server-defaults и может предложить опасный `NOT NULL` без значения.
4. Для SQLite использовать batch-режим для ALTER/DROP/constraint:
   ```python
   with op.batch_alter_table("board_columns") as batch:
       batch.add_column(sa.Column("auto_start_timer", sa.Boolean(), nullable=False, server_default=sa.false()))
   ```
   Практичнее включить `render_as_batch=True` в `context.configure(...)` в `backend/alembic/env.py` (сейчас не включено), тогда autogenerate сам обернёт операции.
5. Порядок для нового NOT NULL: `add_column(nullable=True)` → backfill (`op.execute`/`op.get_bind`) → `alter_column(nullable=False)`; либо `server_default` + последующее снятие default. Пример антипаттерна — `bed2ce42ab1b` и `38bb310f4d87`: `ADD COLUMN ... NOT NULL` без default. На непустой таблице SQLite это отвергает; на пустой может пропустить, поэтому результат зависит от данных.
6. Проверить на копии рабочей БД, не на `data/hackathon.db`:
   ```powershell
   Copy-Item data\hackathon.db $env:TEMP\check.db
   $env:DATABASE_URL = "sqlite:///$($env:TEMP -replace '\\','/')/check.db"
   Set-Location backend
   ..\.venv\Scripts\python.exe -m alembic upgrade head
   ..\.venv\Scripts\python.exe -m alembic downgrade -1
   ..\.venv\Scripts\python.exe -m alembic upgrade head
   ..\.venv\Scripts\python.exe -m alembic check
   ```
7. Прогнать `python -m pytest` (84 теста). Помнить: тесты создают схему через `create_all` и миграции не проверяют, поэтому отдельно нужен прогон upgrade/downgrade.
8. Учесть запуск: `app.main.lifespan` вызывает `run_migrations()` при каждом старте; неудачная миграция роняет старт приложения. Downgrade-функции есть у всех ревизий, но `foreign_keys` в миграционном engine выключен (см. 2), поэтому порядок drop-таблиц в downgrade не защищён FK.

Подробный рабочий процесс, тесты и отладка — в [docs/08-development-guide.md](../docs/08-development-guide.md); эксплуатация и восстановление — в [docs/09-operations-runbook.md](../docs/09-operations-runbook.md).

## 9. Расхождения и ограничения

### 9.1. С прежней версией specifications/02-data-model.md

| Прежняя формулировка | Фактически |
| --- | --- |
| `AiPrompt/Recommendation`: шаблон, контекст, provider/model | Таблицы `AiPrompt` нет. Есть `ai_settings` (один `prompt`, `priority_provider`, `triggers`, `interval_minutes`) и `ai_recommendations` (`provider`, `trigger`, `summary`, `content`, `excluded`); контекст не хранится |
| `TaskTimer`: started/paused/stopped timestamps | Одна строка `task_timers` на задачу: `state`, `accumulated_seconds`, `last_started_at`; интервалы — в `timer_segments` (`started_at`/`ended_at`). Параллельные таймеры разных задач разрешены, у задачи таймер общий |
| `TaskDependency`: task, predecessor | Добавлен `link_type` (`blocked_by`/`after`/`before`), ревизия `bed2ce42ab1b` |
| `BoardColumn`: project, key, title, position | Добавлены `auto_start_timer`, `auto_stop_timer` (ревизия `38bb310f4d87`, в живой БД ещё нет) |
| `Notification`: delivery/read state | Только `read_at`; статуса доставки/Telegram нет, `project_id`/`user_id` nullable |
| `BackupRecord`: path, checksum, status | Поля `path`, `checksum`, `size_bytes`, `kind`, `created_at`; статуса нет. `path` — имя файла, не абсолютный путь |
| Не были перечислены `sessions`, `login_events`, `ip_rules`, `ai_settings`, `timer_segments`, `checklist_items`, `completion_votes`, `sandbox_runs` | Все 8 таблиц существуют и используются |
| «У проекта всегда есть активный администратор» | Не инвариант БД; только проверки `LAST_ADMIN` в `deactivate`/`revoke_role`. Bootstrap создаёт admin только в пустой БД |
| «У задачи максимум один активный таймер» | Обеспечено UQ `task_timers.task_id`; «активный» = состояние `running`, но незакрытых сегментов может быть несколько при прямой записи |
| «Если есть исполнители, ровно один основной» | Только API (`set_assignees`); БД допускает 0 или несколько `is_primary` |
| «Завершённый проект запрещает изменение рабочих сущностей, таймеры, бэкапы и ИИ-задачи» | Таймеры и часть задач блокируются; `PATCH` задачи, чек-лист, колонки, модули, документы, ИИ и бэкапы — нет |
| «В БД UTC; дедлайны и экранные расчёты — Europe/Moscow» | В БД наивное UTC; backend не конвертирует в MSK. `deadline_msk` хранит UTC, конвертация — только на клиенте (если есть) |
| «При аварийном простое таймер продолжается, система сверяет и исправляет» | Таймер продолжается по wall clock (`last_started_at`), но сверки и корректировки записей после простоя нет |
| «Зависимость даёт предупреждение, а не запрет» | Ни предупреждения, ни запрета: зависимости не влияют на `move` |
| «Блокировка документа истекает через 5 минут» | Так и есть: ленивая проверка в `active_lock` + `jobs.cleanup_locks` каждые 60 с |
| «Trashed — колонка, не удаление» | Так и есть; DELETE задачи вообще отсутствует |

### 9.2. С docs/02-functional-requirements.md

| Требование | Фактически |
| --- | --- |
| «Стартовый процесс настраивается капитаном» | Колонки создаёт/правит любой участник (`require_member`), стартовые защищены только от удаления; `key` неизменяем |
| «Любой участник создаёт, назначает, редактирует, перемещает задачи» | Да, но роль берётся глобально: участник проекта A может менять задачи проекта B, если у него есть любая роль |
| «Незавершённая зависимость предупреждает» | Нет ни предупреждения, ни проверки при перемещении; `link_type` не интерпретируется |
| «Просрочка создаёт риск и уведомление» | Риск на дашборде/аналитике есть; уведомление `task_overdue` создаёт планировщик (60 с) или ручной `/admin/jobs/run`, с дедупом по задаче |
| «ИИ получает задачи, сроки, статусы, блокеры, историю инцидентов, прошлые рекомендации, навыки» | `build_snapshot` отдаёт только имя проекта, дедлайн,总数 задач/выполненных, titles просроченных и активные инциденты; навыков, документов и прошлых рекомендаций нет. Ответ — mock |
| «Периодический запуск, события, ручная кнопка» | Только `POST /ai/run`; `triggers` хранятся, но планировщик их не исполняет; rate limit — in-memory и только для не-`manual` |
| «Повтор через 5/10 минут, затем второй провайдер» | Не реализовано; один mock-вызов, без ретраев и второго провайдера |
| «Краткое уведомление в Telegram о рекомендации» | Не создаётся ни `Notification`, ни отправка; Telegram-клиент только логирует |
| «Порог критического дедлайна настраивается» | Поля нет |
| «Предустановленные промпты, настройка капитаном/админом» | Один `DEFAULT_PROMPT` в коде; шаблонов и отдельной таблицы нет. `GET` настроек доступен любому аутентифицированному и создаёт строку при чтении |
| «Рекомендация общая для команды, сохраняется в истории» | Сохраняется в `ai_recommendations`; общего канала/уведомления нет |
| UI документов | Экран, редактор и предпросмотр исключены из продукта; файлы и существующий API сохраняются |
| «Вложения, диаграммы, UML» | Только Markdown и изображения; изображения вне БД, без метаданных |
| «История версий не обязательна» | Отсутствует полностью |
| «Журнал доступен всем; исходная запись неизменяемо доступна» | Чтение — любому аутентифицированному; админ перезаписывает 3 поля, исходное значение только в `audit_revisions`; причины правки нет |
| «Telegram-уведомления в один общий чат, упоминания» | Заглушка: `integrations/telegram.py` пишет в лог, реальной отправки нет |
| «Светофоры участников и модулей независимы» | Светофор вычисляется из инцидентов (`traffic_status`); `modules.traffic_status` — мёртвая колонка, всегда `green` |
| «Несколько активных инцидентов — показывать самый тяжёлый» | Да: подтверждённый красный приоритетнее жёлтого; неподтверждённый красный не окрашивает (тест `test_unconfirmed_red_does_not_color`) |
| «Красный не запрещает работу» | Да, технических запретов нет |
| «Завершение проекта голосованием капитанов» | Голосуют и капитаны, и администраторы, глобально по всем проектам; достаточно единогласия; `reopen` возвращает `preparation`, не `active` |
| «Полный архив содержит задачи, участников, документы, таймеры, инциденты, историю рекомендаций и журнал» | Zip содержит всю БД и каталог документов, то есть перечисленное; env-секреты не входят, но bcrypt-хеши паролей — в БД |
| «Одна последняя локальная копия» | `latest.zip` + последний обычный архив; safety-копии накапливаются, `backup_records` не чистятся |

### 9.3. Ограничения схемы, миграций и живых данных

| Проблема | Детали |
| --- | --- |
| Head-миграция | Исправлено 2026-10-27: `38bb310f4d87` задаёт `server_default=false`; заполненная рабочая БД успешно обновлена до head, backend запускается |
| NOT NULL без default в старой миграции | `bed2ce42ab1b` (`task_dependencies.link_type`) требует отдельной проверки на более старой заполненной базе; текущая база уже содержала эту ревизию |
| Нет batch-режима | `alembic/env.py` не задаёт `render_as_batch=True`; будущие ALTER/DROP/constraint на SQLite потребуют ручного `batch_alter_table` |
| Проверка FK в миграциях | Отдельный engine в `env.py` не включает `PRAGMA foreign_keys`; DDL и downgrade идут без FK-проверок |
| `stamp_head()` после restore | Восстановленная БД помечается head без сверки схемы; старый бэкап может не соответствовать моделям |
| Повторная выдача роли | См. 6.3: `IntegrityError` для проектной роли после отзыва |
| Опечатка в аудите | `api/operations.py` формирует `project.{action}d`; для `reopen` получается `project.reopend` |
| Светофор модуля | `/modules` отдаёт статический `modules.traffic_status` (`green`), `/analytics` — вычисленный; значения расходятся |
| Пути документов | `services/documents.resolve_path` проверяет `startswith(str(root))` без разделителя: `../10/x.md` из проекта 1 проходит и пишет в каталог проекта 10 |
| Доступ к документам/инцидентам/ИИ | Большинство эндпоинтов используют `get_current_user` без `require_member`: любой аутентифицированный может читать документы и инциденты любого проекта, комментировать инциденты и запускать ИИ (если включён) |
| `deadline_msk` | Имя обещает MSK, хранится наивный UTC; при вводе наивного времени без tz оно трактуется как UTC |
| Дубли `Notification` | Дедуп только для `task_overdue` по `payload.task_id`; остальные типы могут дублироваться |
| Отсутствие FK у целей инцидента | Удаление модуля/задачи/пользователя оставляет `incident_targets` с несуществующим `target_id`; светофор для удалённой цели больше не запрашивается, но данные «висят» |
| Размеры и типы файлов | Лимитов нет; SVG разрешён и отдаётся как файл с того же origin |
| Нет DELETE задач/проектов/пользователей | Удаление задач — только перевод в `trashed`; пользователи деактивируются; проекты не удаляются |
| Фоновые задачи в одном потоке | Планировщик — daemon-thread в процессе; при нескольких workers несколько планировщиков создадут дубли бэкапов и уведомлений |

### 9.4. Не реализовано (не описывать как готовое)

UI журнала аудита, WebSocket/real-time, реальная отправка в Telegram (только лог), реальные Gemini/DeepSeek (mock), Google Drive, fxTunnel, Autoheal/Uptime Kuma, ИИ по расписанию и событийные триггеры, повторные попытки и второй провайдер, экспорт/клон проекта, CSRF-токены, размерные лимиты загрузок, версионирование документов, очистка сессий/аудита/старых записей бэкапов, сверка таймеров после простоя, предупреждения о зависимостях, привязка прав к проекту.

## 10. Сущность → API/сервис → тесты

| Сущность | API-модуль | Сервис/логика | Тесты |
| --- | --- | --- | --- |
| `users` | `api/admin.py`, `api/auth.py` | `services/auth_service.py`, `security.py`, `services/bootstrap.py` | `test_admin.py`, `test_auth.py`, `test_integration.py` |
| `projects` | `api/projects.py`, `api/operations.py` | `services/bootstrap.py`, `services/sandbox.py` | `test_analytics.py`, `test_operations.py`, `test_integration.py`, `test_board.py` |
| `role_assignments` | `api/admin.py`, `deps.py` | `services/bootstrap.py` | `test_admin.py`, `test_auth.py`, `test_analytics.py` |
| `sessions` | `api/auth.py`, `deps.py` | `services/auth_service.py` | `test_auth.py`, `test_admin.py` |
| `login_events` | `api/admin.py` | `services/auth_service.py` | `test_auth.py`, `test_admin.py` |
| `ip_rules` | `api/admin.py` | `services/auth_service.py` | `test_auth.py`, `test_admin.py` |
| `audit_entries` | `api/audit.py`, `api/admin.py` | `services/audit.py` | `test_audit.py`, `test_admin.py`, `test_analytics.py` |
| `audit_revisions` | `api/audit.py`, `api/admin.py` | `services/audit.py` | `test_admin.py` |
| `board_columns` | `api/projects.py` | `services/board.py` | `test_board.py`, `test_analytics.py` |
| `modules` | `api/projects.py` | — | `test_board.py`, `test_analytics.py` |
| `tasks` | `api/tasks.py` | `services/tasks.py` | `test_tasks.py`, `test_dashboard.py`, `test_analytics.py`, `test_integration.py` |
| `task_assignees` | `api/tasks.py` | `services/tasks.py` | `test_tasks.py`, `test_notifications.py` |
| `task_dependencies` | `api/tasks.py` | `services/tasks.py` | `test_tasks.py` |
| `checklist_items` | `api/tasks.py` | — | `test_tasks.py` |
| `task_timers` | `api/timers.py`, `api/tasks.py` | `services/timers.py` | `test_timers.py`, `test_board.py`, `test_sandbox.py` |
| `timer_segments` | — | `services/timers.py` | `test_timers.py`, `test_dashboard.py`, `test_analytics.py` |
| `incidents` | `api/incidents.py` | `services/incidents.py` | `test_incidents.py`, `test_notifications.py`, `test_integration.py`, `test_sandbox.py` |
| `incident_targets` | `api/incidents.py` | `services/incidents.py` | `test_incidents.py` |
| `incident_events` | `api/incidents.py` | `services/incidents.py` | `test_incidents.py` |
| `notifications` | `api/notifications.py` | `services/notifications.py`, `services/jobs.py` | `test_notifications.py`, `test_operations.py`, `test_incidents.py` |
| `documents` | `api/documents.py` | `services/documents.py` | `test_documents.py`, `test_integration.py` |
| `document_locks` | `api/documents.py` | `services/documents.py`, `services/jobs.py` | `test_documents.py` |
| `ai_settings` | `api/ai.py` | `services/ai.py` | `test_ai.py`, `test_integration.py` |
| `ai_recommendations` | `api/ai.py` | `services/ai.py` | `test_ai.py` |
| `completion_votes` | `api/operations.py` | — | `test_operations.py`, `test_integration.py` |
| `backup_records` | `api/operations.py` | `services/backup.py` | `test_operations.py`, `test_integration.py` |
| `sandbox_runs` | `api/sandbox.py` | `services/sandbox.py` | `test_sandbox.py` |

Связанные документы: [01-stack-and-layout.md](01-stack-and-layout.md), [03-api.md](03-api.md), [05-jobs-and-integrations.md](05-jobs-and-integrations.md), [06-security-and-tests.md](06-security-and-tests.md), [docs/07-implementation-status.md](../docs/07-implementation-status.md).
