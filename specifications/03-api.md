# 03. HTTP API (as-built)

Дополнение от 28.10.2026: `GET/POST /projects/{project_id}/planning`, версии и `PLANNING_PREVIEW` описаны в [Планировании](../docs/14-planning.md). Общие изменения задач и связей также запускают пересчёт; циклы теперь запрещены.

Документ описывает фактический HTTP-контракт backend: 86 обработчиков под `/api/v1` плюс `GET /health`. Источники: `backend/app/main.py`, `backend/app/api/*.py`, `backend/app/deps.py`, `backend/app/schemas.py`, `backend/app/api/errors.py`, `backend/app/services/*.py`, `frontend/src/api.ts`, `backend/tests/*.py`. Если документ и код расходятся, источником истины считается код; расхождения вынесены в раздел 8.

Смежные документы: [02-data-model.md](02-data-model.md), [04-frontend.md](04-frontend.md), [05-jobs-and-integrations.md](05-jobs-and-integrations.md), [06-security-and-tests.md](06-security-and-tests.md), [известные пробелы](../docs/10-known-gaps-and-roadmap.md), [статус реализации](../docs/07-implementation-status.md).

## 1. Базовые соглашения

### 1.1 Адрес, формат, версия

| Свойство | Фактическое значение |
| --- | --- |
| Базовый URL (локальный запуск) | `http://127.0.0.1:8000` (`APP_HOST=127.0.0.1`, `APP_PORT=8000`) |
| Базовый URL (Docker) | `http://localhost:8000`, порт публикуется как `8000:8000` |
| Префикс API | `/api/v1`; единственное исключение — `GET /health` |
| Формат тела | JSON UTF-8; загрузка изображения — `multipart/form-data` |
| Версия API | одна; согласование версий, заголовки `Accept-Version` и альтернативные префиксы отсутствуют |
| Документация | Swagger UI `/docs`, ReDoc `/redoc`, схема `/openapi.json` |
| Схема безопасности в OpenAPI | не объявлена: cookie читается вручную, кнопка `Authorize` в Swagger не работает |
| Успешное создание | HTTP 200, не 201 |
| Успешное удаление | HTTP 200 и тело `{"status":"ok"}`, не 204 |
| Идентификаторы | целые `int`, автоинкремент; UUID в API нет (кроме имён файлов изображений) |
| Конверт успешного ответа | отсутствует: возвращается сам объект, массив или `{"status":"ok"}` |
| СContent-Type ошибок | `application/json` |

### 1.2 Аутентификация и cookie

| Свойство | Фактическое значение |
| --- | --- |
| Схема | cookie-сессия; заголовок `Authorization`, Bearer-токены и API-ключи не поддерживаются |
| Имя cookie | `session` |
| Значение | `secrets.token_urlsafe(32)` (43 символа), в БД хранится только `sha256` в hex |
| Атрибуты `Set-Cookie` | `HttpOnly`, `SameSite=Lax`, `Max-Age=604800` (7 суток), `Path=/`; флагов `Secure` и `Domain` нет |
| Срок жизни | фиксированные 7 суток от входа; продления по активности нет |
| Хранение | таблица `sessions`: `token_hash`, `user_id`, `ip`, `user_agent`, `created_at`, `expires_at`, `revoked_at` |
| Проверка | cookie → `sha256` → сессия с `revoked_at IS NULL` и `expires_at >= now`; затем пользователь должен существовать и быть `active` |
| Множественные сессии | разрешены; каждый вход создаёт новую сессию, старые не отзываются |
| Выход | `POST /auth/logout` отзывает текущую сессию и удаляет cookie; без cookie возвращает 200 |
| Сброс пароля / деактивация | отзывают все сессии пользователя |
| CSRF | токенов нет; защита ограничена `SameSite=Lax`. Мутации выполняются методами POST/PATCH/PUT/DELETE, для которых Lax не отправляет cookie с чужих сайтов, но same-site сценарии и старые браузеры не покрыты |
| CORS | разрешены только `http://localhost:5173` и `http://127.0.0.1:5173`, `allow_credentials=true`, любые методы и заголовки. Для других origin браузер заблокирует запрос с cookie |
| IP в журнале входов | `request.client.host`; отдельной обработки `X-Forwarded-For` в коде нет |

Вход выполняется `POST /auth/login` с JSON `{"login": "...", "password": "..."}`. Ответ — `UserOut` без ролей; роли возвращает `GET /auth/me`. Пароли хранятся как bcrypt-хеш, сравнение — `bcrypt.checkpw`.

Ограничения входа (`auth_service.py`):

| Правило | Значение |
| --- | --- |
| Окно подсчёта неудач | 15 минут |
| Неудач на один логин | 5, затем HTTP 429 `RATE_LIMITED` |
| Неудач на один IP | 10, затем HTTP 429 `RATE_LIMITED` |
| Явная блокировка IP | таблица `ip_rules`, действие `block`; проверяется до проверки пароля, ответ 403 `IP_BLOCKED` |
| Сброс лимита | `POST /admin/ip-rules/reset?ip=...` удаляет неудачные `login_events` этого IP |
| Заголовок `Retry-After` | не возвращается |

Каждая попытка входа, включая неуспешную и заблокированную, пишется в `login_events` с причиной (`bad_credentials`, `ip_blocked`, `rate_limited`, `deactivated`). Успешный вход пишет событие с `success=true`.

### 1.3 Время и длительности

| Свойство | Фактическое значение |
| --- | --- |
| Хранение | наивный UTC (`datetime.now(timezone.utc).replace(tzinfo=None)`) |
| Сериализация | ISO 8601 без суффикса `Z` и без смещения: `2026-10-27T13:51:54.123456`; микросекунды могут отсутствовать |
| Вход `deadline` задачи | принимается ISO с `Z` или смещением; приводится к UTC и сохраняется наивным; наивное значение трактуется как UTC |
| Вход `deadline_msk` проекта | то же самое. Несмотря на имя, московское время не применяется: поле фактически хранит UTC |
| Остальные входные даты | API их не принимает (инциденты, документы, аудит дат на вход не имеют) |
| Клиент | `frontend/src/ui.tsx` дописывает `Z`, если в строке нет `Z` или смещения, и только затем парсит |
| Длительности | целые секунды (`estimate_seconds`, `accumulated_seconds`, `elapsed_seconds`, `total_seconds`, `age_seconds`, `deadline_seconds_left`, `active_timer_seconds`) |
| Часовые пояса в запросах | параметров `tz`/`timezone` нет; отображение — ответственность клиента |

Серверные расчёты (`age_seconds`, `deadline_seconds_left`) выполняются на момент запроса и не кешируются.

### 1.4 Ошибки

Единый конверт применяется к `HTTPException`, созданным через `api_error(...)`, и к ошибкам валидации FastAPI:

```json
{"error": {"code": "VERSION_CONFLICT", "message": "Задача изменена другим пользователем", "details": {}}}
```

```json
{"error": {"code": "VALIDATION_ERROR", "message": "Ошибка валидации запроса", "details": {"errors": [{"type": "missing", "loc": ["body", "title"], "msg": "Field required"}]}}}
```

| Свойство | Фактическое значение |
| --- | --- |
| Поля | `error.code` (строка), `error.message` (русский текст), `error.details` (объект; обычно `{}`) |
| `details` при 422 | `{"errors": [...]}` — результат `RequestValidationError.errors()` |
| Семантические 422 | часть проверок возвращает 422 через `api_error`: например `CONFIRM_REQUIRED`, неверный уровень инцидента, неверное расширение файла |
| 404/405 на уровне маршрута | не перехватываются: тело `{"detail":"Not Found"}` / `{"detail":"Method Not Allowed"}` |
| Необработанные исключения | HTTP 500 без конверта; примеры: `IntegrityError` при `NOT NULL`, отсутствующий проект в аналитике/ИИ |
| `HTTP_ERROR` | запасной код для `HTTPException`, брошенного не через `api_error`; в текущем коде таких мест нет |
| 503 | не используется |
| Тело при 401 | конверт `UNAUTHENTICATED` (проверено) |

Клиенту следует принимать решения по `error.code`, а не только по HTTP-статусу: один и тот же статус используется разными кодами, а часть ошибок приходит вне конверта.

### 1.5 Пагинация, лимиты, идемпотентность

| Эндпоинт | Параметры | Значение по умолчанию | Ограничения |
| --- | --- | --- | --- |
| `GET /audit` | `limit`, `offset` | 100, 0 | `limit` 1–1000, `offset` ≥ 0 |
| `GET /admin/login-events` | `limit`, `offset` | 100, 0 | `limit` 1–1000, `offset` ≥ 0 |
| `GET /notifications` | `limit` | 100 | `limit` 1–500; `offset` нет |
| `GET /projects/{id}/ai/recommendations` | `limit` | 50 | `limit` 1–200; `offset` нет |
| `GET /admin/sandbox/runs` | — | 100 | жёсткий `LIMIT 100` |
| `GET /tasks/{id}/history` | — | 100 | жёсткий `LIMIT 100` |

Пагинации нет у списков проектов, задач, колонок, модулей, участников, инцидентов, документов, бэкапов, пользователей и ролей: возвращаются все строки. Метаданных пагинации (`total`, `next`, `Link`) нет. Фильтры задач применяются после загрузки всех задач проекта в память.

Идемпотентности по ключу нет. Повторные `POST` создают дубли, кроме мест, где стоит уникальный индекс или явная проверка (`ROLE_EXISTS`, `DOCUMENT_EXISTS`, `IP_ALREADY_BLOCKED`, голос капитана). `DELETE` идемпотентны частично: отсутствующая сущность обычно даёт 404, но снятие зависимости, снятие чужой блокировки документа и выход — 200.

## 2. Матрица доступа

### 2.1 Модель ролей

| Роль | Область | Как проверяется |
| --- | --- | --- |
| `participant` | проект (в модели), фактически глобально | `require_member`: любая из трёх ролей |
| `captain` | проект (в модели), фактически глобально | `require_captain_or_admin` |
| `admin` | глобальная (`project_id=NULL`) | `require_admin` |

Роли складываются: пользователь может иметь несколько активных назначений. Проверка `active_roles()` выбирает все назначения пользователя с `revoked_at IS NULL` и **не фильтрует по `project_id`**. Поэтому роль, выданная для проекта A, даёт доступ к проекту B; `project_id` в `RoleAssignment` хранится, но в авторизации не участвует (см. GAP-04 в [../docs/10-known-gaps-and-roadmap.md](../docs/10-known-gaps-and-roadmap.md)).

Обозначения в таблицах ниже:

| Метка | Значение |
| --- | --- |
| `—` | без аутентификации |
| `any auth` | любой аутентифицированный пользователь, даже без ролей |
| `member` | `participant`, `captain` или `admin` |
| `captain/admin` | `captain` или `admin` |
| `admin` | только `admin` |

Для всех защищённых эндпоинтов действуют общие ошибки: нет/просрочена/отозвана cookie → 401 `UNAUTHENTICATED`; пользователь деактивирован → 403 `DEACTIVATED`; роли не хватает → 403 `FORBIDDEN`. В таблицах раздела 3 эти коды не повторяются.

### 2.2 Матрица операций

| Операция | participant | captain | admin | Сессия без ролей | Без сессии |
| --- | --- | --- | --- | --- | --- |
| `GET /health` | — | — | — | — | да |
| `POST /auth/login` | — | — | — | — | да |
| `POST /auth/logout` | — | — | — | — | да (cookie опционально) |
| `GET /auth/me` | да | да | да | да | нет |
| `GET /projects`, `GET /audit`, `GET /projects/{id}/analytics` | да | да | да | да | нет |
| Чтение проекта, колонок, модулей, задач, дашборда, участников | да | да | да | нет | нет |
| `POST /projects` | нет | нет | да | нет | нет |
| Переименование проекта | нет | да | да | нет | нет |
| Смена дедлайна проекта | нет | нет | да | нет | нет |
| Колонки и модули: создание, изменение, удаление | да | да | да | нет | нет |
| Задачи, чек-лист, зависимости, исполнители | да | да | да | нет | нет |
| Таймер: start/pause/stop | да | да | да | нет | нет |
| Таймер: ручная корректировка времени | нет | да | да | нет | нет |
| Инциденты: список, карточка, создание, комментарий | да | да | да | да | нет |
| Подтверждение красного инцидента | нет | да | да | нет | нет |
| Закрытие жёлтого инцидента | владелец | да | да | владелец | нет |
| Закрытие красного инцидента | нет | да | да | нет | нет |
| Документы: чтение, запись, блокировки, изображения | да | да | да | да | нет |
| ИИ: чтение настроек и рекомендаций, ручной запуск | да | да | да | да | нет |
| ИИ: изменение настроек, исключение рекомендации | нет | да | да | нет | нет |
| Уведомления: чтение и изменение своих | да | да | да | да | нет |
| Бэкапы, восстановление, `jobs/run`, голосование о завершении | нет | да | да | нет | нет |
| Пользователи, роли, IP-правила, журнал входов, правка аудита | нет | нет | да | нет | нет |
| Песочница | нет | нет | да | нет | нет |

Важные следствия:

1. Пользователь без ролей (например, только что созданный) читает `/projects`, `/audit`, `/analytics`, инциденты, документы и ИИ, но получает 403 на доску, задачи и дашборд.
2. `PATCH /projects/{id}` с пустым телом возвращает 200 даже пользователю без ролей: проверки прав выполняются только при наличии полей `name`/`deadline_msk`.
3. Администратор проходит `member`-проверки, потому что `require_member` включает `admin`.
4. Членство в конкретном проекте не проверяется нигде; `project_id` в пути — единственный селектор данных.

### 2.3 Read-only завершённого проекта

Проект в состоянии `completed` должен быть доступен только для чтения. Фактически проверка `ensure_project_active()` вызывается не везде.

| Операция | Проверка | Фактический результат для `completed` |
| --- | --- | --- |
| `POST /projects/{id}/tasks` | да | 409 `PROJECT_COMPLETED` |
| `POST /tasks/{id}/move` | да | 409 |
| `PUT /tasks/{id}/assignees` | да | 409 |
| `POST /tasks/{id}/dependencies` | да | 409 |
| `DELETE /tasks/{id}/dependencies/{predecessor_id}` | нет | выполняется |
| `PATCH /tasks/{id}` | нет | выполняется |
| Чек-лист: добавление, изменение, удаление | нет | выполняется |
| Таймер: start/pause/stop, корректировка | да | 409 (в том числе нельзя приостановить уже идущий таймер) |
| `PATCH /projects/{id}` | нет | выполняется |
| Колонки и модули: CRUD | нет | выполняется |
| Инциденты: создание, confirm-red, resolve | да | 409 |
| Комментарий к инциденту | нет | выполняется |
| Документы: все мутации | нет | выполняются |
| ИИ: настройки, запуск, исключение | нет | выполняются |
| Голосование о повторном открытии | нет | работает и переводит проект в `preparation` |
| Бэкапы и `jobs/run` | нет | выполняются независимо от состояния проекта |

Таким образом, «read-only» реализован частично. Проверено на работающем приложении: для `completed` проекта `PATCH` задачи, чек-лист, создание колонки, создание документа и переименование проекта возвращают 200, а старт таймера и создание инцидента — 409. Подробнее — в разделе 8.

## 3. Справочник эндпоинтов

Все пути в таблицах даны без префикса `/api/v1`, кроме `GET /health`. Успешный ответ — HTTP 200, если не указано иное. Для каждой группы указано фактическое число обработчиков.

| Группа | Кол-во |
| --- | --- |
| health (вне префикса) | 1 |
| auth | 3 |
| admin | 13 |
| audit | 2 |
| projects, columns, modules, participants | 13 |
| tasks, checklist | 12 |
| timers | 4 |
| dashboard | 1 |
| analytics | 1 |
| incidents | 6 |
| notifications | 5 |
| documents | 13 |
| AI | 5 |
| operations (backups, votes, jobs) | 5 |
| sandbox | 7 |
| **Итого `/api/v1`** | **86** |

### 3.1 Общие схемы ответов

| Схема | Поля |
| --- | --- |
| `UserOut` | `id`, `login`, `display_name`, `telegram_username` (null), `active`, `avatar` (null), `created_at` |
| `MeOut` | поля `UserOut` + `roles[]`: `id`, `role`, `project_id` |
| `RoleOut` | `id`, `role`, `project_id` |
| `ProjectOut` | `id`, `name`, `deadline_msk` (null), `state` (`preparation`/`active`/`completed`), `created_at` |
| `ColumnOut` | `id`, `key`, `title`, `position`, `auto_start_timer`, `auto_stop_timer` |
| `ModuleOut` | `id`, `name`, `description` (null), `traffic_status`, `created_at` |
| `ParticipantOut` | `id`, `login`, `display_name`, `telegram_username` (null), `traffic_status`, `active_tasks`, `active_timer_seconds` |
| `TaskOut` | `id`, `project_id`, `column_id`, `column_key`, `module_id`, `parent_id`, `title`, `description`, `priority`, `estimate_seconds`, `deadline`, `tags[]`, `version`, `created_at`, `updated_at`, `assignees[]` (`user_id`, `login`, `display_name`, `is_primary`), `predecessors[]` (`task_id`, `link_type`), `checklist[]` (`id`, `text`, `done`, `position`), `timer` (null или `TimerOut`) |
| `TimerOut` | `state` (`running`/`paused`/`stopped`), `accumulated_seconds`, `elapsed_seconds`, `total_seconds` |
| `ChecklistItemOut` | `id`, `text`, `done`, `position` |
| `DashboardOut` | `project` (`ProjectOut`), `deadline_seconds_left` (null), `total_tasks`, `completed_tasks`, `in_progress_tasks`, `overdue_tasks`, `active_timers`, `active_participants`, `progress_percent`, `estimate_seconds`, `actual_seconds`, `calendar_seconds`, `risks[]` (`task_id`, `title`, `deadline`, `type="overdue"`) |
| `AnalyticsOut` | `kpi` (`project_id`, `name`, `state`, `deadline_msk`, `deadline_seconds_left`, `total_tasks`, `completed_tasks`, `in_progress_tasks`, `overdue_tasks`, `active_timers`, `active_participants`, `progress_percent`, `estimate_seconds`, `actual_seconds`, `calendar_seconds`), `participants[]` (`ParticipantOut`), `modules[]` (`id`, `name`, `total`, `done`, `progress`, `traffic_status`), `burn_down[]` (`date`, `created`, `completed`, `remaining`), `time_by_user[]` (`user_id`, `login`, `display_name`, `seconds`), `active_incidents[]` (`id`, `title`, `level`, `status`), `risks[]` (`type`, `task_id`/`incident_id`, `title`, `deadline`/`level`/`status`) |
| `IncidentOut` | `id`, `project_id`, `level`, `status` (`open`/`confirmed`/`resolved`), `title`, `description`, `impact`, `urgency`, `author_id`, `owner_id`, `resolution`, `created_at`, `confirmed_at`, `resolved_at`, `age_seconds`, `targets[]` (`target_type`, `target_id`), `events[]` (`id`, `incident_id`, `actor_id`, `event_type`, `data`, `created_at`) |
| `NotificationOut` | `id`, `project_id`, `user_id`, `type`, `payload`, `read_at`, `created_at` |
| `DocumentOut` | `id`, `path`, `author_id`, `checksum`, `trashed`, `created_at`, `updated_at`, `locked_by`, `editors[]` (0 или 1 элемент — текущий держатель блокировки) |
| `AiSettingsOut` | `enabled`, `priority_provider`, `prompt`, `interval_minutes`, `triggers` |
| `AiRecommendationOut` | `id`, `provider`, `trigger`, `summary`, `content`, `excluded`, `created_at` |
| `AuditEntryOut` | `id`, `project_id`, `actor_id`, `action`, `entity_type`, `entity_id` (строка), `data`, `created_at` |
| `AuditRevisionOut` | `id`, `audit_entry_id`, `field`, `old_value`, `new_value`, `edited_by`, `edited_at` |
| `LoginEventOut` | `id`, `login`, `ip`, `user_id`, `success`, `reason`, `created_at` |
| `BackupOut` | `id`, `path` (имя файла в `data/backups/`), `checksum`, `size_bytes`, `kind` (`automatic`/`manual`/`safety`), `created_at` |
| `SandboxRunOut` | `id`, `scenario`, `status` (`ok`/`error`), `logs[]`, `run_by`, `created_at` |

Все `datetime` в ответах — наивный UTC в формате из п. 1.3. Все поля, не помеченные null, присутствуют всегда; `null` возможен только там, где указано.

### 3.2 Health

| Метод и путь | Кто | Вход | Выход | Особенности и ошибки |
| --- | --- | --- | --- | --- |
| `GET /health` | — | — | `{"status":"ok"}` | Выполняет `SELECT 1` к БД; 200 только при доступной БД. Папка данных, права записи и применённость миграций не проверяются, хотя комментарий в коде это обещает. Ошибка БД → 500 без конверта |

### 3.3 Auth

| Метод и путь | Кто | Вход | Выход | Особенности и ошибки |
| --- | --- | --- | --- | --- |
| `POST /auth/login` | — | `{"login": str, "password": str}`; ограничений длины и формата в схеме нет | `UserOut`; `Set-Cookie: session=...` | 401 `BAD_CREDENTIALS`; 403 `IP_BLOCKED`; 403 `DEACTIVATED`; 429 `RATE_LIMITED`; пишет `login_events` при каждой попытке; роли не возвращает |
| `POST /auth/logout` | — (cookie опционально) | — | `{"status":"ok"}` | Отзывает сессию, если cookie передан; удаляет cookie; повторный вызов безопасен |
| `GET /auth/me` | any auth | — | `MeOut` | 401 `UNAUTHENTICATED` при отсутствии/истечении/отзыве сессии; 403 `DEACTIVATED` для неактивного пользователя |

### 3.4 Admin

Все маршруты этой группы защищены на уровне роутера (`dependencies=[Depends(require_admin)]`) и дополнительно внутри обработчиков; доступ только `admin`. Префикс `/admin`.

| Метод и путь | Кто | Вход | Выход | Особенности и ошибки |
| --- | --- | --- | --- | --- |
| `GET /admin/users` | admin | — | `UserOut[]` | Все пользователи, включая деактивированных; сортировка по `id`; пагинации нет |
| `GET /admin/roles` | admin | — | `[{"id": int, "user_id": int, "role": str, "project_id": int\|null}]` | Только активные назначения (`revoked_at IS NULL`); `response_model` не задан; сортировка по `id` |
| `POST /admin/users` | admin | `login` 1–128, `password` 1–255, `display_name` 1–255, `telegram_username?` ≤128 | `UserOut` | 409 `LOGIN_TAKEN`; пишет `user.created`; пароль хешируется bcrypt; пользователь сразу активен |
| `PATCH /admin/users/{user_id}` | admin | `login?`, `display_name?`, `telegram_username?` | `UserOut` | 404 `NOT_FOUND`; 409 `LOGIN_TAKEN`; аудит только для `login` и `display_name`; `telegram_username: null` игнорируется (очистить нельзя) |
| `POST /admin/users/{user_id}/password-reset` | admin | `{"new_password": str}` 1–255 | `UserOut` | 404 `NOT_FOUND`; меняет хеш, отзывает все сессии, пишет `user.password_reset`; старый пароль не раскрывается |
| `POST /admin/users/{user_id}/deactivate` | admin | — | `UserOut` | 404 `NOT_FOUND`; 409 `LAST_ADMIN`, если это последний активный администратор; выставляет `active=false`, отзывает роли и сессии, пишет `user.deactivated`; повторная деактивация — 200 без изменений |
| `POST /admin/roles` | admin | `{"user_id": int, "role": "participant"\|"captain"\|"admin", "project_id?": int}` | `RoleOut` | 404 `NOT_FOUND` (пользователь); 409 `ROLE_EXISTS`; для `admin` `project_id` принудительно `NULL`; для `participant`/`captain` `project_id` может быть `NULL` и не проверяется на существование проекта; пишет `role.granted` |
| `DELETE /admin/roles/{assignment_id}` | admin | — | `{"status":"ok"}` | 404, если назначение не найдено или уже отозвано; 409 `LAST_ADMIN` для роли последнего администратора; выставляет `revoked_at`; пишет `role.revoked` |
| `GET /admin/login-events` | admin | `limit` 1–1000 (100), `offset` ≥0 (0) | `LoginEventOut[]` | Сортировка по `created_at` desc; все логины, включая неуспешные |
| `POST /admin/ip-rules` | admin | `{"ip": str}` 1–64 | `{"ip": str}` — эхо запроса, не запись | 409 `IP_ALREADY_BLOCKED`; создаёт правило `action="block"`; пишет `ip.blocked`; `id` правила не возвращается |
| `DELETE /admin/ip-rules/{rule_id}` | admin | — | `{"status":"ok"}` | 404 `NOT_FOUND`; удаляет правило; пишет `ip.unblocked`. Списка правил (`GET /admin/ip-rules`) нет, поэтому `rule_id` через API получить негде |
| `POST /admin/ip-rules/reset` | admin | query `ip` (обязателен) | `{"status":"ok"}` | Удаляет все неудачные `login_events` указанного IP; формат IP не валидируется; пишет `ip.limit_reset` |
| `PATCH /admin/audit/{entry_id}` | admin | `{"field": "action"\|"entity_type"\|"entity_id", "new_value": str}` | `{"status":"ok"}` | 404 `NOT_FOUND`; 422 `VALIDATION_ERROR` для другого поля; меняет поле записи и добавляет `AuditRevision` со старым и новым значением; сам факт правки в аудит не пишется |

### 3.5 Audit

| Метод и путь | Кто | Вход | Выход | Особенности и ошибки |
| --- | --- | --- | --- | --- |
| `GET /audit` | any auth | `limit` 1–1000 (100), `offset` ≥0 (0) | `AuditEntryOut[]` | Без фильтров по проекту, актору и действию; сортировка по `created_at` desc; доступен пользователю без ролей (проверено тестом) |
| `GET /audit/{entry_id}/revisions` | any auth | — | `AuditRevisionOut[]` | История правок записи; сортировка по `edited_at`; если записи нет — пустой массив, не 404 |

### 3.6 Проекты, колонки, модули, участники

| Метод и путь | Кто | Вход | Выход | Особенности и ошибки |
| --- | --- | --- | --- | --- |
| `GET /projects` | any auth | — | `ProjectOut[]` | Все проекты, сортировка по `id`; фильтра членства нет |
| `POST /projects` | admin | `{"name": str}` 1–255 | `ProjectOut` | 403 `FORBIDDEN` для не-админа; создаёт проект в состоянии `preparation` и 9 стартовых колонок; пишет `project.created` |
| `GET /projects/{project_id}` | member | — | `ProjectOut` | 404 `NOT_FOUND` |
| `PATCH /projects/{project_id}` | any auth + права по полям | `name?` 1–255, `deadline_msk?` ISO/null | `ProjectOut` | 404; `name` — только `captain/admin` (403 `FORBIDDEN`); `deadline_msk` — только `admin` (403); пустое тело возвращает 200 даже без ролей; `state` через этот эндпоинт не меняется; аудит `project.renamed` / `project.deadline_changed` |
| `GET /projects/{project_id}/columns` | member | — | `ColumnOut[]` | 404, если проекта нет; сортировка по `position` |
| `POST /projects/{project_id}/columns` | member | `title` 1–128, `auto_start_timer=false`, `auto_stop_timer=false` | `ColumnOut` | 404; `key` — slug из `title`: только `a-z0-9`, иначе `custom`, `custom_2`, …; `position = max + 1`; пишет `column.created`; проверки завершённости нет |
| `PATCH /columns/{column_id}` | member | `title?`, `auto_start_timer?`, `auto_stop_timer?` | `ColumnOut` | 404; пишет `column.updated` даже без изменений; версии нет; проверки завершённости нет |
| `DELETE /columns/{column_id}` | member | — | `{"status":"ok"}` | 404; 409 `COLUMN_PROTECTED` для девяти стартовых ключей; задачи переносятся в `backlog`; пишет `column.deleted` |
| `GET /projects/{project_id}/modules` | member | — | `ModuleOut[]` | 404; `traffic_status` берётся из БД и всегда `green` (поле нигде не обновляется) |
| `POST /projects/{project_id}/modules` | member | `name` 1–255, `description?` | `ModuleOut` | 404; пишет `module.created`; `traffic_status` не вычисляется |
| `PATCH /modules/{module_id}` | member | `name?`, `description?` | `ModuleOut` | 404; `description: null` игнорируется; пишет `module.updated` |
| `DELETE /modules/{module_id}` | member | — | `{"status":"ok"}` | 404; у задач обнуляется `module_id`; пишет `module.deleted` |
| `GET /projects/{project_id}/participants` | member | — | `ParticipantOut[]` | 404; включает всех пользователей с любой активной ролью (глобально), не только участников проекта; порядок не определён; `traffic_status` вычисляется по инцидентам с целью `user`; `active_tasks` — задачи вне `done`/`realised`/`trashed`; `active_timer_seconds` — только идущие таймеры |

Состояние проекта меняется только голосованием: `complete` → `completed`, `reopen` → `preparation`. Перевести проект в `active` через API нельзя; `active` создаёт только песочница.

### 3.7 Задачи и чек-лист

| Метод и путь | Кто | Вход | Выход | Особенности и ошибки |
| --- | --- | --- | --- | --- |
| `GET /projects/{project_id}/tasks` | member | query `assignee_id?`, `module_id?`, `column_key?`, `tag?` | `TaskOut[]` | Проверки существования проекта нет: для неизвестного проекта — `[]`; неизвестный `column_key` — `[]`; фильтры применяются в Python; сортировка по `id`; пагинации нет; задачи в `trashed` тоже возвращаются |
| `POST /projects/{project_id}/tasks` | member | `title` 1–255; `description?`; `module_id?`; `priority="medium"` (значение не валидируется); `estimate_seconds?` ≥0; `deadline?`; `tags[]`; `column_key="backlog"`; `parent_id?` | `TaskOut` | 409 `PROJECT_COMPLETED`; 404 `COLUMN_NOT_FOUND`; 422, если модуль или родитель из другого проекта; можно создать сразу в `done`/`trashed`; `version=1`; пишет `task.created` |
| `GET /tasks/{task_id}` | member | — | `TaskOut` | 404 `NOT_FOUND`; таймер отдаётся с пересчитанным `elapsed_seconds` |
| `GET /tasks/{task_id}/history` | member | — | `[{action, actor_id, data, created_at}]` | 404; последние 100 записей аудита с `entity_type="task"` и `entity_id=str(id)`, desc |
| `PATCH /tasks/{task_id}` | member | `version` (обязателен) + `title?`, `description?`, `module_id?`, `priority?`, `estimate_seconds?`, `deadline?`, `tags?` | `TaskOut` | 409 `VERSION_CONFLICT`; 422 при чужом модуле; `column_id` менять нельзя — только `move`; `version` увеличивается на 1; пишет `task.updated`; проверки завершённости проекта нет; явный `null` в `title`/`tags` приводит к 500 (`NOT NULL`) |
| `POST /tasks/{task_id}/move` | member | `{"column_key": str, "version": int}` | `TaskOut` | 409 `PROJECT_COMPLETED`, 409 `VERSION_CONFLICT`; 404 `COLUMN_NOT_FOUND`; матрицы допустимых переходов нет; `version+1`; аудит `task.moved` с `from_column`/`to_column`/`key`; после перемещения применяются правила авто-старта/остановки таймера |
| `PUT /tasks/{task_id}/assignees` | member | `{"assignees": [{"user_id": int, "is_primary": bool}]}` | `TaskOut` | 409 `PROJECT_COMPLETED`; 422, если список непуст и основных исполнителей не ровно один; 422 для несуществующего пользователя; пустой список очищает исполнителей; старые назначения удаляются; `version+1`; аудит `task.assignees_set`; уведомления `task_assigned`; дубли `user_id` не проверяются |
| `POST /tasks/{task_id}/dependencies` | member | `predecessor_id` int, `link_type="blocked_by"` ∈ `blocked_by`/`after`/`before` | `TaskOut` | 409 `PROJECT_COMPLETED`; 422 для self, неверного типа, чужого проекта; повторная связь — no-op с 200; `version` не меняется; аудит `task.dependency_added` |
| `DELETE /tasks/{task_id}/dependencies/{predecessor_id}` | member | — | `TaskOut` | Идемпотентно: отсутствующая связь — 200; проверки завершённости нет; `version` не меняется; аудит `task.dependency_removed` при удалении |
| `POST /tasks/{task_id}/checklist` | member | `{"text": str}` 1–500 | `ChecklistItemOut` | `position` = текущее количество элементов; проверки завершённости и версии нет; аудит `task.checklist_added` |
| `PATCH /checklist/{item_id}` | member | `text?`, `done?` | `ChecklistItemOut` | 404; версии, аудита и проверки завершённости нет |
| `DELETE /checklist/{item_id}` | member | — | `{"status":"ok"}` | 404; версии, аудита и проверки завершённости нет |

### 3.8 Таймеры

| Метод и путь | Кто | Вход | Выход | Особенности и ошибки |
| --- | --- | --- | --- | --- |
| `POST /tasks/{task_id}/timer/start` | member | — | `TimerOut` | 404; 409 `PROJECT_COMPLETED`; 409 `TIMER_RUNNING`, если уже идёт; создаёт таймер при первом запуске и новый `TimerSegment`; запускать может любой member, не только исполнитель |
| `POST /tasks/{task_id}/timer/pause` | member | — | `TimerOut` | 404; 409 `PROJECT_COMPLETED`; 409 `TIMER_NOT_RUNNING`, если таймер не идёт; закрывает сегмент, начисляет секунды, состояние `paused` |
| `POST /tasks/{task_id}/timer/stop` | member | — | `TimerOut` | 404; 409 `PROJECT_COMPLETED`; 409 `TIMER_NOT_ACTIVE`, если таймера нет или он уже `stopped`; из `running` закрывает сегмент; состояние `stopped` |
| `POST /tasks/{task_id}/time-adjustment` | captain/admin | `{"accumulated_seconds": int}` ≥0 | `TimerOut` | 404; 409 `PROJECT_COMPLETED`; создаёт таймер в состоянии `stopped`, если его не было; иначе перезаписывает `accumulated_seconds`; идущий сегмент не закрывается и продолжает добавлять `elapsed_seconds`; аудит `task.time_adjusted` |

`TimerOut.total_seconds = accumulated_seconds + elapsed_seconds`. `elapsed_seconds` считается от `last_started_at` только для `running`. Таймер один на задачу (уникальный индекс), но параллельные таймеры разных задач разрешены; лимита «один таймер на пользователя» нет.

### 3.9 Дашборд

| Метод и путь | Кто | Вход | Выход | Особенности и ошибки |
| --- | --- | --- | --- | --- |
| `GET /projects/{project_id}/dashboard` | member | — | `DashboardOut` | 404 `NOT_FOUND`; `total_tasks` — все задачи, кроме `trashed`; `completed` — `done`+`realised`; `in_progress` — `in_progress`+`testing`+`review`; `overdue` — не завершённые задачи с дедлайном в прошлом; `progress_percent` — доля завершённых, 1 знак; `estimate_seconds`/`actual_seconds` считаются по **всем** задачам, включая `trashed`; `calendar_seconds` — объединение интервалов сегментов проекта; `active_timers`/`active_participants` считаются по идущим таймерам **выбранного** проекта; `risks` содержит только просрочки |

### 3.10 Аналитика

| Метод и путь | Кто | Вход | Выход | Особенности и ошибки |
| --- | --- | --- | --- | --- |
| `GET /projects/{project_id}/analytics` | any auth | — | `AnalyticsOut` | Проверки существования проекта нет: для отсутствующего проекта — 500 (`AttributeError` у `project.name`), не 404. `kpi` повторяет расчёты дашборда (с теми же глобальными таймерами и `trashed` в оценках); `participants` — глобальные роли; `modules[].traffic_status` вычисляется по инцидентам; `burn_down` строится по аудиту `task.created` и первому `task.moved` в `done`/`realised`; `time_by_user` группирует время по основному исполнителю, задачи без исполнителя попадают в строку «Без исполнителя»; `risks` включает просрочки (в том числе в `trashed`) и активные инциденты |

### 3.11 Инциденты

| Метод и путь | Кто | Вход | Выход | Особенности и ошибки |
| --- | --- | --- | --- | --- |
| `GET /projects/{project_id}/incidents` | any auth | query `status?`, `level?` (точное совпадение) | `IncidentOut[]` | Проверки проекта нет: неизвестный проект — `[]`; сортировка по `created_at` desc; пагинации нет |
| `POST /projects/{project_id}/incidents` | any auth | `level` `yellow`/`red`; `title` 1–255; `description?`; `impact?`; `urgency?`; `owner_id?`; `targets[]` (`target_type` `task`/`module`/`user`, `target_id` int) | `IncidentOut` | 409 `PROJECT_COMPLETED`; 422 для неверного уровня или типа цели; существование `owner_id` и целей не проверяется; статус `open`; событие `created`; уведомления: `red` — капитанам, `yellow` — владельцу и капитанам; аудит не пишется |
| `GET /incidents/{incident_id}` | any auth | — | `IncidentOut` | 404 `NOT_FOUND`; доступа к проекту не проверяет |
| `POST /incidents/{incident_id}/confirm-red` | captain/admin | `{"confirm": true, "comment?": str}` | `IncidentOut` | 403 `FORBIDDEN` для не-капитана; 404; 409 `PROJECT_COMPLETED`; 422, если инцидент не `red`; 409 `INVALID_STATE`, если уже обработан; `confirm=true` → `confirmed` + `confirmed_at` + уведомление команде; `confirm=false` → `resolved` + `resolution` (комментарий или «Эскалация отклонена»); события `confirmed`/`rejected` |
| `POST /incidents/{incident_id}/resolve` | any auth + правило | `{"resolution": str}` (непустая) | `IncidentOut` | 404; 409 `PROJECT_COMPLETED`; 409 `INVALID_STATE`, если уже `resolved`; для `red` — только `captain/admin` (403); для `yellow` — владелец или `captain/admin` (403 иначе); уведомление автору и владельцу; событие `resolved` |
| `POST /incidents/{incident_id}/events` | any auth | `{"text": str}` (непустая) | `IncidentOut` | 404; добавляет событие `comment`; разрешено для закрытого инцидента; проверки `PROJECT_COMPLETED` нет; аудит не пишется |

### 3.12 Уведомления

| Метод и путь | Кто | Вход | Выход | Особенности и ошибки |
| --- | --- | --- | --- | --- |
| `GET /notifications` | any auth (свои) | `unread_only=false`, `limit` 1–500 (100) | `NotificationOut[]` | Только `user_id` текущего пользователя; сортировка по `created_at` desc; `offset` нет |
| `POST /notifications/{notification_id}/read` | any auth (свои) | — | `NotificationOut` | 404, если уведомления нет или оно чужое; `read_at` ставится один раз, повторный вызов возвращает прежнее значение |
| `POST /notifications/read-all` | any auth (свои) | — | `{"status":"ok"}` | Помечает прочитанными все непрочитанные уведомления пользователя |
| `DELETE /notifications/{notification_id}` | any auth (свои) | — | `{"status":"ok"}` | 404 для чужого/отсутствующего; физическое удаление |
| `DELETE /notifications` | any auth (свои) | — | `{"status":"ok"}` | Удаляет все уведомления пользователя; тела нет |

### 3.13 Документы

| Метод и путь | Кто | Вход | Выход | Особенности и ошибки |
| --- | --- | --- | --- | --- |
| `GET /projects/{project_id}/documents` | any auth | — | `DocumentOut[]` | Только `trashed=false`; сортировка по `path`; проект не проверяется (неизвестный → `[]`) |
| `GET /projects/{project_id}/documents/trash` | any auth | — | `DocumentOut[]` | Только `trashed=true`; сортировка по `path` |
| `POST /projects/{project_id}/documents` | any auth | `{"path": str}` 1–512, `{"content": str}` (по умолчанию `""`) | `DocumentOut` | 422, если путь не заканчивается на `.md`/`.markdown` (регистрозависимо); 409 `DOCUMENT_EXISTS`, если путь занят, в том числе документом в корзине; создаёт файл в `data/documents/{project_id}/{path}` и запись; проект, членство и завершённость не проверяются; аудит не пишется |
| `GET /documents/{document_id}` | any auth | — | `DocumentOut` | 404 `NOT_FOUND` |
| `GET /documents/{document_id}/content` | any auth | — | `{"content": str}` | 404, если нет записи или файла на диске; содержимое читается с диска |
| `PUT /documents/{document_id}/content` | any auth | `{"content": str, "base_checksum": str}` | `DocumentOut` | 409 `VERSION_CONFLICT`, если `base_checksum != document.checksum`; перезаписывает файл, обновляет `checksum` и `updated_at`; блокировка не проверяется; аудит не пишется; `base_checksum` обязателен |
| `POST /documents/{document_id}/lock` | any auth | — | `DocumentOut` | 409 `DOCUMENT_LOCKED`, если активная блокировка принадлежит другому; своя блокировка продлевается; истёкшая (5 минут) удаляется и создаётся заново |
| `DELETE /documents/{document_id}/lock` | any auth | — | `DocumentOut` | Снимает только свою блокировку; чужая остаётся, ответ 200 без ошибки |
| `POST /documents/{document_id}/heartbeat` | any auth | — | `DocumentOut` | Продлевает только свою блокировку; для чужой/отсутствующей — 200 без изменений |
| `DELETE /documents/{document_id}` | any auth | — | `{"status":"ok"}` | Мягкое удаление: `trashed=true`, файл остаётся; постоянного удаления нет; путь остаётся занятым |
| `POST /documents/{document_id}/restore` | any auth | — | `{"status":"ok"}` | `trashed=false` |
| `POST /projects/{project_id}/documents/images` | any auth | `multipart/form-data`, поле `file` | `{"path": "assets/<uuid>.<ext>"}` | Расширение из имени файла, whitelist `png/jpg/jpeg/gif/webp/svg`, иначе 422; содержимое и размер не проверяются; файл пишется в `assets/`; аудит не пишется |
| `GET /projects/{project_id}/documents/images/{filename}` | any auth | — | файл (`FileResponse`) | 404, если файла нет; путь резолвится в `assets/{filename}`; MIME определяется по расширению |

### 3.14 ИИ-советник

| Метод и путь | Кто | Вход | Выход | Особенности и ошибки |
| --- | --- | --- | --- | --- |
| `GET /projects/{project_id}/ai/settings` | any auth | — | `AiSettingsOut` | Если записи нет, возвращает дефолт (`enabled=false`, `priority_provider="gemini"`, `prompt` — текст по умолчанию, `interval_minutes=30`, все триггеры `true`), но созданную строку не коммитит: каждый GET снова отдаёт дефолт; для отсутствующего проекта при включённых FK — 500 |
| `PATCH /projects/{project_id}/ai/settings` | captain/admin | `enabled?`, `priority_provider?`, `prompt?`, `interval_minutes?` 5–1440, `triggers?` (объект) | `AiSettingsOut` | Создаёт запись при необходимости; значения `priority_provider` и `triggers` не валидируются; аудит не пишется; проверки завершённости нет |
| `GET /projects/{project_id}/ai/recommendations` | any auth | `limit` 1–200 (50) | `AiRecommendationOut[]` | Сортировка по `created_at` desc; проект не проверяется; `offset` нет |
| `POST /projects/{project_id}/ai/run` | any auth | `{"trigger": "manual"}` (любая строка) | `AiRecommendationOut` | 409 `AI_DISABLED`, если настройки выключены; 429 `RATE_LIMITED` для не-`manual` триггера, если с прошлого запуска прошло меньше `interval_minutes`; лимит хранится в памяти процесса и сбрасывается при перезапуске; содержимое — mock по снимку проекта; реальные Gemini/DeepSeek не вызываются; проверки проекта и завершённости нет |
| `POST /projects/{project_id}/ai/recommendations/{rec_id}/exclude` | captain/admin | — | `AiRecommendationOut` | 404, если рекомендации нет или она из другого проекта; переключает `excluded`; на снимок и запуски не влияет; аудит не пишется |

### 3.15 Операции: бэкапы, голосование, фоновые задачи

Маршруты `backups` и `jobs` находятся в роутере `operations` и не защищены `require_admin`; для них достаточно `captain/admin`, несмотря на префикс `/admin`.

| Метод и путь | Кто | Вход | Выход | Особенности и ошибки |
| --- | --- | --- | --- | --- |
| `POST /admin/backups` | captain/admin | — | `BackupOut` | Создаёт zip `backup_<timestamp>_manual.zip` в `data/backups/`; обновляет `latest.zip`; удаляет старые обычные zip-файлы; запись в БД; аудит не пишется |
| `GET /admin/backups` | captain/admin | — | `BackupOut[]` | Все записи по `created_at` desc; может содержать записи, чьи файлы уже удалены политикой хранения |
| `POST /admin/backups/{backup_id}/restore` | captain/admin | `{"confirm": bool}` (по умолчанию `false`) | `{"status":"ok", "backup_id": int}` | 422 `CONFIRM_REQUIRED` без `confirm=true`; 404, если записи или файла нет; 409 `BACKUP_CORRUPT` при несовпадении sha256; создаёт safety-бэкап, распаковывает, закрывает сессию и engine, заменяет БД и каталог документов, выполняет `alembic stamp head`; сервер не перезапускается, сессии из старой БД могут стать недействительными |
| `POST /projects/{project_id}/completion-votes` | captain/admin | `{"action": "complete"\|"reopen"}` | `{"state": str, "votes": int, "required": int}` | 404; 422 `VALIDATION_ERROR` для другого `action`; голос уникален для пользователя/проекта/действия; при единогласии всех активных `captain`+`admin` проект переходит в `completed` (complete) или `preparation` (reopen), все голоса проекта удаляются, пишется `project.completed`/`project.reopend`; проверки завершённости нет — повторное открытие работает |
| `POST /admin/jobs/run` | captain/admin | — | `{"locks_cleaned": int, "overdue_notified": int}` | Запускает очистку просроченных блокировок и рассылку о просрочках; `overdue_notified` — число задач, по которым созданы уведомления, а не число уведомлений |

### 3.16 Песочница

Актуальное расширение: [стенд и API песочницы](../docs/12-sandbox.md#api). Дополнительно доступны `/workspace`, `/checks`, `/reset`, `/telegram`; `/run` принимает `full_check` и `check:<group>`. Старые таблицы ниже описывают исходный прототип; неизвестный сценарий теперь возвращает 422, а отчёт содержит `checks[]` и `duration_ms`.

Все маршруты защищены `admin` на уровне роутера и внутри обработчика; префикс `/admin/sandbox`.

| Метод и путь | Кто | Вход | Выход | Особенности и ошибки |
| --- | --- | --- | --- | --- |
| `GET /admin/sandbox/scenarios` | admin | — | `{scenario: description}` | Подготовка демо, команда, спринт, просрочка, блокер, таймер, мок-уведомления и проверка ошибок ИИ |
| `POST /admin/sandbox/run` | admin | `{"scenario": str}` | `SandboxRunOut` | Принимает сценарий, `full_check` или `check:<group>`; неизвестный ключ → 422; занятый стенд → 409; отчёт содержит `checks[]`, `duration_ms` и корректный статус ошибки. Подготовка данных меняет только тестовый проект, диагностика использует временные БД |
| `GET /admin/sandbox/runs` | admin | — | `SandboxRunOut[]` | Последние 100 запусков по `created_at` desc |
| `GET /admin/sandbox/workspace` | admin | — | `WorkspaceOut` | Сводка выделенного проекта и тестовые аккаунты; чтение не создаёт новый проект |
| `GET /admin/sandbox/checks` | admin | — | `{key: title}` | Семь групп диагностических проверок |
| `POST /admin/sandbox/reset` | admin | `{"project_id": int, "confirm": bool}` | `ResetOut` | 422 без подтверждения; 409 для чужого проекта или занятости; перед очисткой — копия SQLite и архив файлов; общие аккаунты сохраняются |
| `GET /admin/sandbox/telegram` | admin | `project_id`, `limit` (1–500) | `TelegramDeliveryOut[]` | Журнал предполагаемых отправок; внешних вызовов нет |

## 4. Сквозные правила

### 4.1 Версионирование задач

| Операция | `version` в запросе | Изменение `version` |
| --- | --- | --- |
| `POST /projects/{id}/tasks` | нет | устанавливается 1 |
| `PATCH /tasks/{id}` | обязателен | +1 |
| `POST /tasks/{id}/move` | обязателен | +1 |
| `PUT /tasks/{id}/assignees` | нет | +1 |
| `POST/DELETE /tasks/{id}/dependencies` | нет | не меняется |
| `POST/PATCH/DELETE` чек-листа | нет | не меняется |
| Таймеры и корректировка времени | нет | не меняется |
| Документы | вместо версии — `base_checksum` | меняется `checksum` |

При несовпадении `version` возвращается 409 `VERSION_CONFLICT`; при несовпадении `base_checksum` — 409 `VERSION_CONFLICT`. Сервер не выполняет слияние и не возвращает текущую версию в теле ошибки: клиент должен заново прочитать сущность и повторить операцию. `updated_at` для контроля конкурентности не используется.

`PATCH /tasks/{id}` с одним `version` и без изменяемых полей всё равно увеличивает версию на 1 и пишет `task.updated`. `PUT assignees` увеличивает версию даже при том же наборе исполнителей.

### 4.2 Авто-старт и авто-остановка таймера

Правила применяются только в `POST /tasks/{id}/move`, после смены колонки:

1. Если у целевой колонки `auto_start_timer=true` и таймер не в состоянии `running` — вызывается `start_timer` (из `paused`/`stopped`/отсутствия).
2. Иначе, если `auto_stop_timer=true` и таймер `running` — вызывается `stop_timer`.
3. Если у колонки включены оба флага и таймер уже идёт, сработает остановка (первое условие ложно, второе истинно).

Создание задачи сразу в колонке с `auto_start_timer` таймер не запускает. Перемещение в ту же колонку всё равно увеличивает `version` и может запустить/остановить таймер. Автоправила не обходят проверку `PROJECT_COMPLETED`: перемещение в завершённом проекте запрещено.

Состояния таймера: `stopped` (начальное или после остановки), `running`, `paused`. `start` создаёт новый `TimerSegment`; `pause`/`stop` закрывают открытый сегмент и начисляют секунды в `accumulated_seconds`. `stop` из `paused` не закрывает сегмент (он уже закрыт). Ручная корректировка меняет `accumulated_seconds`, не трогая открытый сегмент; если таймер идёт, `total_seconds` продолжает расти.

### 4.3 Документы: checksum и блокировки

| Правило | Значение |
| --- | --- |
| Checksum | `sha256(content.encode("utf-8"))`, hex; хранится в `documents.checksum` |
| Оптимистичная блокировка | `PUT /documents/{id}/content` требует `base_checksum`, равный текущему; иначе 409 |
| Блокировка редактирования | одна запись `document_locks` на документ; TTL 5 минут от `last_activity_at` |
| Захват | `POST /lock`; чужая активная блокировка → 409 `DOCUMENT_LOCKED`; своя — продление |
| Продление | `POST /heartbeat`; только своя блокировка |
| Снятие | `DELETE /lock`; только своя; чужая остаётся, ответ 200 |
| Очистка | лениво при чтении/захвате и фоновой задачей каждые 60 секунд |
| Проверка при записи | отсутствует: `PUT content` не требует владения блокировкой |
| Хранение | файлы в `data/documents/{project_id}/`; запись в БД хранит путь, checksum и флаг корзины |
| Удаление | мягкое (`trashed=true`), файл остаётся; восстановление — `POST /restore` |
| Версии | истории версий нет, только текущий checksum |

### 4.4 Уведомления и дедупликация

| Тип | Когда создаётся | Получатели | `payload` |
| --- | --- | --- | --- |
| `task_assigned` | `PUT /tasks/{id}/assignees` с непустым списком | все назначенные | `task_id`, `title` |
| `incident_yellow_created` | создан жёлтый инцидент | владелец + все `captain`/`admin` | `incident_id`, `title`, `level` |
| `incident_red_created` | создан красный инцидент | все `captain`/`admin` | `incident_id`, `title`, `level` |
| `incident_red_confirmed` | красный подтверждён | все `participant`/`captain`/`admin` | `incident_id`, `title` |
| `incident_resolved` | инцидент закрыт | автор + владелец | `incident_id`, `title`, `resolution` |
| `task_overdue` | фоновая задача `check_overdue` | все `participant`/`captain`/`admin` | `task_id`, `title` |

Получатели ограничиваются проектом; глобальные администраторы получают уведомления согласно действующим правилам. Внутри одного вызова `notify_users` дубли пользователей устраняются через `set`.

Дедупликация есть только у просрочек: перед созданием проверяются все существующие `Notification` проекта с `type="task_overdue"` и собираются `payload.task_id`; если задача уже когда-либо попадала в рассылку, повторное уведомление не создаётся (даже после закрытия и повторного открытия просрочки). Для назначений и инцидентов дедупликации нет: повторное назначение или повторное создание инцидента создаёт новые уведомления.

Telegram использует транзакционную очередь и фонового отправителя; настройки, маршруты,
состояния доставки и API удаления аккаунтов описаны в [актуальном расширении](../docs/16-telegram-and-accounts.md#api-и-проверка).

### 4.5 Голосование о завершении

| Правило | Фактическое поведение |
| --- | --- |
| Кто голосует | пользователи с активной ролью `captain` или `admin` (глобально, не по проекту) |
| Уникальность | один голос на `(project_id, user_id, action)` |
| Условие перехода | все текущие активные `captain`+`admin` должны иметь голос за это действие |
| `complete` | проект → `completed`; аудит `project.completed` |
| `reopen` | проект → `preparation`; аудит `project.reopend` (опечатка в коде) |
| После решения | все голоса проекта удаляются |
| Ответ | `state`, `votes` (число голосов за действие), `required` (число активных капитанов и админов) |
| Проверка состояния | нет: голосование доступно и в `completed`, и в `preparation` |
| Автозавершение по дедлайну | отсутствует |

Голоса пользователей, потерявших роль, остаются в таблице и учитываются в `votes`, но для единогласия требуется подмножество текущих `captain_ids`; лишние голоса не мешают.

### 4.6 Резервное копирование и восстановление

| Свойство | Значение |
| --- | --- |
| Формат | zip: `database.sqlite` (снимок через `sqlite3.backup`), каталог `documents/`, `manifest.json` с `created_at` и `kind` |
| Имя | `backup_<YYYYmmddHHMMSSffffff>_<kind>.zip`; `kind` ∈ `automatic`/`manual`/`safety` |
| `latest.zip` | обновляется для всех копий, кроме `safety` |
| Хранение | после обычной копии удаляются все старые `backup_*.zip` без `_safety`; записи `backup_records` не удаляются, поэтому список может ссылаться на отсутствующие файлы |
| Safety-копии | создаются перед восстановлением и не удаляются автоматически |
| Автоматические копии | планировщик раз в 900 секунд, первая — примерно через 15 минут после старта; состояние проекта не учитывается |
| Восстановление | `confirm=true`; проверка sha256 zip; safety-бэкап; распаковка; закрытие сессии и `engine.dispose()`; удаление `hackathon.db`, `-wal`, `-shm`; копирование БД и документов; `alembic stamp head` |
| Перезапуск | не выполняется; активные вкладки и сессии могут получить ошибки, сессии из восстановленной БД могут отсутствовать |
| Аудит | создание и восстановление не пишутся в журнал |
| Внешняя копия | Google Drive и другие внешние хранилища не используются |

### 4.7 Что попадает в журнал аудита

| Пишется | Не пишется |
| --- | --- |
| `bootstrap.admin_created`; `user.created`, `user.login_changed`, `user.name_changed`, `user.password_reset`, `user.deactivated`; `role.granted`, `role.revoked`; `ip.blocked`, `ip.unblocked`, `ip.limit_reset` | Вход и выход (они в `login_events`); чтение любых сущностей |
| `project.created`, `project.renamed`, `project.deadline_changed`, `project.completed`, `project.reopend` | Инциденты: создание, подтверждение, закрытие, комментарии |
| `column.created/updated/deleted`; `module.created/updated/deleted` | Документы: создание, сохранение, блокировки, корзина, изображения |
| `task.created/updated/moved/assignees_set/dependency_added/dependency_removed/checklist_added/time_adjusted` | Правка и удаление чек-листа; старт/пауза/остановка таймера |
| Песочница: `task.created`, `task.moved` для созданных задач | ИИ: настройки, запуск, исключение; бэкапы и восстановление; уведомления; правка самой записи аудита (только `AuditRevision`) |

## 5. Примеры запросов

Примеры предполагают backend на `http://127.0.0.1:8000` и cookie-jar `cookies.txt`. Синтаксис с одинарными кавычками — для bash/Git Bash; в PowerShell используйте `curl.exe` и двойные кавычки. Идентификаторы условны.

### 5.1 Вход

```bash
curl -i -c cookies.txt -H 'Content-Type: application/json' \
  -d '{"login":"admin","password":"change-me"}' \
  http://127.0.0.1:8000/api/v1/auth/login
```

Ожидается 200, `UserOut` и `Set-Cookie: session=...; HttpOnly; Max-Age=604800; Path=/; SameSite=lax`.

### 5.2 Текущий пользователь

```bash
curl -s -b cookies.txt http://127.0.0.1:8000/api/v1/auth/me
```

Ожидается 200 и `roles` с активными назначениями.

### 5.3 Создание задачи

```bash
curl -s -b cookies.txt -H 'Content-Type: application/json' \
  -d '{"title":"API-справочник","column_key":"backlog","priority":"high","estimate_seconds":7200,"tags":["docs"]}' \
  http://127.0.0.1:8000/api/v1/projects/1/tasks
```

Ожидается 200, `id`, `version=1`, `timer=null`.

### 5.4 Перемещение задачи

```bash
curl -s -b cookies.txt -H 'Content-Type: application/json' \
  -d '{"column_key":"in_progress","version":1}' \
  http://127.0.0.1:8000/api/v1/tasks/1/move
```

Ожидается 200 и `version=2`; при включённом у колонки `auto_start_timer` в ответе будет `timer.state="running"`. Повтор с `version=1` даст 409 `VERSION_CONFLICT`.

### 5.5 Запуск таймера

```bash
curl -s -b cookies.txt -X POST \
  http://127.0.0.1:8000/api/v1/tasks/1/timer/start
```

Ожидается 200 и `{"state":"running", ...}`; повторный вызов — 409 `TIMER_RUNNING`.

### 5.6 Создание инцидента

```bash
curl -s -b cookies.txt -H 'Content-Type: application/json' \
  -d '{"level":"yellow","title":"Не проходит сборка","description":"CI падает на шаге тестов","owner_id":2,"targets":[{"target_type":"task","target_id":1}]}' \
  http://127.0.0.1:8000/api/v1/projects/1/incidents
```

Ожидается 200, `status="open"`, событие `created`; владелец и капитаны получат уведомления.

### 5.7 Создание и сохранение документа

```bash
curl -s -b cookies.txt -H 'Content-Type: application/json' \
  -d '{"path":"docs/api.md","content":"# API"}' \
  http://127.0.0.1:8000/api/v1/projects/1/documents

curl -s -b cookies.txt -X PUT -H 'Content-Type: application/json' \
  -d '{"content":"# API v2","base_checksum":"<checksum из первого ответа>"}' \
  http://127.0.0.1:8000/api/v1/documents/1/content
```

Первый запрос вернёт `checksum`; второй с устаревшим `base_checksum` даст 409 `VERSION_CONFLICT`.

### 5.8 Запуск ИИ-советника

```bash
curl -s -b cookies.txt -X PATCH -H 'Content-Type: application/json' \
  -d '{"enabled":true}' \
  http://127.0.0.1:8000/api/v1/projects/1/ai/settings

curl -s -b cookies.txt -H 'Content-Type: application/json' \
  -d '{"trigger":"manual"}' \
  http://127.0.0.1:8000/api/v1/projects/1/ai/run
```

`PATCH` доступен только `captain/admin`; `run` — любому аутентифицированному. Ответ — mock-рекомендация с `provider` из настроек.

### 5.9 Бэкап и восстановление

```bash
curl -s -b cookies.txt -X POST http://127.0.0.1:8000/api/v1/admin/backups

curl -s -b cookies.txt http://127.0.0.1:8000/api/v1/admin/backups

curl -s -b cookies.txt -H 'Content-Type: application/json' \
  -d '{"confirm":true}' \
  http://127.0.0.1:8000/api/v1/admin/backups/1/restore
```

Без `confirm=true` — 422 `CONFIRM_REQUIRED`. После восстановления соединения с БД пересоздаются, сервер не перезапускается.

## 6. Чего в API нет

| Ожидалось или упоминалось | Фактически |
| --- | --- |
| `WS /api/v1/ws?project_id=...` и события `task.changed`, `timer.changed`, `incident.changed`, `notification.created`, `document.presence`, `dashboard.changed`, `ai.recommendation.created` | WebSocket отсутствует; фронтенд опрашивает API: доска — 1 с, инциденты и аналитика — 5 с, уведомления — 10 с |
| `GET/POST/PATCH /projects/{id}/ai/prompts` | Нет; промпт — поле `prompt` в `ai_settings`, отдельного CRUD нет; `triggers` хранятся, но планировщиком не используются |
| `POST /projects/{id}/clone` | Нет; клонирования, экспорта и архивации проекта нет |
| `POST /projects/{id}/backups`, `POST /projects/{id}/restore` | Нет; бэкапы только через `/admin/backups`, восстановление — `/admin/backups/{id}/restore` |
| Google Drive для внешней копии | Нет; `GOOGLE_DRIVE_FOLDER_ID` не используется |
| Реальная отправка в Telegram | Реализована через DPAPI и outbox; [подключение и ограничения](../docs/16-telegram-and-accounts.md) |
| CSRF-токены, `Secure`-cookie | Нет |
| UI документов | Исключён из продукта; API сохраняется |
| UI аудита | API есть; экран отсутствует |
| Удаление задачи, постоянное удаление документа, версии и папки документов | Нет; задача уходит в колонку `trashed`, документ — в мягкую корзину |
| Реактивация пользователя, самостоятельная смена пароля, удаление пользователя | Нет |
| Список IP-правил, счётчик непрочитанных уведомлений, отчёт/CSV, метрики | Нет |
| Ключи идемпотентности, `Retry-After`, 503 при недоступности интеграции | Нет; 429 только для входа и ИИ |
| Схема безопасности в OpenAPI | Нет; cookie-аутентификация в схеме не описана |

Фронтенд не использует 21 из 86 эндпоинтов `/api/v1`:

- документы — все 13: `GET/POST /projects/{id}/documents`, `GET /projects/{id}/documents/trash`, `GET /documents/{id}`, `GET/PUT /documents/{id}/content`, `POST/DELETE /documents/{id}/lock`, `POST /documents/{id}/heartbeat`, `DELETE /documents/{id}`, `POST /documents/{id}/restore`, `POST /projects/{id}/documents/images`, `GET /projects/{id}/documents/images/{filename}`;
- аудит — `GET /audit`, `GET /audit/{id}/revisions`, `PATCH /admin/audit/{id}`;
- `DELETE /admin/ip-rules/{id}` (блокировка ставится, снятие из UI недоступно);
- `POST /projects/{id}/ai/recommendations/{rec_id}/exclude`;
- `GET /projects/{id}`, `GET /tasks/{id}`, `GET /incidents/{id}`.

`GET /health` фронтенд также не вызывает — он предназначен для Docker healthcheck и эксплуатации.

## 7. Коды ошибок

| Код | HTTP | Когда возникает | Что делать клиенту |
| --- | --- | --- | --- |
| `UNAUTHENTICATED` | 401 | Нет cookie, сессия не найдена, истекла или отозвана, пользователь удалён | Вызвать `/auth/me`; при 401 показать вход |
| `BAD_CREDENTIALS` | 401 | Неверный логин или пароль | Показать ошибку; не повторять автоматически |
| `DEACTIVATED` | 403 | Аккаунт деактивирован при входе или в текущей сессии | Сообщить пользователю; обратиться к администратору |
| `IP_BLOCKED` | 403 | IP есть в `ip_rules` с действием `block` | Сообщить администратору; снять правило в БД/админке |
| `RATE_LIMITED` | 429 | ≥5 неудач на логин или ≥10 на IP за 15 минут; для ИИ — не-`manual` запуск раньше `interval_minutes` | Подождать; администратор может сбросить лимит IP; для ИИ — ручной запуск или позже |
| `FORBIDDEN` | 403 | Нет роли; попытка сменить дедлайн/название без прав; не капитан для confirm-red | Скрыть недоступное действие; проверить роли в `/auth/me` |
| `NOT_FOUND` | 404 | Нет сущности по id (проект, задача, инцидент, документ, пользователь, правило, бэкап, файл) | Обновить список/карточку; проверить id |
| `VALIDATION_ERROR` | 422 | Ошибка схемы тела/query/path или семантическая проверка через `api_error` | Показать `details.errors`; исправить payload |
| `HTTP_ERROR` | любой | Запасной код для `HTTPException` без конверта | Показать общее сообщение; залогировать |
| `VERSION_CONFLICT` | 409 | Устаревший `version` задачи или `base_checksum` документа | Перечитать сущность, повторить с новыми значениями |
| `PROJECT_COMPLETED` | 409 | Мутация в завершённом проекте (только там, где есть проверка) | Перевести UI в режим чтения; повторное открытие — голосованием |
| `COLUMN_NOT_FOUND` | 404 | `column_key` отсутствует на доске проекта | Обновить колонки; выбрать существующую |
| `COLUMN_PROTECTED` | 409 | Попытка удалить стартовую колонку | Запретить удаление в UI |
| `TIMER_RUNNING` | 409 | Повторный старт идущего таймера | Обновить состояние; не дублировать клик |
| `TIMER_NOT_RUNNING` | 409 | Пауза таймера, который не идёт | Обновить состояние |
| `TIMER_NOT_ACTIVE` | 409 | Остановка отсутствующего или уже остановленного таймера | Обновить состояние |
| `DOCUMENT_EXISTS` | 409 | Путь документа уже занят, включая корзину | Выбрать другой путь или восстановить из корзины |
| `DOCUMENT_LOCKED` | 409 | Активная блокировка документа принадлежит другому | Открыть только чтение; ждать TTL 5 минут |
| `AI_DISABLED` | 409 | ИИ-советник выключен в настройках | Капитану включить `enabled` |
| `INVALID_STATE` | 409 | Инцидент уже подтверждён/закрыт | Обновить карточку инцидента |
| `LOGIN_TAKEN` | 409 | Логин уже существует | Выбрать другой логин |
| `LAST_ADMIN` | 409 | Деактивация или отзыв роли последнего активного администратора | Сначала назначить другого администратора |
| `ROLE_EXISTS` | 409 | Такая активная роль уже назначена | Обновить список ролей |
| `IP_ALREADY_BLOCKED` | 409 | IP уже заблокирован | Использовать существующее правило |
| `CONFIRM_REQUIRED` | 422 | Восстановление бэкапа без `confirm=true` | Повторить с `{"confirm":true}` |
| `BACKUP_CORRUPT` | 409 | sha256 файла не совпал с записью | Выбрать другой бэкап; проверить диск |
| — (500) | 500 | Необработанное исключение: `IntegrityError`, отсутствующий проект в аналитике/ИИ, ошибка файла | Показать общую ошибку; повторить; проверить логи сервера; конверта нет |
| — (404/405 маршрута) | 404/405 | Неверный путь или метод | Исправить URL/метод; тело — `{"detail": ...}`, не конверт |

## 8. Расхождения и ограничения

### 8.1 Расхождения с прежней спецификацией API

| Прежняя формулировка | Фактическая реализация |
| --- | --- |
| WebSocket `/api/v1/ws` с событиями | Отсутствует; используется polling |
| `GET/POST/PATCH /projects/{id}/ai/prompts` | Отсутствует; промпт хранится в `ai_settings.prompt` |
| `POST /projects/{id}/ai/run`, `/backups`, `/restore`, `/clone` | Есть только `/ai/run`; бэкапы и восстановление — `/admin/backups...`; `/clone` нет |
| `GET /projects/{id}/audit` | Аудит глобальный: `GET /audit`, без фильтра по проекту |
| `GET/POST/PATCH /projects/{id}/columns`, `/modules` | Изменение — только по id: `PATCH /columns/{id}`, `PATCH /modules/{id}` |
| `POST /tasks/{id}/assignees` | Фактически `PUT /tasks/{id}/assignees` |
| «Дерево и редакторы» документов | Плоский список `DocumentOut[]`; `editors` — 0 или 1 текущий держатель блокировки; папок и версий нет |
| 403 при завершённом проекте | 409 `PROJECT_COMPLETED`, и только для части операций |
| 503 при недоступности внешней интеграции | Не используется; внешних вызовов нет |
| «Для параллельных изменений использовать `version` или `updated_at`» | `version` — только задачи; `updated_at` не проверяется; документы — `base_checksum` |
| «Голос капитана» за завершение | Требуется единогласие всех активных `captain` **и** `admin`; голоса глобальные |
| `GET/POST /admin/sandbox/*` | `/scenarios`, `/checks`, `/workspace`, `/run`, `/runs`, `/telegram`, `/reset` |
| «Таймеры и резервное копирование останавливаются» при завершении (docs/01) | Бэкапы продолжаются по расписанию; таймеры нельзя запускать, но уже идущий нельзя даже приостановить или остановить |
| «Из архива можно создать копию проекта» (docs/01) | Клонирования нет |
| Роли привязаны к проекту | Проверки игнорируют `project_id`; любая роль открывает все проекты |

### 8.2 Ограничения реализации

1. **Проектная изоляция отсутствует.** `require_member`, `require_captain_or_admin` и `require_admin` проверяют только факт активной роли; `project_id` из пути не сверяется с назначением. Пользователь с ролью в одном проекте читает и меняет данные любого другого (GAP-04).
2. **Read-only завершённого проекта частичный.** Разрешены `PATCH /tasks/{id}`, чек-лист, зависимости (удаление), `PATCH /projects/{id}`, колонки, модули, документы, ИИ, бэкапы и `jobs/run`. Запрещены создание/перемещение задачи, исполнители, добавление зависимости, таймеры, создание/подтверждение/закрытие инцидента. Повторное открытие голосованием работает.
3. **Единый формат ошибок не гарантирован.** 404/405 маршрута и 500 не имеют конверта; часть семантических ошибок отдаётся как 422 (`CONFIRM_REQUIRED`, расширение файла, уровень инцидента), часть — как 404 (`COLUMN_NOT_FOUND`).
4. **Явный `null` и дубли не валидируются.** `PATCH /tasks/{id}` с `"title": null` или `"tags": null` приводит к `IntegrityError` и 500; дубли `user_id` в исполнителях и целей инцидента могут дать 500 на уникальном индексе.
5. **Отсутствие проекта не всегда даёт 404.** `GET /projects/{id}/analytics` и `POST /projects/{id}/ai/run` падают с 500; `GET /projects/{id}/documents`, `/tasks`, `/incidents`, `/ai/recommendations` возвращают пустой список; `POST /projects/{id}/documents` при включённых FK даёт 500.
6. **Состав KPI.** С 2026-10-27 `active_timers` и `active_participants` в дашборде и аналитике ограничены выбранным проектом. `estimate_seconds`/`actual_seconds` включают задачи в `trashed`; `analytics.risks` тоже включает `trashed`, а `dashboard.risks` — нет.
7. **`Module.traffic_status` — мёртвое поле.** В `GET /projects/{id}/modules` всегда `green`; реальный светофор считается только в `analytics.modules` и `participants`.
8. **ИИ — mock с непостоянными настройками.** `GET /ai/settings` не сохраняет дефолтную строку; лимит частоты живёт в памяти процесса; `triggers` не используются; `excluded` ни на что не влияет; ключи Gemini/DeepSeek игнорируются; запуск доступен любому аутентифицированному.
9. **Документы доступны без членства и без проверки завершённости.** Блокировка не защищает сохранение: `PUT content` не проверяет владельца lock. Мягкое удаление оставляет файл и занимает путь. Нет лимита размера и проверки содержимого (SVG принимается). Проверка пути `startswith` не защищает от перехода в соседний каталог с тем же префиксом (`documents/1` → `documents/10`). Аудит не пишется.
10. **Бэкапы.** Записи `backup_records` не удаляются вместе с файлами, поэтому `GET /admin/backups` может показывать недоступные копии; safety-копии накапливаются; восстановление выполняется на живом процессе без перезапуска и без инвалидации сессий; распаковка zip не проверяет пути (zip slip); аудита нет; внешней копии нет.
11. **Health слишком слабый.** Проверяется только `SELECT 1`; запись в `data/` и миграции не проверяются, хотя комментарий в коде утверждает обратное.
12. **Безопасность сессий.** Cookie без `Secure`, CSRF-токенов нет, CORS ограничен dev-origin; общего rate limiting нет, только вход и ИИ; `APP_SECRET_KEY` не используется.
13. **Голосование о завершении глобальное.** Учитываются все активные `captain`+`admin`, а не только участники проекта; `reopen` возвращает `preparation`, а не `active`; в аудите опечатка `project.reopend`; автозавершения по дедлайну нет.
14. **Инциденты почти не валидируются.** `owner_id` и цели не проверяются на существование и принадлежность проекту; комментарии разрешены после закрытия и не проверяют завершённость; аудит не пишется; `traffic_status` красный только у подтверждённого красного инцидента.
15. **Таймеры.** Один таймер на задачу, но параллельные таймеры разных задач разрешены; любой member управляет таймером любой задачи; ручная корректировка на идущем таймере не закрывает сегмент; после завершения проекта нельзя остановить уже идущий таймер.
16. **Песочница пишет в рабочую БД.** Создаёт пользователей `alice`/`bob`/`cap` с паролем `sandbox-pass`, проект `Sandbox`, задачи и инциденты; сценарии не транзакционны целиком, часть эффектов коммитится внутри.
17. **Крупные списки без пагинации.** Задачи, инциденты, документы, пользователи и бэкапы возвращаются целиком; фильтры задач применяются в памяти.
18. **`deadline_msk` — не московское время.** Поле хранит наивный UTC; имя вводит в заблуждение, конвертации в MSK нет.
19. **Создание и удаление отвечают 200.** Клиенты, ожидающие 201/204, должны это учитывать.
20. **OpenAPI не описывает аутентификацию.** Cookie-сессия не объявлена как security scheme, автоматическая авторизация в Swagger UI недоступна.

## 9. Источники

| Что проверялось | Файлы |
| --- | --- |
| Сборка приложения, префиксы, CORS, планировщик | `backend/app/main.py` |
| Маршруты и обработчики | `backend/app/api/*.py` |
| Зависимости, роли, read-only | `backend/app/deps.py` |
| DTO и ограничения полей | `backend/app/schemas.py` |
| Формат ошибок | `backend/app/api/errors.py` |
| Бизнес-правила | `backend/app/services/*.py` |
| Клиент API и используемые методы | `frontend/src/api.ts`, `frontend/src/ui.tsx` |
| Фактическое поведение | `backend/tests/*.py` |
| Известные пробелы | `../docs/10-known-gaps-and-roadmap.md` |
