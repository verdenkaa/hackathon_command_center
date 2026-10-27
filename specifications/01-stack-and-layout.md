# Стек и структура (as-built)

Документ описывает фактическое состояние репозитория, а не исходные требования из `docs/`. Проверено по `backend/requirements.txt`, `frontend/package.json`, конфигурации, миграциям, скриптам запуска и тестам. Потоки выполнения — в [07-flows.md](07-flows.md).

## 1. Фактический стек

### Backend

| Компонент | Версия / диапазон | Где зафиксировано | Использование |
| --- | --- | --- | --- |
| Python | 3.12 | `Dockerfile` (`python:3.12-slim`); локально 3.12.6 | runtime |
| FastAPI | `>=0.115,<1` | [requirements.txt](../backend/requirements.txt) | HTTP API, DI |
| Uvicorn | `>=0.30,<1`, extra `standard` | там же | ASGI-сервер, один процесс |
| SQLAlchemy | `>=2.0,<2.1` | там же | ORM 2.0 (`Mapped`, `mapped_column`) |
| Alembic | `>=1.13,<2` | там же | миграции, автоприменение при старте |
| Pydantic | `>=2.7,<3` | там же | DTO и валидация |
| pydantic-settings | `>=2.3,<3` | там же | `Settings`, чтение `.env` |
| python-multipart | `>=0.0.9` | там же | загрузка изображений документов |
| bcrypt | `>=4.1,<5` | там же | хеширование паролей |
| pytest | `>=8,<9` | там же | тесты |
| pytest-asyncio | `>=0.23,<1` | там же | объявлен, но асинхронных тестов нет |
| httpx | `>=0.27,<1` | там же | транспорт `fastapi.testclient.TestClient` |
| SQLite | стандартная библиотека Python | [session.py](../backend/app/db/session.py) | БД, WAL, `foreign_keys=ON` |

Версии точными пинами не зафиксированы: диапазоны в `requirements.txt`, lock-файла Python нет. Версия SQLite определяется Python/образом.

### Frontend

| Компонент | Версия | Использование |
| --- | --- | --- |
| React / React DOM | `^18.3.1` | UI, локальное состояние |
| TypeScript | `^5.5.3` | строгий режим (`strict: true`, `noEmit: true`) |
| Vite | `^5.4.0` | dev-сервер и сборка |
| @vitejs/plugin-react | `^4.3.1` | JSX/HMR |
| @types/react, @types/react-dom | `^18.3.3`, `^18.3.0` | типы |

Скрипты: `dev`, `build`, `preview` ([package.json](../frontend/package.json)). Скриптов `test`, `lint`, `typecheck` нет; `build` запускает только `vite build`, без `tsc`. Стили — один [index.css](../frontend/src/index.css), без CSS-фреймворка.

### Что не используется

| Ожидалось в черновике | Факт |
| --- | --- |
| TanStack Query | нет в зависимостях; `useEffect`/`useState` + `fetch` |
| Tailwind CSS, shadcn/ui | нет; чистый CSS и собственные классы |
| React Router | нет; вкладки в состоянии `App.tsx` |
| Redux/Zustand и другой state manager | нет |
| WebSocket | нет ни на backend, ни на frontend; опрос интервалами |
| UI документов | Исключён из продукта; существующие файлы и API сохраняются |
| Vitest, React Testing Library, Playwright | нет; frontend-тестов нет |
| ESLint, Prettier | конфигов нет |
| axios | нет; нативный `fetch` |
| SDK Gemini/DeepSeek, Telegram, Google Drive | нет; только HTTP-заготовка Telegram в лог |
| Отдельный frontend-контейнер / nginx | нет; Docker поднимает только API |

## 2. Дерево репозитория

```text
hackaton2026/
├─ backend/
│  ├─ app/
│  │  ├─ api/                 # 15 роутеров: admin, ai, analytics, audit, auth,
│  │  │                       # dashboard, documents, health, incidents, notifications,
│  │  │                       # operations, projects, sandbox, tasks, timers; errors.py
│  │  ├─ services/            # 14 модулей: ai, analytics, audit, auth_service, backup,
│  │  │                       # board, bootstrap, documents, incidents, jobs,
│  │  │                       # notifications, sandbox, tasks, timers
│  │  ├─ db/                  # base.py (Base), models.py (27 таблиц), session.py (engine)
│  │  ├─ integrations/        # telegram.py — mock/stub, реальной отправки нет
│  │  ├─ main.py              # create_app, lifespan, scheduler, run_migrations
│  │  ├─ config.py            # Settings, PROJECT_ROOT, sqlalchemy_url
│  │  ├─ deps.py              # get_db, get_current_user, require_*, ensure_project_active
│  │  ├─ security.py          # bcrypt, token_urlsafe(32), sha256
│  │  ├─ schemas.py           # Pydantic DTO
│  │  └─ timeutil.py          # наивный UTC, to_naive_utc
│  ├─ alembic/
│  │  ├─ env.py               # URL из Settings, metadata из Base
│  │  ├─ script.py.mako
│  │  └─ versions/            # 8 ревизий, head = 38bb310f4d87
│  ├─ tests/                  # conftest.py, helpers.py, 15 test_*.py, 84 теста
│  ├─ alembic.ini
│  ├─ pytest.ini
│  └─ requirements.txt
├─ frontend/
│  ├─ src/
│  │  ├─ App.tsx              # вход, вкладки, логин, уведомления
│  │  ├─ Board.tsx            # доска, создание/панель задачи, таймеры
│  │  ├─ Incidents.tsx        # инциденты
│  │  ├─ Analytics.tsx        # дашборд/аналитика
│  │  ├─ Admin.tsx            # пользователи, роли, IP, бэкапы, журнал
│  │  ├─ Sandbox.tsx          # админ-песочница
│  │  ├─ Settings.tsx         # проект, колонки, модули, ИИ, завершение
│  │  ├─ api.ts               # типы и клиент fetch, project id в localStorage
│  │  ├─ ui.tsx               # общие компоненты и форматирование
│  │  ├─ main.tsx
│  │  └─ index.css
│  ├─ index.html
│  ├─ package.json
│  ├─ package-lock.json
│  ├─ tsconfig.json
│  └─ vite.config.ts
├─ data/                      # runtime, вне Git: БД, документы, бэкапы
├─ docs/                      # продуктовые требования 01–06 + agents_plan + README
├─ specifications/            # as-built 01–07
├─ Dockerfile
├─ docker-compose.yml
├─ start.ps1 / start.bat / start.sh
├─ .env.example
├─ .gitignore
├─ README.md
└─ AGENTS.md
```

Ключевые точки входа: [main.py](../backend/app/main.py) (`create_app`, `lifespan`), [config.py](../backend/app/config.py), [session.py](../backend/app/db/session.py), [models.py](../backend/app/db/models.py), [deps.py](../backend/app/deps.py), [api/errors.py](../backend/app/api/errors.py), [api.ts](../frontend/src/api.ts), [Board.tsx](../frontend/src/Board.tsx).

Каталога `auth/`, `domain/`, `jobs/`, `operations/` из черновика нет: их роли выполняют `services/`, `api/` и `deps.py`. Отдельного каталога `sandbox` нет: `api/sandbox.py` + `services/sandbox.py`.

## 3. Процессы и порты

| Процесс | Команда | Адрес | Особенности |
| --- | --- | --- | --- |
| Backend | из `backend/`: `python -m uvicorn app.main:app --host 127.0.0.1 --port 8000` | http://127.0.0.1:8000 | при старте применяет миграции, создаёт bootstrap-данные, запускает поток планировщика |
| Frontend (dev) | из `frontend/`: `npm run dev` | http://localhost:5173 | Vite; прокси `/api` и `/health` на `http://127.0.0.1:8000` |
| Docker | `docker compose up --build` | http://127.0.0.1:8000 | только API; frontend в образ не входит |

`vite.config.ts` задаёт `port: 5173` без `strictPort` и без `host`, поэтому при занятом порте Vite может выбрать другой, а доступ по сети по умолчанию не открыт. Прокси не переписывает путь: `/api/...` приходит в FastAPI как есть. CORS разрешает только `http://localhost:5173` и `http://127.0.0.1:5173` с credentials; при работе через прокси запросы same-origin и CORS не участвует.

Порядок запуска: сначала backend (ему нужны миграции и bootstrap), затем frontend; открывать `http://localhost:5173`. Обратный порядок не ломает запуск, но запросы UI до готовности API возвращают ошибку сети.

| Скрипт | Поведение |
| --- | --- |
| [start.ps1](../start.ps1) | создаёт `.venv` и ставит `requirements.txt`, если нет; `npm install`, если нет `frontend/node_modules`; запускает backend и frontend в отдельных процессах/окнах |
| [start.bat](../start.bat) | то же для cmd: два окна `cmd /k` |
| [start.sh](../start.sh) | то же для Git Bash; путь к интерпретатору — `.venv/Scripts/python.exe` (Windows), на Linux/macOS не работает; оба процесса в фоне, `wait` |

Скрипты не создают `.env` и не останавливают прежние процессы; автозапуска после перезагрузки, службы Windows или планировщика нет. При отсутствии `.env` действуют дефолты `admin` / `change-me` и корневая `data/`.

## 4. Конфигурация

`Settings` наследует `BaseSettings`; `.env` читается только из корня репозитория (`PROJECT_ROOT/.env`), переменные окружения имеют приоритет над `.env`, лишние ключи игнорируются (`extra="ignore"`). Настройки создаются один раз при импорте `app.config`.

| Переменная | Дефолт | Назначение | Секрет | Фактическое использование |
| --- | --- | --- | --- | --- |
| `APP_ENV` | `development` | метка среды | нет | нигде не читается |
| `APP_SECRET_KEY` | `change-me` | «секрет приложения» | да | нигде не используется: cookie не подписывается, токен случайный, в БД sha256 |
| `APP_HOST` | `127.0.0.1` | хост | нет | приложением не читается; хост задаёт CLI/Docker CMD |
| `APP_PORT` | `8000` | порт | нет | приложением не читается; порт задаёт CLI/Docker CMD |
| `APP_DATA_DIR` | `<корень>/data` (абсолютный) | каталог данных | нет | `settings.data_dir`; от него строятся БД, документы, бэкапы; каталог создаётся при импорте `db.session` |
| `DATABASE_URL` | `""` | URL БД | может содержать пароль | если пусто — `sqlite:///<APP_DATA_DIR>/hackathon.db`; иначе используется дословно |
| `APP_FIRST_ADMIN_LOGIN` | `admin` | логин первого админа | нет | только `bootstrap()` |
| `APP_FIRST_ADMIN_PASSWORD` | `change-me` | пароль первого админа | да | только `bootstrap()`; bcrypt-хеш в БД |
| `APP_FIRST_ADMIN_NAME` | `Administrator` | отображаемое имя | нет | только `bootstrap()` |
| `TELEGRAM_BOT_TOKEN` | `""` | токен бота | да | только выбор ветки лога в `integrations/telegram.py`; HTTP-вызовов нет |
| `TELEGRAM_CHAT_ID` | `""` | чат | да | там же |
| `AI_GEMINI_API_KEY` | `""` | ключ Gemini | да | не используется |
| `AI_DEEPSEEK_API_KEY` | `""` | ключ DeepSeek | да | не используется |
| `AI_PRIORITY_PROVIDER` | `gemini` | приоритет провайдера | нет | не используется; провайдер хранится в `ai_settings.priority_provider` |
| `GOOGLE_DRIVE_FOLDER_ID` | `""` | папка Drive | да | не используется |
| `FXTUNNEL_TOKEN` | `""` | токен туннеля | да | не используется |

Правила путей:

- `PROJECT_ROOT` вычисляется от `__file__` и не зависит от CWD; дефолт `APP_DATA_DIR` абсолютный.
- Если `DATABASE_URL`/`APP_DATA_DIR` заданы относительными, они разрешаются от текущего рабочего каталога процесса. Скрипты запускают uvicorn из `backend/`, поэтому `.env.example` (`APP_DATA_DIR=./data`, `DATABASE_URL=sqlite:///./data/hackathon.db`) уводит данные в `backend/data/`, а не в корневую `data/`. Docker задаёт абсолютные `/data`.
- `DATABASE_URL` с не-SQLite URL не поддерживается практически: `services/backup.py:db_file_path()` понимает только `sqlite:///`, иначе трактует строку как путь.
- `.env` в репозитории отсутствует; `.env.example` — шаблон, а не автоматически применяемый файл.

## 5. Хранение данных

```text
data/
├─ hackathon.db           # SQLite (по умолчанию)
├─ hackathon.db-wal       # WAL-журнал, появляется при работе
├─ hackathon.db-shm       # shared-memory файл WAL
├─ documents/
│  └─ <project_id>/
│     ├─ <path>.md        # Markdown, UTF-8, дерево каталогов произвольное
│     └─ assets/
│        └─ <uuid>.<ext>  # png/jpg/jpeg/gif/webp/svg
└─ backups/
   ├─ backup_<timestamp>_<kind>.zip   # automatic | manual | safety
   └─ latest.zip                      # копия последнего не-safety бэкапа
```

- SQLite: `journal_mode=WAL`, `foreign_keys=ON` на каждом соединении, `check_same_thread=False`, `timeout=30`, `pool_pre_ping=True`. Отдельного `busy_timeout` нет; расчёт на один процесс-писатель.
- Документы лежат вне БД; в `documents` хранятся путь, автор, sha256, флаг корзины и время. Блокировки — в `document_locks`.
- Бэкап — zip: `database.sqlite` (снимок через `sqlite3.Connection.backup`, не копирование «на живую»), `documents/`, `manifest.json` с `created_at` и `kind`. `latest.zip` обновляется только для `manual`/`automatic`.
- В Git не должны попадать: `data/`, `.env`, `*.db`, `*.db-wal`, `*.db-shm`, `.venv/`, `frontend/node_modules/`, `frontend/dist/`, `.tmp/`, `backend/tests/.tmp/`, `__pycache__/`, `.pytest_cache/`, `.dsh/`. Это покрыто [.gitignore](../.gitignore).
- В текущем рабочем каталоге `data/documents/` пуст, в `data/backups/` один `automatic`-архив и `latest.zip`; `data/hackathon.db` находится на ревизии `bed2ce42ab1b` (см. раздел 7).

## 6. Docker

[Dockerfile](../Dockerfile): `python:3.12-slim`, `pip install -r requirements.txt`, копирование только `backend/`, `WORKDIR /app/backend`, `EXPOSE 8000`, `CMD uvicorn app.main:app --host 0.0.0.0 --port 8000`. Пользователь не понижен, frontend и статика не копируются, healthcheck в Dockerfile нет.

[docker-compose.yml](../docker-compose.yml): один сервис `app`, `build: .`, `restart: unless-stopped`, `env_file: .env` (файл обязателен), переменные `APP_HOST=0.0.0.0`, `APP_PORT=8000`, `APP_DATA_DIR=/data`, `DATABASE_URL=sqlite:////data/hackathon.db`, порт `8000:8000`, том `./data:/data`, healthcheck `python -c "urllib.request.urlopen('http://localhost:8000/health')"` с интервалом 15 с, timeout 5 с, 3 повторами и `start_period` 30 с.

| Аспект | Прямой запуск | Docker |
| --- | --- | --- |
| Хост/порт | CLI-аргументы `127.0.0.1:8000` | `0.0.0.0:8000` из CMD, `APP_HOST`/`APP_PORT` не влияют |
| БД | `data/` относительно CWD или дефолт корня | абсолютная `/data/hackathon.db` |
| Frontend | `npm run dev`, порт 5173 | отсутствует; на `/` API отдаёт 404 |
| `.env` | опционален | обязателен для compose |
| Миграции/bootstrap | в `lifespan` | там же |
| Перезапуск | вручную/скриптом | `restart: unless-stopped` + healthcheck (сам по себе не перезапускает unhealthy-контейнер) |

Чего нет: frontend-сервиса/nginx, Autoheal, Uptime Kuma, Docker socket, меток для autoheal, fxTunnel, отдельного тома для бэкапов, non-root пользователя, `.dockerignore`. Из-за отсутствия `.dockerignore` в контекст сборки попадают `.venv/`, `data/`, `frontend/node_modules/`, `frontend/dist/`, `backend/tests/.tmp/` и `.dsh/`.

## 7. Alembic

Миграции применяются автоматически в `lifespan` до bootstrap: `run_migrations()` создаёт `Config` из `backend/alembic.ini`, задаёт абсолютный `script_location` и вызывает `command.upgrade(cfg, "head")`. `stamp_head()` используется после восстановления БД и только помечает схему текущей, не выполняя DDL.

[env.py](../backend/alembic/env.py) импортирует `Base` и `models`, подменяет `sqlalchemy.url` на `settings.sqlalchemy_url`, поддерживает offline/online. `alembic.ini` содержит `prepend_sys_path = .` и декоративный URL `sqlite:///./data/hackathon.db`, который перекрывается `env.py`.

Цепочка ревизий (head → корень):

| Ревизия | Файл | down_revision | Содержание |
| --- | --- | --- | --- |
| `38bb310f4d87` | `column_timer_rules.py` | `bed2ce42ab1b` | `board_columns.auto_start_timer`, `auto_stop_timer` |
| `bed2ce42ab1b` | `task_link_types.py` | `70df8d8dfcdd` | `task_dependencies.link_type` |
| `70df8d8dfcdd` | `sandbox.py` | `96cd78ac8062` | `sandbox_runs` |
| `96cd78ac8062` | `backups_completion.py` | `435366661053` | `backup_records`, `completion_votes` |
| `435366661053` | `documents_ai.py` | `bff78085fd9d` | `documents`, `document_locks`, `ai_settings`, `ai_recommendations` |
| `bff78085fd9d` | `incidents_notifications.py` | `f0c4c14d1a18` | `incidents`, `incident_targets`, `incident_events`, `notifications` |
| `f0c4c14d1a18` | `board_tasks_timers.py` | `ae5d65fc0a23` | `board_columns`, `modules`, `tasks`, `task_assignees`, `task_dependencies`, `checklist_items`, `task_timers`, `timer_segments` |
| `ae5d65fc0a23` | `initial.py` | `None` | пользователи, проекты, роли, сессии, входы, IP, аудит |

Команды (из `backend/`, чтобы работал `prepend_sys_path` и импорт `app`):

```powershell
..\.venv\Scripts\python.exe -m alembic current
..\.venv\Scripts\python.exe -m alembic history
..\.venv\Scripts\python.exe -m alembic upgrade head
..\.venv\Scripts\python.exe -m alembic revision --autogenerate -m "add something"
```

Ограничения:

- Автосгенерированные ревизии `38bb310f4d87` и `bed2ce42ab1b` добавляют `NOT NULL`-колонки без `server_default`. На пустой таблице SQLite это допускает, на непустой — нет.
- В текущем рабочем каталоге `data/hackathon.db` имеет `alembic_version = bed2ce42ab1b`, а в `board_columns` нет `auto_start_timer`/`auto_stop_timer`. Проверка на копии БД: `alembic upgrade head` падает на `38bb310f4d87` с `sqlite3.OperationalError: Cannot add a NOT NULL column with default value NULL`, потому что таблица уже содержит 9 стартовых колонок проекта. Следствие: запуск с этим файлом не пройдёт `run_migrations()`. На пустой БД цепочка проходит до `38bb310f4d87` (проверено).
- Тесты Alembic не используют: схема создаётся `Base.metadata.create_all` (см. раздел 8), поэтому расхождение «модели ↔ миграции» тестами не ловится.
- Downgrade-пути есть, но не тестируются; миграции данных нет.

## 8. Тесты

[pytest.ini](../backend/pytest.ini): `pythonpath = .`, `testpaths = tests`, `addopts = -p no:cacheprovider`.

[conftest.py](../backend/tests/conftest.py) до импорта приложения задаёт `DATABASE_URL=sqlite:///tests/.tmp/test.db`, `APP_DATA_DIR=tests/.tmp`, `APP_FIRST_ADMIN_*` (`admin` / `admin-pass-123` / `Test Admin`), `APP_ENV=test`. Создаёт отдельный engine с `NullPool`; фикстура `client` делает `drop_all`/`create_all` (без Alembic), вызывает `bootstrap()`, подменяет `get_db` и отдаёт `TestClient(app)`. Файлы `backend/tests/.tmp/` — артефакты тестов, в Git не входят.

Команды:

```powershell
Set-Location backend
..\.venv\Scripts\python.exe -m pytest -q                 # 84 passed
..\.venv\Scripts\python.exe -m pytest tests/test_timers.py -q
..\.venv\Scripts\python.exe -m pytest -k "incident" -q
```

15 файлов `test_*.py`, 84 теста: admin 10, ai 6, analytics 7, audit 2, auth 9, board 6, dashboard 3, documents 4, incidents 7, integration 1, notifications 4, operations 5, sandbox 2, tasks 10, timers 8. Покрыты API-потоки и права; не покрыты миграции, поток планировщика, frontend, конкурентные гонки и реальные интеграции. Асинхронных тестов нет, несмотря на `pytest-asyncio`. Линтеров, mypy и coverage-конфига нет.

## 9. Расхождения с прежними документами

### 9.1. С прежней версией `specifications/01-stack-and-layout.md`

| Прежнее утверждение | Факт |
| --- | --- |
| React + TanStack Query + Tailwind CSS + shadcn/ui | только React, TypeScript, Vite и чистый CSS |
| WebSocket для обновлений в реальном времени | нет; polling 1/5/10 с |
| UI документов | Исключён из продукта; существующие файлы и API сохраняются |
| pytest + httpx, Vitest + RTL, Playwright | только pytest + httpx; frontend-тестов нет |
| Пакеты `auth`, `domain`, `jobs`, `operations`, `sandbox` | `api` + `services` + `deps.py`; sandbox — два файла |
| `data/` включает логи и очередь повторных внешних операций | логов и очереди нет; есть БД, документы, изображения, бэкапы |
| Docker: `app`, `autoheal`, `uptime-kuma`; fxTunnel на хосте | один сервис `app`; autoheal, Kuma и туннель отсутствуют |
| Прямой запуск через службу/планировщик Windows | только скрипты ручного запуска |
| `/health` возвращает 200 только при готовности, применённых миграциях и доступной на запись папке данных | `SELECT 1`; запись в `data/` и состояние миграций не проверяются |

### 9.2. С [docs/03-architecture-and-operations.md](../docs/03-architecture-and-operations.md)

| Требование docs/03 | Факт |
| --- | --- |
| Docker и прямой запуск используют одни данные и конфигурацию | при прямом запуске с `.env.example` относительные пути уводят данные в `backend/data/`; без `.env` — в корневую `data/`; Docker использует `/data` |
| Autoheal перезапускает unhealthy-контейнер, нужны метка и Docker socket | нет ни метки, ни Autoheal, ни доступа к socket; `restart` и healthcheck сами контейнер не перезапускают |
| Uptime Kuma с HTTP- и Docker-проверками | нет |
| fxTunnel запускается вместе с сервером и переподключается | нет кода и конфигурации; `FXTUNNEL_TOKEN` не читается |
| Хранится одна последняя локальная копия; замена безопасна | `latest.zip` + один обычный архив, но `safety`-копии накапливаются; записи `backup_records` для удалённых файлов остаются |
| Frontend может поставляться собранной статикой с сервером | статика не монтируется; Docker отдаёт только API |
| RESTORE требует подтверждения и сначала создаёт защитную копию | реализовано (`CONFIRM_REQUIRED`, `kind="safety"`) |
| Миграции применяются при старте | реализовано, но на непустой БД с текущей ревизией `bed2ce42ab1b` обновление падает (раздел 7) |

Прочее: `README.md` и `docs/README.md` ссылаются на `docs/07-implementation-status.md`, `08-development-guide.md`, `09-operations-runbook.md`, `10-known-gaps-and-roadmap.md`, которых в дереве нет. Docker не содержит frontend, поэтому `docker compose up` даёт рабочий API без пользовательского интерфейса.
