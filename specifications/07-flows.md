# Потоки выполнения (as-built)

Документ описывает фактическое поведение прототипа: триггеры, шаги, записи в БД, проверки и тесты. Стек и структура — в [01-stack-and-layout.md](01-stack-and-layout.md), HTTP-контракт — в [03-api.md](03-api.md).

## Общие правила

- Ошибки API имеют формат `{"error": {"code", "message", "details"}}`; ошибки валидации Pydantic отдают `VALIDATION_ERROR` с `details.errors`. Необработанные исключения дают стандартный 500 без этого конверта.
- Сессия БД создаётся на запрос (`get_db`) и закрывается после ответа. Часть сервисов коммитит внутри себя: `services.auth_service.record_login`/`create_session`, `services.timers.start_timer`/`pause_timer`/`stop_timer`/`adjust_time`. Поэтому бизнес-операция не всегда атомарна.
- Все даты в БД — наивный UTC (`timeutil.utcnow`). Входные `deadline`/`deadline_msk` с часовым поясом приводятся к UTC; ответы отдают ISO без суффикса, frontend добавляет `Z` при разборе.
- Аутентификация — cookie `session` (HttpOnly, SameSite=Lax, 7 дней). CSRF-токенов нет. Часть эндпоинтов требует только `get_current_user`, часть — роль (`require_member`, `require_captain_or_admin`, `require_admin`). Проверки ролей не фильтруют `project_id`: роль в любом проекте даёт доступ к любому проекту.
- Состояние проекта блокирует запись только при `completed` и только в перечисленных ниже эндпоинтах. `preparation` и `active` на запись не влияют; штатный проект создаётся в `preparation` и никогда не переводится в `active` (в `active` создаётся только проект песочницы).
- Frontend не имеет роутера и глобального store. Текущий проект хранится в `localStorage` (`hcc-project`, по умолчанию 1). Обновление данных — polling, без WebSocket.

## Сводка потоков

| № | Поток | Вход | Основной код | Тесты |
| --- | --- | --- | --- | --- |
| 1 | Первый запуск и bootstrap | старт uvicorn | `main.lifespan`, `services.bootstrap` | `conftest.client`, `test_board`, `test_auth::test_health` |
| 2 | Вход и сессия | `POST /api/v1/auth/login` | `api.auth`, `services.auth_service`, `deps` | `test_auth` (9) |
| 3 | Загрузка доски и опрос | открытие вкладки «Доска» | `Board.tsx`, `api.tasks/columns/dashboard` | `test_board`, `test_tasks`, `test_dashboard` |
| 4 | Создание задачи с исполнителями | форма «+ Задача» | `api.tasks.create_task`, `set_assignees` | `test_tasks` (10) |
| 5 | Перемещение задачи | drag-and-drop / select | `api.tasks.move_task`, `services.timers` | `test_tasks`, `test_board`, `test_integration` |
| 6 | Таймер | start/pause/stop/adjust | `api.timers`, `services.timers` | `test_timers` (8) |
| 7 | Жёлтый инцидент | «+ Инцидент» | `api.incidents`, `services.incidents` | `test_incidents` |
| 8 | Красный инцидент и светофор | «+ Инцидент», confirm/resolve | `api.incidents`, `services.incidents.traffic_status` | `test_incidents` (7) |
| 9 | Рассылка уведомлений | события задач/инцидентов | `services.notifications`, `integrations.telegram` | `test_notifications` (4) |
| 10 | Документы | API вручную (UI нет) | `api.documents`, `services.documents` | `test_documents` (4) |
| 11 | ИИ-рекомендация | настройки/запуск | `api.ai`, `services.ai` | `test_ai` (6) |
| 12 | Бэкап и восстановление | админ/капитан, планировщик | `services.backup`, `api.operations` | `test_operations` |
| 13 | Завершение/открытие проекта | голосование | `api.operations.completion_vote` | `test_operations` |
| 14 | Песочница | админ-вкладка | `api.sandbox`, `services.sandbox` | `test_sandbox` (2) |
| 15 | Фоновая проверка просрочек | поток планировщика | `main._scheduler_loop`, `services.jobs` | `test_operations::test_jobs_overdue_notification` |

## 1. Первый запуск и bootstrap

**Триггер.** Запуск процесса `uvicorn app.main:app` (напрямую, скриптом или в контейнере).

**Схема:** uvicorn → `create_app()` → `lifespan` → `run_migrations()` (Alembic `upgrade head`) → `SessionLocal()` → `bootstrap()` → запуск daemon-потока планировщика → приём запросов.

**Шаги.**

1. Импорт `app.config` создаёт `Settings`; импорт `app.db.session` создаёт каталог `settings.data_dir` и engine (для SQLite — `check_same_thread=False`, `timeout=30`, WAL и `foreign_keys=ON` на каждом соединении).
2. `lifespan` вызывает `run_migrations()`: `Config("backend/alembic.ini")`, абсолютный `script_location`, `command.upgrade(cfg, "head")`.
3. Открывается сессия, вызывается `bootstrap(db)`.
4. Если в `users` уже есть хотя бы одна запись, bootstrap возвращает `None` и ничего не создаёт. Проверяется наличие любого пользователя, а не администратора.
5. Иначе создаётся `User` (`login`/`password_hash`/`display_name` из `APP_FIRST_ADMIN_*`, `active=True`, bcrypt-хеш).
6. Создаётся `Project(name="Hackathon", state=preparation)`.
7. `create_default_columns` вставляет 9 колонок в порядке `backlog`, `todo`, `specification_review`, `in_progress`, `testing`, `review`, `done`, `realised`, `trashed`; флаги автотаймера по умолчанию `False`.
8. Создаётся `RoleAssignment(admin, project_id=None, granted_by=admin.id)`.
9. Пишется `audit_entries` с `action=bootstrap.admin_created`, `data={login, project_id}`.
10. Выполняется `commit`; затем стартует поток `_scheduler_loop` (раздел 15) и приложение начинает принимать запросы.

**Записи в БД.** `users` — 1; `projects` — 1; `board_columns` — 9; `role_assignments` — 1; `audit_entries` — 1; служебная `alembic_version` — head. При повторном старте записей не добавляется.

**Проверки и ошибки.**

| Ситуация | Результат |
| --- | --- |
| Миграция не применилась | исключение в `lifespan`, процесс не доходит до приёма запросов |
| Пользователи уже есть | bootstrap no-op; отсутствие администратора или проекта не лечится |
| `.env` отсутствует | дефолты `admin` / `change-me`, данные в корневой `data/` |
| Пароль по умолчанию | политики паролей и принудительной смены нет |

**Тесты.** Отдельного теста bootstrap нет; фикстура `conftest.client` вызывает `bootstrap()` перед каждым тестом. Порядок колонок проверяет `test_board.py::test_default_columns_order`, доступность `/health` — `test_auth.py::test_health`.

**Особенность текущего рабочего каталога.** `data/hackathon.db` имеет `alembic_version = bed2ce42ab1b`, а в `board_columns` отсутствуют `auto_start_timer`/`auto_stop_timer`. При старте с этим файлом `run_migrations()` пытается применить `38bb310f4d87` и падает: `Cannot add a NOT NULL column with default value NULL` (таблица непустая). На пустой БД цепочка проходит. Подробнее — [01-stack-and-layout.md](01-stack-and-layout.md), раздел 7.

## 2. Вход и сессия

**Триггер.** Отправка формы входа (`App.tsx: Login`) или прямой `POST /api/v1/auth/login` с `{login, password}`.

**Схема:** browser → `POST /auth/login` → `auth_service.authenticate` → `login_events` (commit) → `sessions` (commit) → `Set-Cookie: session` → UI `GET /auth/me` → `get_current_user`.

**Шаги.**

1. IP берётся из `request.client.host`, User-Agent — из заголовка.
2. `is_ip_blocked`: при наличии `ip_rules.action="block"` для этого IP пишется неуспешный `login_events` и возвращается 403 `IP_BLOCKED`.
3. `failure_counts` считает неуспешные входы за 15 минут по этому IP и по этому логину. При `>=10` по IP или `>=5` по логину — 429 `RATE_LIMITED` (тоже с записью события).
4. Пользователь ищется по точному логину; пароль проверяется `bcrypt.checkpw`. Неизвестный логин и неверный пароль неразличимы: 401 `BAD_CREDENTIALS`.
5. Неактивный пользователь после верного пароля получает 403 `DEACTIVATED`.
6. Успешный вход фиксируется в `login_events` (`success=True`) отдельным коммитом.
7. Создаётся сессия: `secrets.token_urlsafe(32)`, в БД — только sha256, `expires_at = now + 7 дней`, IP и User-Agent.
8. Cookie `session`: HttpOnly, SameSite=Lax, `max_age=604800`; флаг `Secure` не ставится, домен/path по умолчанию.
9. Ответ — `UserOut`; UI вызывает `GET /auth/me`, который добавляет к пользователю активные роли.
10. На каждом защищённом запросе `get_current_user` хеширует cookie, ищет неотозванную сессию, проверяет срок и `user.active`.
11. `POST /auth/logout` отзывает сессию по хешу и удаляет cookie. Сброс пароля и деактивация администратором отзывают все сессии пользователя.

**Записи в БД.** `login_events` — на каждую попытку (успешную и нет); `sessions` — на успешный вход; `sessions.revoked_at` — при выходе/сбросе; `ip_rules`, `users`, `role_assignments` — чтение.

**Проверки и ошибки.**

| Код | Условие |
| --- | --- |
| 401 `UNAUTHENTICATED` | нет cookie, сессия не найдена/отозвана/истекла, пользователь удалён |
| 403 `DEACTIVATED` | `users.active=False` |
| 403 `IP_BLOCKED` | IP в `ip_rules` с `action=block` |
| 429 `RATE_LIMITED` | 10 неудач с IP или 5 с логином за 15 минут |
| 401 `BAD_CREDENTIALS` | нет пользователя или неверный bcrypt |

**Тесты.** `test_auth.py` (успех, неверный пароль, неизвестный логин, `/me`, выход, лимит по логину, блокировка IP, `/health`), `test_admin.py` (создание пользователя и вход, сброс пароля, деактивация, сброс IP-лимита).

**Особенности.** Лимит считается по фактам в `login_events`, а не в памяти; администратор сбрасывает его, удаляя неуспешные события по IP. Одновременно можно иметь несколько сессий. Скользящего продления сессии нет. За обратным прокси IP будет адресом прокси: отдельной обработки `X-Forwarded-For` в коде нет.

## 3. Загрузка доски и опрос

**Триггер.** Успешный вход или переключение проекта; вкладка «Доска».

**Схема:** `App` → `GET /auth/me` → `GET /projects` → `Board` → `Promise.all([GET /columns, GET /tasks, GET /dashboard])` → render → `setInterval` 1 с (`tasks` + `dashboard`), 5 с (`incidents`, `analytics`), 10 с (`notifications`).

**Шаги.**

1. `App` загружает `/auth/me`; при 401 показывает форму входа; при успехе — список проектов и уведомления.
2. `Board` монтируется с `key={projectId}`; id проекта берётся из `localStorage` (по умолчанию 1).
3. Первичная загрузка: колонки (сортировка по `position`), все задачи проекта (сортировка по `id`), дашборд. Участники, модули и инциденты загружаются отдельными `useLoad`-запросами один раз.
4. `serialize_task` для каждой задачи добавляет `column_key`, исполнителей, зависимости, чек-лист и таймер (`elapsed` считается на момент ответа).
5. `Board` раскладывает задачи по `column_id`, применяет фильтры (исполнитель, тег, поиск). Блокировки и «затронутые» задачи вычисляются на клиенте по активным инцидентам и зависимостям.
6. Каждую секунду повторяются `GET /tasks` и `GET /dashboard`; ошибки опроса молча игнорируются. Колонки после первичной загрузки не опрашиваются.
7. `Incidents` и `Analytics` обновляются каждые 5 секунд, счётчик уведомлений — каждые 10 секунд.
8. После действий (перемещение, таймер, назначение) `Board` вызывает `reload()` — снова колонки, задачи, дашборд.

**Записи в БД.** Нет, только чтение. Запрос задач делает отдельные выборки на каждую задачу (исполнители, зависимости, чек-лист, таймер) — N+1.

**Проверки и ошибки.** 401 без сессии; 403 без роли-участника; 404 для несуществующего проекта в дашборде; ошибки первичной загрузки показываются баннером, ошибки polling — нет.

**Тесты.** `test_board.py::test_default_columns_order`, `test_tasks.py::test_task_filters`, `test_dashboard.py` (пустой проект, прогресс, просрочка). Frontend-тестов нет.

**Особенности.** WebSocket отсутствует. Изменения колонок в другой вкладке не подхватываются до перезагрузки. UI подсвечивает карточку как заблокированную при любом неразрешённом инциденте с целью `task`, включая неподтверждённый красный, хотя светофор остаётся зелёным (раздел 8).

## 4. Создание задачи с исполнителями

**Триггер.** Кнопка «+ Задача» → отправка формы `TaskForm` в `Board.tsx`.

**Схема:** форма → `POST /projects/{id}/tasks` → `create_task` → `tasks` + `audit_entries` (commit) → ответ с `id` → `PUT /tasks/{id}/assignees` → `task_assignees` + `notifications` + лог Telegram (commit) → `reload()`.

**Шаги.**

1. UI собирает `title`, `description`, `priority` (по умолчанию `medium`), `module_id`, `estimate_seconds` из строки `ч:мм` (неверный формат даёт `null`), `deadline` из `datetime-local` в ISO, `tags` через запятую, `column_key` (по умолчанию `backlog`) и отмеченных исполнителей.
2. `POST /api/v1/projects/{id}/tasks` требует роль участника (любую), затем `ensure_project_active`.
3. `get_column_by_key` ищет колонку проекта: нет — 404 `COLUMN_NOT_FOUND`.
4. Проверяются `module_id` (модуль должен принадлежать проекту) и `parent_id` (родитель должен принадлежать проекту); иначе 422 `VALIDATION_ERROR`.
5. Создаётся `Task` с `version=1`, `deadline` приводится к наивному UTC, `tags` — JSON-список; `flush()`.
6. Пишется `audit_entries(action="task.created")`, выполняется `commit()`; ответ содержит `timer=null`, пустые `assignees`/`predecessors`/`checklist`.
7. Если исполнители выбраны, UI отдельным запросом вызывает `PUT /tasks/{id}/assignees`.
8. Сервер проверяет: если список непуст, ровно один `is_primary` (иначе 422); все `user_id` существуют (иначе 422). Принадлежность исполнителя проекту и его активность не проверяются.
9. Старые `task_assignees` удаляются, новые вставляются, `version++`, пишется аудит `task.assignees_set`.
10. Каждому исполнителю создаётся `notifications(type="task_assigned", payload={task_id,title})`; `telegram_client.send` вызывается с упоминаниями `@username`. Выполняется общий `commit`.
11. UI закрывает форму и перезагружает доску. Автостарт таймера при создании не срабатывает, даже если колонка имеет `auto_start_timer`.

**Записи в БД.** `tasks` (1), `audit_entries` (`task.created`, затем `task.assignees_set`), `task_assignees` (N), `notifications` (N, тип `task_assigned`).

**Проверки и ошибки.** 409 `PROJECT_COMPLETED`; 404 `COLUMN_NOT_FOUND`; 422 `VALIDATION_ERROR` для модуля/родителя/основного исполнителя/несуществующего пользователя; 401/403 при отсутствии сессии/роли.

**Тесты.** `test_tasks.py::test_create_task_default_backlog`, `test_participant_can_create_task`, `test_set_assignees`, `test_assignees_require_one_primary`; `test_integration.py::test_full_cycle`.

**Особенности.** Создание и назначение — два запроса без общей транзакции: при ошибке второго задача остаётся без исполнителей. Основной исполнитель — первый отмеченный в UI. API не принимает исполнителей в теле создания. Автостарт таймера применяется только к перемещению.

## 5. Перемещение задачи (version, автотаймер)

**Триггер.** Drag-and-drop карточки или смена колонки в панели задачи.

**Схема:** UI `handleDrop` → проверка зависимостей на клиенте → `POST /tasks/{id}/move {column_key, version}` → `_check_version` → `tasks.column_id` → аудит → правило колонки → `task_timers`/`timer_segments` → commit.

**Шаги.**

1. UI не отправляет запрос, если колонка не изменилась. Для колонок `in_progress`, `testing`, `review` проверяет незавершённых предшественников (`blocked_by`/`after`, кроме `done`/`realised`) и спрашивает подтверждение через `window.confirm`. Это только UX: сервер зависимости не блокирует.
2. `POST /api/v1/tasks/{id}/move` ищет задачу (404), вызывает `ensure_project_active` (409 `PROJECT_COMPLETED`), сверяет `version` (409 `VERSION_CONFLICT`).
3. Ищется колонка по ключу в проекте задачи; нет — 404 `COLUMN_NOT_FOUND`.
4. `column_id` заменяется, `version++`, пишется `audit_entries(action="task.moved", data={from_column,to_column,key})`.
5. Если у колонки `auto_start_timer=True` и таймер не `running` — вызывается `start_timer` (создаёт/переводит таймер в `running`, открывает `TimerSegment`, коммитит).
6. Иначе, если `auto_stop_timer=True` и таймер `running` — вызывается `stop_timer` (закрывает сегмент, начисляет секунды, `stopped`, коммитит).
7. Выполняется общий `commit`, задача сериализуется с новым таймером.

**Записи в БД.** `tasks.column_id`/`version`/`updated_at`; `audit_entries`; при срабатывании правила — `task_timers`, `timer_segments`.

**Проверки и ошибки.** 409 `VERSION_CONFLICT`, 409 `PROJECT_COMPLETED`, 404 `NOT_FOUND`, 404 `COLUMN_NOT_FOUND`. Матрицы допустимых переходов нет: в любую колонку из любой.

**Тесты.** `test_tasks.py::test_move_task`, `test_version_conflict`; `test_board.py::test_custom_column_auto_timer`; `test_integration.py::test_full_cycle`.

**Особенности.** Если у колонки включены оба флага, побеждает автостарт. Перемещение в ту же колонку через API всё равно увеличивает версию и может применить правило. `start_timer` коммитит внутри `move_task`, поэтому возможна частично применённая операция при сбое после него.

## 6. Таймер (start/pause/stop, сегменты, корректировка)

**Триггер.** Кнопки «Старт», «Пауза», «Стоп» в панели задачи; поле корректировки у капитана/администратора.

**Схема:** UI → `POST /tasks/{id}/timer/{start|pause|stop}` → `services.timers` → `TaskTimer` + `TimerSegment` (commit) → `TimerOut`; корректировка → `POST /tasks/{id}/time-adjustment` → `adjust_time` → аудит → `TimerOut`.

**Шаги.**

1. `_task` проверяет существование задачи (404) и `ensure_project_active` (409).
2. `start`: если таймер уже `running` — 409 `TIMER_RUNNING`. Иначе создаётся `TaskTimer(state="running", accumulated_seconds=0, last_started_at=now)` либо обновляется существующий; добавляется `TimerSegment(started_at=now)` с открытым `ended_at`; commit.
3. `pause`: если таймера нет или он не `running` — 409 `TIMER_NOT_RUNNING`. Находится открытый сегмент, ему ставится `ended_at`, к `accumulated_seconds` прибавляется `int(now - started_at)`; состояние `paused`, `last_started_at=None`; commit.
4. `stop`: если таймера нет или он `stopped` — 409 `TIMER_NOT_ACTIVE`. Для `running` закрывается открытый сегмент; состояние `stopped`, `last_started_at=None`; commit. Из `paused` просто переводит в `stopped`.
5. Чтение (`serialize_task`, `TimerOut`): `elapsed = now - last_started_at` только для `running`; `total = accumulated + elapsed`. Для `paused`/`stopped` `elapsed=0`.
6. Корректировка: `POST /tasks/{id}/time-adjustment` доступна только капитану/администратору (403 иначе), `accumulated_seconds >= 0`. Если таймера нет, создаётся `stopped` с заданным значением; если есть — значение перезаписывается. Пишется `audit_entries(action="task.time_adjusted")`, commit.
7. Дашборд считает `actual_seconds` как сумму `accumulated + elapsed` по всем задачам, `calendar_seconds` — как объединение интервалов всех `timer_segments` проекта (`merge_intervals`).

**Записи в БД.** `task_timers` (одна запись на задачу, `task_id` уникален), `timer_segments` (открытые/закрытые интервалы), `audit_entries` при корректировке.

**Проверки и ошибки.** 409 `TIMER_RUNNING`, 409 `TIMER_NOT_RUNNING`, 409 `TIMER_NOT_ACTIVE`, 403 `FORBIDDEN` для корректировки участником, 409 `PROJECT_COMPLETED`, 404 `NOT_FOUND`.

**Тесты.** `test_timers.py` (start/pause/stop, двойной старт, пауза без запуска, параллельные таймеры разных задач, корректировка админом и запрет участнику, `merge_intervals`); `test_integration.py::test_full_cycle`.

**Особенности.** Ограничения «один активный таймер на пользователя» нет: параллельно могут идти таймеры разных задач. Корректировка не закрывает активный сегмент: при последующем `stop` длительность открытого сегмента прибавится к заданному значению, поэтому `accumulated_seconds` и сумма сегментов могут разойтись, а `actual_seconds` — с `calendar_seconds`. Автоостановки при завершении задачи или проекта нет.

## 7. Жёлтый инцидент

**Триггер.** Кнопка «+ Инцидент», уровень `yellow`; либо `POST /api/v1/projects/{id}/incidents`.

**Схема:** UI → `POST /projects/{id}/incidents` → `create_incident` → `incidents` + `incident_targets` + `incident_events` → `notify_users` (owner + капитаны) → commit.

**Шаги.**

1. Эндпоинт требует только аутентификацию (`get_current_user`), не роль участника; вызывает `ensure_project_active`.
2. Уровень должен быть `yellow` или `red` (иначе 422); типы целей — `task`, `module`, `user` (иначе 422). Существование целей и их принадлежность проекту не проверяются.
3. `create_incident` вставляет `Incident(status="open", level="yellow", author_id, owner_id, impact, urgency)`, цели и событие `created` с данными уровня/заголовка/ответственного; `flush`.
4. Получатели уведомления: `owner_id` (если задан) и все активные капитаны/администраторы (`captains()`); тип `incident_yellow_created`, payload `{incident_id,title,level}`.
5. Выполняется commit; ответ содержит цели, события и `age_seconds`.
6. Закрытие: `POST /incidents/{id}/resolve` с непустым `resolution`. Только ответственный или капитан/администратор (403 иначе). Если уже `resolved` — 409 `INVALID_STATE`. Статус `resolved`, `resolution`, `resolved_at`, событие `resolved`; уведомление автору и ответственному (тип `incident_resolved`); commit.
7. Комментарий: `POST /incidents/{id}/events` с непустым текстом; добавляет событие `comment` без проверки состояния и без аудита.

**Записи в БД.** `incidents`, `incident_targets` (N), `incident_events` (`created`, затем `resolved`/`comment`), `notifications` (owner + капитаны; при закрытии — автор + owner).

**Проверки и ошибки.** 422 `VALIDATION_ERROR` (уровень, тип цели, пустой текст/решение), 409 `INVALID_STATE`, 403 `FORBIDDEN`, 404 `NOT_FOUND`, 409 `PROJECT_COMPLETED`.

**Тесты.** `test_incidents.py::test_create_yellow_incident`, `test_yellow_resolve_permission`, `test_comment_adds_event`, `test_traffic_status`; `test_notifications.py::test_notification_on_yellow_incident`.

**Особенности.** Автор не может закрыть инцидент, если он не ответственный. Жёлтый инцидент нельзя «подтвердить»: `confirm-red` вернёт 422. Записи в `audit_entries` нет — история только в `incident_events`. Цели не валидируются, поэтому светофор может «покрасить» несуществующий или чужой объект с тем же id.

## 8. Красный инцидент (создание, подтверждение/отклонение, закрытие, светофор)

**Триггер.** Создание инцидента с `level="red"`; затем подтверждение или отклонение капитаном; закрытие после работ.

**Схема:** участник → `POST /projects/{id}/incidents {level:"red"}` → `open` + уведомление капитанов → капитан `POST /incidents/{id}/confirm-red {confirm}` → `confirmed`/`resolved` → `resolve` → `resolved`; `traffic_status` вычисляется при чтении участников/аналитики.

**Шаги.**

1. Создание выполняется тем же `create_incident`, что и жёлтого: статус `open`, событие `created`, цели. Уведомление получают только капитаны/администраторы, тип `incident_red_created`.
2. Пока статус `open`, светофор остаётся зелёным (неподтверждённый красный не красит).
3. `POST /incidents/{id}/confirm-red` требует капитана/администратора (403 иначе) и активный проект. `confirm_red` проверяет `level=="red"` (иначе 422) и `status=="open"` (иначе 409 `INVALID_STATE`).
4. `confirm=true`: статус `confirmed`, `confirmed_at`, событие `confirmed`; уведомление всей команде (тип `incident_red_confirmed`). `confirm=false`: статус сразу `resolved`, `resolution = comment` или «Эскалация отклонена», `resolved_at`, событие `rejected`; уведомления нет.
5. Закрытие: `POST /incidents/{id}/resolve`; для красного требует капитана/администратора. Статус `resolved`, решение, событие `resolved`, уведомление автору и ответственному.
6. `traffic_status(target_type, target_id)` ищет все неразрешённые инциденты с этой целью: если есть красный со статусом `confirmed` — `red`; иначе если есть любой неразрешённый жёлтый — `yellow`; иначе `green`.
7. Светофор отдаётся в `GET /projects/{id}/participants` (для `user`) и в `GET /projects/{id}/analytics` (для `module`), а также используется в аналитике. Отдельного эндпоинта светофора нет.

**Записи в БД.** `incidents` (level, status, confirmed_at, resolved_at, resolution), `incident_targets`, `incident_events` (`created`, `confirmed`/`rejected`, `resolved`), `notifications`.

**Проверки и ошибки.** 403 при подтверждении/закрытии не капитаном; 422 при `confirm-red` для жёлтого; 409 при повторной обработке; 422 при неверной цели; 409 `PROJECT_COMPLETED`; 404.

**Тесты.** `test_incidents.py::test_red_escalation_flow`, `test_red_reject_escalation`, `test_unconfirmed_red_does_not_color`, `test_traffic_status`; `test_integration.py::test_full_cycle`.

**Особенности.** Создать красный может любой аутентифицированный пользователь, включая участника без роли в проекте. Подтверждение и закрытие проверяют роль глобально, а не членство в проекте инцидента. Аудита нет. Закрытие не требует, чтобы инцидент был подтверждён. `incidents` без целей не влияют на светофор. Поле `modules.traffic_status` в БД существует, но нигде не обновляется: `GET /modules` возвращает сохранённое значение (обычно `green`), а аналитика считает цвет заново.

## 9. Рассылка уведомлений

**Триггер.** Назначение исполнителей, создание/подтверждение/закрытие инцидента, фоновая проверка просрочек.

**Схема:** доменное событие → `notify_users(...)` → `notifications` (flush) → `telegram_client.send` (лог) → commit вызывающего кода → UI `GET /notifications` каждые 10 с.

**Шаги.**

1. Вызывающий код передаёт `project_id`, список `user_ids`, `type`, `payload`, необязательный `telegram_text` и упоминания.
2. `notify_users` дедублирует `user_ids` через `set`, создаёт по `Notification` на пользователя и делает `flush` (не commit).
3. Если передан `telegram_text`, синхронно вызывается `telegram_client.send`. При пустых `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` пишется `[telegram mock]`, иначе `[telegram stub]`; HTTP-запрос не выполняется, функция всегда возвращает `True`.
4. Commit выполняет вызывающий эндпоинт; при его отсутствии уведомления откатятся.
5. UI получает только свои уведомления (`GET /api/v1/notifications`, опционально `unread_only`, `limit`), отмечает одно/все прочитанными, удаляет одно или очищает все.
6. Чтение/удаление чужого уведомления даёт 404.

**Записи в БД.** `notifications`: `project_id`, `user_id`, `type`, `payload` (JSON), `read_at`, `created_at`. `read_at` обновляется при отметке.

| Событие | Получатели | Тип | Payload |
| --- | --- | --- | --- |
| Назначение задачи | все назначенные | `task_assigned` | `task_id`, `title` |
| Жёлтый инцидент создан | owner + капитаны/админы | `incident_yellow_created` | `incident_id`, `title`, `level` |
| Красный создан | капитаны/админы | `incident_red_created` | `incident_id`, `title`, `level` |
| Красный подтверждён | вся команда | `incident_red_confirmed` | `incident_id`, `title` |
| Инцидент закрыт | автор + owner | `incident_resolved` | `incident_id`, `title`, `resolution` |
| Просрочка задачи | вся команда | `task_overdue` | `task_id`, `title` |

**Проверки и ошибки.** 401 без сессии; 404 при доступе к чужому уведомлению. Отдельной проверки членства в проекте нет.

**Тесты.** `test_notifications.py` (жёлтый инцидент, назначение, отметка прочтения, требование авторизации); `test_operations.py::test_jobs_overdue_notification`.

**Особенности.** `captains()` и `team()` возвращают активных пользователей с ролью в любом проекте, без фильтра по `project_id`. Telegram — только лог, повторов и очереди нет. Уведомление о просрочке создаётся один раз на задачу и не зависит от `read_at`; после снятия и повторного наступления просрочки второго уведомления не будет.

## 10. Документы (создание, сохранение с checksum, блокировка, heartbeat, корзина)

**Триггер.** Прямые вызовы API; экрана документов в UI нет.

**Схема:** `POST /projects/{id}/documents` → файл на диск + `documents`; `PUT /documents/{id}/content` → сверка checksum → файл + checksum; `POST /lock` → `document_locks`; `POST /heartbeat` → TTL; `DELETE` → `trashed=true`.

**Шаги.**

1. Создание: `POST /api/v1/projects/{id}/documents` с `{path, content}`. Требуется только аутентификация; состояние проекта не проверяется.
2. `path` обрезается по пробелам и крайним `/`; расширение должно быть `.md` или `.markdown` (иначе 422). Дубликат `(project_id, path)` — 409 `DOCUMENT_EXISTS`.
3. Файл пишется в `data/documents/<project_id>/<path>` (родительские каталоги создаются), затем считается sha256 и вставляется `Document` с `author_id`, `checksum`, `trashed=false`. Commit.
4. Чтение: список без корзины, отдельный список корзины, метаданные, содержимое (`read_file`).
5. Сохранение: `PUT /documents/{id}/content` с `{content, base_checksum}`. Если `base_checksum != documents.checksum` — 409 `VERSION_CONFLICT`. Иначе файл перезаписывается, checksum и `updated_at` обновляются, commit. Блокировка и состояние проекта не проверяются.
6. Блокировка: `POST /documents/{id}/lock`. `active_lock` возвращает блокировку, если с `last_activity_at` прошло меньше 5 минут; истёкшая удаляется. Чужая активная блокировка — 409 `DOCUMENT_LOCKED`; своя обновляется.
7. Heartbeat: `POST /documents/{id}/heartbeat` обновляет `last_activity_at` только если блокировка принадлежит текущему пользователю; иначе молча 200 без изменений.
8. Снятие: `DELETE /documents/{id}/lock` удаляет блокировку только владельца; чужая — молча 200.
9. Корзина: `DELETE /documents/{id}` ставит `trashed=true` (файл остаётся); `POST /documents/{id}/restore` снимает флаг. Оба действия без проверки владельца/роли.
10. Изображения: `POST /projects/{id}/documents/images` принимает multipart, проверяет расширение (`png/jpg/jpeg/gif/webp/svg`), пишет `assets/<uuid>.<ext>`; `GET .../images/{filename}` отдаёт файл. Лимита размера нет, содержимое читается целиком в память.

**Записи в БД.** `documents` (path, author_id, checksum, trashed, created_at, updated_at), `document_locks` (document_id уникален, user_id, acquired_at, last_activity_at). Содержимое — только в файлах.

**Проверки и ошибки.** 422 `VALIDATION_ERROR` (не Markdown, плохой путь, формат изображения), 409 `DOCUMENT_EXISTS`, 409 `VERSION_CONFLICT`, 409 `DOCUMENT_LOCKED`, 404 `NOT_FOUND`.

**Тесты.** `test_documents.py::test_document_crud`, `test_document_reject_non_markdown`, `test_document_lock_flow`, `test_document_lock_conflict`.

**Особенности.** Блокировка не является обязательной для сохранения: `save_content` проверяет только checksum. `resolve_path` сравнивает строковый префикс без разделителя, поэтому путь вида `../10/...` из проекта 1 может пройти проверку и попасть в каталог проекта 10. Нет проверки роли участника и состояния проекта. Корзина не удаляет файл; `delete_file` в сервисе не вызывается. TTL блокировки 5 минут, дополнительно её чистит фоновый job. UI документов и аудита отсутствует.

## 11. ИИ-рекомендация (включение, запуск, rate limit, исключение)

**Триггер.** Вкладка «Настройки» → блок ИИ; либо прямые вызовы `/ai/*`.

**Схема:** `GET /ai/settings` (создаёт дефолт в сессии) → `PATCH /ai/settings {enabled:true}` (капитан) → `POST /ai/run {trigger}` → проверка enabled и rate limit → снимок проекта → mock-рекомендация → `ai_recommendations` (commit) → список/исключение.

**Шаги.**

1. `get_settings` ищет `ai_settings` проекта; если нет — создаёт `enabled=false`, `priority_provider="gemini"`, `prompt=DEFAULT_PROMPT`, `interval_minutes=30`, `triggers` из пяти флагов (`red_confirmed`, `blocker_created`, `blocker_closed`, `overdue`, `deadline_6h`) и делает `flush`. `GET` не коммитит, поэтому на новом проекте строка исчезнет при закрытии сессии; постоянной она становится после `PATCH` или `run`.
2. `PATCH /projects/{id}/ai/settings` доступен капитану/администратору; обновляет переданные поля (`interval_minutes` 5–1440), commit.
3. `POST /projects/{id}/ai/run` доступен любому аутентифицированному. Если `enabled=false` — 409 `AI_DISABLED`.
4. Для `trigger != "manual"` проверяется in-memory лимит: если с прошлого запуска проекта прошло меньше `interval_minutes` — 429 `RATE_LIMITED`. Ручной запуск не лимитируется.
5. `mark_run` записывает время в память процесса (в БД не сохраняется).
6. `build_snapshot` собирает имя проекта, дедлайн, число задач, число завершённых (`done`/`realised`), просроченные незавершённые задачи и активные инциденты.
7. `_mock_recommendation` выбирает ветку: активные инциденты → просрочки → «по плану»; формирует `summary` и `content` с причиной/риском/действием. Внешних API нет, ключи не используются.
8. Создаётся `AiRecommendation(provider=settings.priority_provider, trigger, summary, content, excluded=false)`; commit в эндпоинте.
9. Список рекомендаций — до 200 последних; `POST .../recommendations/{id}/exclude` (капитан/администратор) переключает `excluded`.

**Записи в БД.** `ai_settings` (создание/обновление), `ai_recommendations` (provider, trigger, summary, content, excluded).

**Проверки и ошибки.** 409 `AI_DISABLED`, 429 `RATE_LIMITED`, 403 на `PATCH`/`exclude` без роли, 404 на чужую рекомендацию.

**Тесты.** `test_ai.py` (по умолчанию выключен, запуск требует включения, mock-ответ, права на настройки, rate limit, исключение).

**Особенности.** Rate limit живёт в памяти процесса, сбрасывается при перезапуске и не общий для нескольких воркеров. `trigger` не валидируется по списку. Фоновых запусков по событиям нет, несмотря на `triggers`. Реальные Gemini/DeepSeek не подключены; `prompt` в mock не используется. Проверки существования проекта и состояния `completed` нет.

## 12. Бэкап и восстановление

**Триггер.** Кнопка в админке/настройках, `POST /admin/backups`, `POST /admin/backups/{id}/restore`; автоматически — поток планировщика.

**Схема:** `create_backup(kind)` → sqlite backup в `database.sqlite` → копия `documents/` → `manifest.json` → zip → `latest.zip` (кроме safety) → `backup_records`; `restore` → проверка checksum → safety-копия → подмена БД и документов → `stamp_head`.

**Шаги.**

1. Создание доступно капитану/администратору. `create_backup` создаёт каталог `data/backups`, временный каталог и имя `backup_<timestamp>_<kind>.zip`.
2. Снимок БД делается через `sqlite3.Connection.backup` в `tmp/database.sqlite`; копируется `data/documents` (если есть); пишется `manifest.json` с `created_at` и `kind`.
3. Все файлы временного каталога упаковываются в zip (DEFLATE).
4. Для `kind != "safety"` zip копируется в `latest.zip.tmp` и атомарно заменяет `latest.zip`; старые `backup_*.zip` без `_safety` (кроме текущего) удаляются.
5. Считается sha256 zip, в `backup_records` вставляются `path`, `checksum`, `size_bytes`, `kind`; commit. Запись добавляется после снимка БД, поэтому в самом архиве её нет.
6. Автоматический бэкап: поток планировщика вызывает `create_backup(kind="automatic")` при `now - last_backup >= 900`; первый — примерно через 15 минут после старта.
7. Восстановление: `POST /admin/backups/{id}/restore` с `{confirm: true}` (иначе 422 `CONFIRM_REQUIRED`), только капитан/администратор. Запись ищется в `backup_records` (404), файл проверяется на существование (404) и sha256 (409 `BACKUP_CORRUPT`).
8. Перед заменой создаётся `safety`-копия текущего состояния.
9. Архив распаковывается во временный каталог; сессия закрывается, `engine.dispose()`; удаляются `hackathon.db`, `-wal`, `-shm`; копируется `database.sqlite`; каталог `documents` заменяется содержимым архива.
10. Вызывается `stamp_head()`: схема помечается как head без выполнения миграций. API возвращает `{"status":"ok","backup_id":...}`.

**Записи в БД.** `backup_records` (path, checksum, size, kind, created_at). Восстановление заменяет всю БД и каталог документов; `safety`-запись не переживает замену, потому что снимок для неё сделан до вставки записи.

**Проверки и ошибки.** 422 `CONFIRM_REQUIRED`, 404 (запись/файл), 409 `BACKUP_CORRUPT`, 403 без роли. Ошибки файловой системы не преобразуются в доменные коды.

**Тесты.** `test_operations.py::test_backup_and_restore`, `test_restore_requires_confirmation`; `test_integration.py::test_full_cycle`.

**Особенности.** `backup_records` для удалённых старых архивов остаются, поэтому список может содержать записи без файла. `latest.zip` не имеет отдельной записи. `safety`-архивы не удаляются. Восстановление не запускает миграции и не проверяет совместимость схемы: старый архив помечается head, хотя его схема может быть старше кода. Автоматический бэкап при ошибке молча пропускается (исключение глотается в планировщике). Бэкап не включает `.env`, секреты и внешние интеграции; шифрования нет.

## 13. Завершение и повторное открытие проекта

**Триггер.** Блок «Завершение» в настройках: `POST /api/v1/projects/{id}/completion-votes` с `{action: "complete"|"reopen"}`.

**Схема:** капитан → голос `completion_votes` → набор активных капитанов/админов → если все проголосовали, `projects.state=completed` (или `preparation`), голоса удаляются, аудит → часть эндпоинтов отвечает 409 `PROJECT_COMPLETED`.

**Шаги.**

1. Эндпоинт требует капитана/администратора; проект ищется по id (404).
2. Если голоса пользователя за это действие ещё нет, вставляется `CompletionVote(project_id, user_id, action)` и commit. Повторный голос не создаёт дубль.
3. `captain_ids` — все активные пользователи с ролью `captain` или `admin` в любом проекте (глобально). `votes` — множество проголосовавших за это действие в этом проекте.
4. Если `captain_ids` непусто и все они входят в `votes`: состояние `completed` для `complete`, `preparation` для `reopen`; все голоса проекта удаляются; пишется аудит `project.completed` или `project.reopend` (опечатка в коде); commit.
5. Ответ: `{state, votes: <число проголосовавших>, required: <число капитанов>}`; `votes` считается до удаления.
6. После `completed` `ensure_project_active` возвращает 409 в: создании задачи, перемещении, назначении исполнителей, добавлении зависимости, всех операциях таймера, создании/подтверждении/закрытии инцидента.
7. Повторное открытие доступно из любого состояния и переводит проект в `preparation` (не в `active`).

**Записи в БД.** `completion_votes` (project_id, user_id, action; уникальность), `projects.state`, `audit_entries`. При успехе голоса проекта удаляются.

**Проверки и ошибки.** 403 без роли, 404 нет проекта, 409 `PROJECT_COMPLETED` в перечисленных эндпоинтах, 422 при неверном `action` (Pydantic pattern).

**Тесты.** `test_operations.py::test_completion_unanimous_and_readonly`, `test_completion_reopen`; `test_integration.py::test_full_cycle`.

**Особенности.** Порог — все капитаны и администраторы глобально, а не капитаны проекта; администратор также обязан голосовать. Завершение не проверяет открытые задачи/инциденты и не рассылает уведомления. Read-only частичный: `PATCH /tasks/{id}`, чек-лист, удаление зависимости, колонки, модули, документы, ИИ, бэкапы, изменение проекта и повторное голосование остаются доступны. Состояние `active` штатно не выставляется.

## 14. Сценарий песочницы

**Триггер.** Вкладка «Песочница» (только admin) → выбор сценария → `POST /api/v1/admin/sandbox/run {scenario}`.

**Схема:** admin → `GET /admin/sandbox/scenarios` → `POST /run` → `get_sandbox_project` + `get_team` → мутации → `sandbox_runs` (commit) → журнал `GET /admin/sandbox/runs`.

**Шаги.**

1. Роутер `/admin/sandbox` защищён `require_admin`; список сценариев — статический словарь `SCENARIOS` (6 записей).
2. `get_sandbox_project` ищет проект с именем `Sandbox`; если нет — создаёт `Project(state=active)` с 9 колонками и commit.
3. `get_team` создаёт (если нет) пользователей `alice`, `bob` (participant) и `cap` (captain) с паролем `sandbox-pass`; назначает роли на проект песочницы, если их нет; commit.
4. `create_team` — только логирует состав.
5. `simulate_sprint`: останавливает все running-таймеры проекта песочницы (закрывает сегменты, начисляет секунды), создаёт три задачи (`in_progress` с таймером alice, просроченную `todo` bob, `done` cap), создаёт жёлтый инцидент от bob; commit.
6. `overdue_as_dev` — создаёт просроченную задачу alice; `incident_as_dev` — жёлтый инцидент bob; `timer_cycle` — задача и полный цикл start/pause/stop; `integration_failure` — только запись в лог, внешние вызовы не выполняются.
7. При исключении API делает `rollback` и формирует лог ошибки; `record_run` отдельным commit сохраняет `SandboxRun(status="error")`.
8. Успешный запуск сохраняет `SandboxRun(scenario, status="ok", logs, run_by, created_at)`; список последних 100 доступен администратору.

**Записи в БД.** `projects` (Sandbox), `board_columns`, `users` (alice/bob/cap), `role_assignments`, `tasks`, `task_assignees`, `task_timers`, `timer_segments`, `incidents`, `incident_events`, `audit_entries`, `sandbox_runs`.

**Проверки и ошибки.** 403 для не-администратора; неизвестный сценарий возвращает `ok=false` и лог, а не HTTP-ошибку; ошибка выполнения сохраняется в `sandbox_runs`.

**Тесты.** `test_sandbox.py::test_sandbox_scenarios` (прогоняет все сценарии), `test_sandbox_requires_admin`.

**Особенности.** Пароль песочницы фиксирован, сброса и изоляции нет: данные копятся в обычном проекте `Sandbox` и видны в общих списках. Сценарий неатомарен: `timers.start_timer` коммитит внутри, поэтому при сбое часть данных может остаться. Проект ищется по имени, поэтому конфликт с пользовательским проектом `Sandbox` возможен.

## 15. Фоновая проверка просрочек и планировщик

**Триггер.** После bootstrap в `lifespan` запускается daemon-поток `_scheduler_loop`; тик — 60 секунд.

**Схема:** thread → `stop.wait(60)` → `SessionLocal` → `jobs.run_all_jobs` → `cleanup_locks` + `check_overdue` → при `>=900` с `create_backup(automatic)` → close; при остановке `stop.set()`.

**Шаги.**

1. `last_backup` инициализируется текущим временем; цикл ждёт 60 секунд или сигнал остановки.
2. На каждом тике открывается отдельная сессия и вызывается `run_all_jobs`.
3. `cleanup_locks`: удаляются `document_locks` с `last_activity_at < now - 5 минут`; при наличии удалений commit.
4. `check_overdue`: перебираются проекты со статусом не `completed`; для каждого определяются колонки `done`, `realised`, `trashed` и задачи с `deadline < now` вне этих колонок.
5. Для каждого проекта загружаются существующие уведомления типа `task_overdue`; задачи, чьи `task_id` уже есть в payload, пропускаются.
6. По каждой новой просроченной задаче создаются уведомления всей команде (`team()`) с типом `task_overdue` и текстом для Telegram; commit на проект; возвращается число созданных.
7. Если с прошлого бэкапа прошло не менее 900 секунд, вызывается `create_backup(kind="automatic")` и время обновляется.
8. Сессия закрывается; любое исключение глотается (`except Exception: pass`), поток продолжает работу.
9. При завершении приложения выставляется `stop`, но `join` нет: поток может дожить до конца текущего 60-секундного ожидания/тика.

**Записи в БД.** `document_locks` (удаление), `notifications` (`task_overdue`), `backup_records` + файлы бэкапов.

**Проверки и ошибки.** Ошибки не логируются и не видны в API. Ручной запуск — `POST /admin/jobs/run` (капитан/администратор), выполняет те же job'ы без бэкапа.

**Тесты.** `test_operations.py::test_jobs_overdue_notification`. Поток планировщика, очистка блокировок и автоматический бэкап тестами не покрыты.

**Особенности.** Проверка `deadline_6h`, триггеры ИИ и повторные уведомления не реализованы. Уведомление о просрочке создаётся один раз на задачу навсегда. Проекты в `completed` пропускаются. При нескольких воркерах uvicorn каждый процесс запустит свой планировщик; штатный запуск — один процесс.

## Расхождения и ограничения

| # | Наблюдение | Влияние |
| --- | --- | --- |
| 1 | Read-only для `completed` реализован не для всех «рабочих» сущностей | `PATCH /tasks/{id}`, чек-лист, удаление зависимости, колонки, модули, документы, ИИ, бэкапы и изменение проекта остаются доступны |
| 2 | Роли `participant`/`captain` не фильтруются по `project_id` при проверке доступа | роль в любом проекте даёт доступ к задачам, инцидентам, документам и аналитике любого проекта; списки капитанов и команды для уведомлений/завершения тоже глобальные |
| 3 | Часть эндпоинтов требует только `get_current_user`, а не роль участника | пользователь без роли может читать документы/инциденты/аналитику, создавать инциденты, документы и запускать ИИ |
| 4 | Документы: `save_content` не проверяет блокировку; `resolve_path` сравнивает префикс без разделителя | можно сохранить файл, удерживаемый другим, и обойти каталог проекта через `../<id>/...`; лимита размера загрузки нет |
| 5 | `modules.traffic_status` — хранимая колонка, которая никогда не обновляется | `GET /modules` всегда отдаёт `green`, тогда как аналитика считает цвет по инцидентам |
| 6 | UI блокирует карточку при любом неразрешённом инциденте, включая неподтверждённый красный | визуальная блокировка расходится со светофором, который остаётся зелёным до подтверждения |
| 7 | У инцидентов и документов нет записей в `audit_entries`; цели инцидентов не проверяются на существование/проект | журнал не отражает эти действия; светофор может ссылаться на чужой/несуществующий id |
| 8 | Завершение проекта требует голоса всех администраторов и капитанов глобально; reopen переводит в `preparation`, а не `active` | один капитан другого проекта влияет на завершение; состояние `active` штатно недостижимо |
| 9 | `adjust_time` не закрывает активный сегмент, а `calendar_seconds` считается по сегментам | ручная корректировка может завысить `actual_seconds` после stop и расходится с календарём |
| 10 | `backup_records` не удаляются вместе с архивами; `safety`-запись теряется после восстановления; restore делает `stamp head` без миграций | список бэкапов содержит недоступные файлы; восстановление старого архива может оставить несовместимую схему |
| 11 | ИИ: rate limit в памяти, ручной запуск без лимита, `trigger` не валидируется, фоновых триггеров нет | лимит не переживает перезапуск и не работает между воркерами; настройки `triggers` не действуют |
| 12 | Уведомления о просрочке создаются один раз на задачу; получатели — вся команда глобально; Telegram только в лог | повторная просрочка не уведомляется; реальной отправки и повторов нет |
| 13 | Планировщик глотает исключения без логирования, не делает `join`, первый автоматический бэкап — примерно через 15 минут | сбой job'а/бэкапа не виден; при нескольких процессах возможны дубли |
| 14 | Песочница использует фиксированный пароль и постоянный проект `Sandbox`, сценарии неатомарны | данные копятся, сброса нет, возможны частичные изменения после ошибки |
| 15 | Тесты не применяют Alembic, не покрывают frontend и поток планировщика | 84 зелёных теста не гарантируют применимость миграций к непустой БД (текущий `data/hackathon.db` — пример) |

Связанные документы: [01-stack-and-layout.md](01-stack-and-layout.md), [03-api.md](03-api.md), [docs/03-architecture-and-operations.md](../docs/03-architecture-and-operations.md).
