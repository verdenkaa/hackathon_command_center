# Спецификации реализации (as-built)

Этот каталог описывает **фактический прототип**, а не первоначальный замысел. Спецификации синхронизированы с кодом в `backend/app` и `frontend/src`: если документ и код расходятся, источником истины считается код, а расхождение нужно исправить в документе.

Исходные требования и продуктовые решения находятся в [../docs/](../docs/README.md); трассировка требований к коду и тестам — в [../docs/07-implementation-status.md](../docs/07-implementation-status.md).

| Файл | Содержание | Основные источники в коде |
| --- | --- | --- |
| [01-stack-and-layout.md](01-stack-and-layout.md) | Стек, структура репозитория, процессы, конфигурация, Docker, миграции | `backend/requirements.txt`, `frontend/package.json`, `Dockerfile`, `docker-compose.yml`, `start.*`, `backend/app/config.py` |
| [02-data-model.md](02-data-model.md) | Таблицы, поля, связи, перечисления, инварианты, правила миграций | `backend/app/db/models.py`, `backend/alembic/versions/` |
| [03-api.md](03-api.md) | Полный справочник HTTP API, права, ошибки, примеры | `backend/app/api/`, `backend/app/deps.py`, `backend/app/schemas.py` |
| [04-frontend.md](04-frontend.md) | SPA: компоненты, состояние, опрос данных, экраны, UI-примитивы, ограничения | `frontend/src/` |
| [05-jobs-and-integrations.md](05-jobs-and-integrations.md) | Планировщик, бэкапы/восстановление, Telegram, ИИ, внешние интеграции | `backend/app/main.py`, `backend/app/services/`, `backend/app/integrations/` |
| [06-security-and-tests.md](06-security-and-tests.md) | Аутентификация, авторизация, защита данных, тестовый набор, риски | `backend/app/security.py`, `services/auth_service.py`, `deps.py`, `backend/tests/` |
| [07-flows.md](07-flows.md) | Сквозные сценарии: вход, задача, таймер, инцидент, документ, ИИ, бэкап, завершение проекта | `backend/app/api/`, `backend/app/services/` |

## Соглашения

- Все пути указаны относительно корня репозитория.
- Время в БД — наивный UTC; в документе это не повторяется у каждого поля.
- Примеры запросов предполагают запущенный backend на `http://127.0.0.1:8000`.
- Документ описывает только то, что есть в коде. Возможности из исходных требований, которых нет в реализации, перечислены в разделах «Расхождения» и в [../docs/10-known-gaps-and-roadmap.md](../docs/10-known-gaps-and-roadmap.md).

## Поддержка

Спецификации обновляются вместе с кодом: см. таблицу «Изменение в коде → что обновить» в [../docs/README.md](../docs/README.md). Каждая спецификация начинается с назначения и списка источников, чтобы правку можно было проверить по коду.
