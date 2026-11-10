# HTTP API

## Контракты и доступ

Префикс пользовательского API — `/api/v1`; `/health` расположен отдельно. JSON-схемы определены в `backend/app/schemas.py`, `planning_schemas.py`, `operational_schemas.py`, `situation_schemas.py`, `telegram_schemas.py` и локальных схемах модулей API.

В изолированном режиме разработки FastAPI публикует `/docs` и `/openapi.json`. В managed эти маршруты выключены. OpenAPI описывает формат, но ограничения managed, транзакции и бизнес-правила нужно читать вместе с обработчиком/сервисом.

Вход: POST `/api/v1/auth/login` с JSON `{"login":"...","password":"..."}`. Сервер устанавливает HttpOnly-cookie `session`; отправляйте её в следующих запросах. GET `/auth/me` возвращает аккаунт, роли и managed. Logout отзывает сессию.

| Операция | Основная граница доступа |
| --- | --- |
| Чтение проекта/объектов | Активный участник проекта либо admin |
| Задачи, таймеры, инциденты | Проектная роль и специальные правила операции; чужие ID отклоняются |
| Изменение плана, настройки Argus/Telegram | captain своего проекта либо admin |
| Аккаунты, роли, IP, период проекта | admin |
| Подтверждение красного, корректировка времени | captain/admin |
| Завершение/открытие | Голосование капитанов по серверным правилам |
| Копия/restore/создание проекта в managed | Локальная панель; старые write API возвращают LOCAL_PANEL_REQUIRED |
| Sandbox | admin, только вне managed |

Точная зависимость прав находится в обработчике и `deps.py`; доступ к административной роли не равен участию капитана в конкретной операции.

## Версии, ошибки и время

PATCH задачи и move используют её `version`; план — проектную `revision`. Устаревшее значение даёт 409 VERSION_CONFLICT. Поля частичного PATCH обрабатываются через exclude_unset: отсутствие поля и null различаются.

Команда плана `op="link"` с `source_id` и `target_id` создаёт общую мягкую зависимость `after` у целевой задачи. Она возвращается в `predecessors` задачи и в `edges` плана. Команда `set_blocker` отдельно переключает тип существующей связи без изменения направления.

Опасные последствия изменения плана могут вернуть 409 PLANNING_PREVIEW с `details.token/changes/conflicts`. После просмотра повторяется тот же запрос с актуальными версиями и заголовком `X-Planning-Confirm`; это отдельный подтверждаемый протокол, не автоматический повтор после потери связи.

Типовой отказ:

```json
{"error":{"code":"VERSION_CONFLICT","message":"Задача изменена другим пользователем","details":{}}}
```

400/422 — неверные параметры/правила, 401 — вход, 403 — права, 404 — отсутствующий или недоступный объект, 409 — конфликт состояния/версии, 429 — лимит входа. Точный код важнее общего HTTP-статуса. Формат HTTP/validation-ошибок задаёт `api/errors.py`; необработанный сбой не обязан соответствовать этой схеме.

Длительности — секунды. База хранит naive UTC, ввод дат проекта и плана нормализуется в UTC; UI показывает МСК. ISO-значение без offset в ответе базы нужно трактовать по контракту как UTC, не как местное время браузера.

Общего idempotency key нет. Создание задачи принимает необязательный UUID `creation_key` и массив `assignees` с ровно одним основным исполнителем, если список не пуст. Задача, исполнители и уведомления сохраняются одной транзакцией. Повтор того же ключа, пользователя, проекта и тела возвращает ту же задачу; другое тело с этим ключом даёт 409 IDEMPOTENCY_CONFLICT. Ключ и отпечаток тела записаны в аудит создания; это не отдельная копия задачи. Для остальных объектов после потери ответа проверяйте состояние перед повтором. Клиентские NETWORK_ERROR/NETWORK_RESULT_UNKNOWN не являются серверными кодами.

Список задач и задачи в плане загружают исполнителей, связи, чек-листы, таймеры и инциденты пакетно: число SQL-запросов не растёт на каждую карточку. Полный состав DTO сохранён.

## Каталог маршрутов Aion

Каталог соответствует декораторам зарегистрированных модулей `backend/app/api`. Обработчик указан для поиска схем, зависимостей и тестов; тело запроса не следует выводить только из имени пути.

| Метод | Путь | Модуль / обработчик |
| --- | --- | --- |
| GET | `/api/v1/admin/users/{user_id}/deletion-preview` | `admin.deletion_preview` |
| DELETE | `/api/v1/admin/users/{user_id}` | `admin.delete_user` |
| GET | `/api/v1/admin/users` | `admin.list_users` |
| GET | `/api/v1/admin/roles` | `admin.list_roles` |
| POST | `/api/v1/admin/users` | `admin.create_user` |
| PATCH | `/api/v1/admin/users/{user_id}` | `admin.patch_user` |
| POST | `/api/v1/admin/users/{user_id}/password-reset` | `admin.password_reset` |
| POST | `/api/v1/admin/users/{user_id}/deactivate` | `admin.deactivate` |
| POST | `/api/v1/admin/roles` | `admin.assign_role` |
| DELETE | `/api/v1/admin/roles/{assignment_id}` | `admin.revoke_role` |
| GET | `/api/v1/admin/login-events` | `admin.login_events` |
| POST | `/api/v1/admin/ip-rules` | `admin.block_ip` |
| DELETE | `/api/v1/admin/ip-rules/{rule_id}` | `admin.unblock_ip` |
| POST | `/api/v1/admin/ip-rules/reset` | `admin.reset_ip_limit` |
| PATCH | `/api/v1/admin/audit/{entry_id}` | `admin.edit_audit` |
| GET | `/api/v1/projects/{project_id}/analytics` | `analytics.get_analytics` |
| GET | `/api/v1/audit` | `audit.audit_list` |
| GET | `/api/v1/audit/{entry_id}/revisions` | `audit.audit_revisions` |
| POST | `/api/v1/auth/login` | `auth.login` |
| POST | `/api/v1/auth/logout` | `auth.logout` |
| GET | `/api/v1/auth/me` | `auth.me` |
| GET | `/api/v1/projects/{project_id}/dashboard` | `dashboard.dashboard` |
| GET | `/api/v1/projects/{project_id}/documents` | `documents.list_documents` |
| GET | `/api/v1/projects/{project_id}/documents/trash` | `documents.list_trash` |
| POST | `/api/v1/projects/{project_id}/documents` | `documents.create_document` |
| GET | `/api/v1/documents/{document_id}` | `documents.get_document` |
| GET | `/api/v1/documents/{document_id}/content` | `documents.get_content` |
| PUT | `/api/v1/documents/{document_id}/content` | `documents.save_content` |
| POST | `/api/v1/documents/{document_id}/lock` | `documents.lock_document` |
| DELETE | `/api/v1/documents/{document_id}/lock` | `documents.unlock_document` |
| POST | `/api/v1/documents/{document_id}/heartbeat` | `documents.heartbeat` |
| DELETE | `/api/v1/documents/{document_id}` | `documents.trash_document` |
| POST | `/api/v1/documents/{document_id}/restore` | `documents.restore_document` |
| POST | `/api/v1/projects/{project_id}/documents/images` | `documents.upload_image` |
| GET | `/api/v1/projects/{project_id}/documents/images/{filename}` | `documents.get_image` |
| GET | `/health` | `health.health` |
| GET | `/api/v1/projects/{project_id}/incidents` | `incidents.list_incidents` |
| POST | `/api/v1/projects/{project_id}/incidents` | `incidents.create_incident` |
| GET | `/api/v1/incidents/{incident_id}` | `incidents.get_incident` |
| POST | `/api/v1/incidents/{incident_id}/confirm-red` | `incidents.confirm_red` |
| POST | `/api/v1/incidents/{incident_id}/resolve` | `incidents.resolve_incident` |
| POST | `/api/v1/incidents/{incident_id}/events` | `incidents.add_comment` |
| POST | `/api/v1/notifications/{notification_id}/open` | `notifications.open_notification` |
| GET | `/api/v1/notifications` | `notifications.list_notifications` |
| POST | `/api/v1/notifications/{notification_id}/read` | `notifications.mark_read` |
| POST | `/api/v1/notifications/read-all` | `notifications.mark_all_read` |
| DELETE | `/api/v1/notifications/{notification_id}` | `notifications.delete_notification` |
| DELETE | `/api/v1/notifications` | `notifications.clear_all` |
| POST | `/api/v1/admin/backups` | `operations.create_backup` |
| GET | `/api/v1/admin/backups` | `operations.list_backups` |
| POST | `/api/v1/admin/backups/{backup_id}/restore` | `operations.restore_backup` |
| POST | `/api/v1/projects/{project_id}/completion-votes` | `operations.completion_vote` |
| POST | `/api/v1/admin/jobs/run` | `operations.run_jobs` |
| GET | `/api/v1/projects/{project_id}/planning` | `planning.read_plan` |
| POST | `/api/v1/projects/{project_id}/planning` | `planning.edit_plan` |
| GET | `/api/v1/projects` | `projects.list_projects` |
| POST | `/api/v1/projects` | `projects.create_project` |
| GET | `/api/v1/projects/{project_id}` | `projects.get_project` |
| PATCH | `/api/v1/projects/{project_id}` | `projects.patch_project` |
| GET | `/api/v1/projects/{project_id}/columns` | `projects.list_columns` |
| POST | `/api/v1/projects/{project_id}/columns` | `projects.create_column` |
| PATCH | `/api/v1/columns/{column_id}` | `projects.patch_column` |
| DELETE | `/api/v1/columns/{column_id}` | `projects.delete_column` |
| GET | `/api/v1/projects/{project_id}/modules` | `projects.list_modules` |
| POST | `/api/v1/projects/{project_id}/modules` | `projects.create_module` |
| PATCH | `/api/v1/modules/{module_id}` | `projects.patch_module` |
| DELETE | `/api/v1/modules/{module_id}` | `projects.delete_module` |
| GET | `/api/v1/projects/{project_id}/participants` | `projects.list_participants` |
| GET | `/api/v1/projects/{project_id}/events` | `realtime.events` |
| GET | `/api/v1/admin/sandbox/workspace` | `sandbox.workspace` |
| GET | `/api/v1/admin/sandbox/checks` | `sandbox.check_catalog` |
| POST | `/api/v1/admin/sandbox/reset` | `sandbox.reset` |
| GET | `/api/v1/admin/sandbox/telegram` | `sandbox.telegram_deliveries` |
| GET | `/api/v1/admin/sandbox/scenarios` | `sandbox.list_scenarios` |
| POST | `/api/v1/admin/sandbox/run` | `sandbox.run_scenario` |
| GET | `/api/v1/admin/sandbox/runs` | `sandbox.list_runs` |
| GET | `/api/v1/projects/{project_id}/situations/settings` | `situations.settings` |
| PUT | `/api/v1/projects/{project_id}/situations/settings` | `situations.save` |
| GET | `/api/v1/projects/{project_id}/situations/history` | `situations.history` |
| GET | `/api/v1/tasks/{task_id}/incident-cascade` | `tasks.incident_cascade` |
| GET | `/api/v1/tasks/{task_id}/incident-impact` | `tasks.incident_impact` |
| GET | `/api/v1/projects/{project_id}/tasks` | `tasks.list_tasks` |
| POST | `/api/v1/projects/{project_id}/tasks` | `tasks.create_task` |
| GET | `/api/v1/tasks/{task_id}` | `tasks.get_task` |
| GET | `/api/v1/tasks/{task_id}/history` | `tasks.task_history` |
| PATCH | `/api/v1/tasks/{task_id}` | `tasks.patch_task` |
| POST | `/api/v1/tasks/{task_id}/move` | `tasks.move_task` |
| PUT | `/api/v1/tasks/{task_id}/assignees` | `tasks.set_assignees` |
| POST | `/api/v1/tasks/{task_id}/dependencies` | `tasks.add_dependency` |
| DELETE | `/api/v1/tasks/{task_id}/dependencies/{predecessor_id}` | `tasks.remove_dependency` |
| POST | `/api/v1/tasks/{task_id}/checklist` | `tasks.add_checklist_item` |
| PATCH | `/api/v1/checklist/{item_id}` | `tasks.patch_checklist_item` |
| DELETE | `/api/v1/checklist/{item_id}` | `tasks.delete_checklist_item` |
| GET | `/api/v1/telegram/bot` | `telegram.bot` |
| DELETE | `/api/v1/telegram/bot/key` | `telegram.delete_key` |
| GET | `/api/v1/projects/{project_id}/telegram` | `telegram.settings` |
| PUT | `/api/v1/projects/{project_id}/telegram` | `telegram.save` |
| POST | `/api/v1/projects/{project_id}/telegram/test` | `telegram.test` |
| GET | `/api/v1/projects/{project_id}/telegram/deliveries` | `telegram.deliveries` |
| POST | `/api/v1/projects/{project_id}/telegram/deliveries/{delivery_id}/retry` | `telegram.retry` |
| POST | `/api/v1/tasks/{task_id}/timer/start` | `timers.timer_start` |
| POST | `/api/v1/tasks/{task_id}/timer/pause` | `timers.timer_pause` |
| POST | `/api/v1/tasks/{task_id}/timer/stop` | `timers.timer_stop` |
| POST | `/api/v1/tasks/{task_id}/time-adjustment` | `timers.time_adjustment` |

## Особые протоколы

Документы используют checksum для согласованного сохранения и lock/heartbeat с TTL 5 минут; содержимое и метаданные хранятся раздельно. Изображения передаются multipart, не JSON. Экрана документов в UI нет.

SSE `events` передаёт версии проекта, перепроверяет доступ и не держит долгую SQLite-транзакцию; после подключения клиент перечитывает актуальные данные. Глобального лимита SSE нет.

Повтор доставки Hermes требует accept_duplicate_risk для uncertain. Удаление пользователя требует confirm=true, preview_version и проверенных замен; обзор устаревает при конкурентном изменении связей.

## Локальный API Ouroboros

Это отдельный сервер loopback с capability → cookie `hcc_control`, Host/Origin-проверками. Его маршруты **не имеют** префикса `/api/v1` и не доступны через пользовательскую сессию Aion.

`control/server.py` определяет `/api/status`, операции `/api/platforms/*`, проверку зависимостей, настройки ключей/туннеля, `/api/action/{action}`, загрузку копии и inspect/apply/activate восстановления. Запросы setup/restore и показ ключа требуют локальной авторизации. Этот API не является удалённым универсальным Docker/shell-интерфейсом.

[Потоки](07-flows.md) · [Безопасность](06-security-and-tests.md) · [Ограничения](../docs/10-known-limitations.md)
