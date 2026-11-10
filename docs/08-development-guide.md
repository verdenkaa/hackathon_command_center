# Разработка и сопровождение

## Изолированная среда

Нужны Git, Python 3.12+, Node.js 22 с npm. Команды PowerShell ниже выполняются из корня checkout. Перед запуском прочитайте `AGENTS.md` и проверьте `git status --short`: не стирайте чужие изменения. Рабочий проект и его базу не используйте как стенд.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
npm --prefix frontend ci
npm --prefix control/tests ci

# Только отдельная тестовая папка; для постоянных проектов выберите путь вне Git.
$developmentData = Join-Path (Get-Location) '.tmp/development'
$env:APP_DATA_DIR = $developmentData
$env:DATABASE_URL = 'sqlite:///' + (Join-Path $developmentData 'hackathon.db').Replace('\', '/')
$env:APP_MANAGED = 'false'
$env:APP_ENV = 'development'
$env:APP_FIRST_ADMIN_LOGIN = 'dev-admin'
$developmentPassword = Read-Host 'Пароль только для локального стенда' -AsSecureString
$env:APP_FIRST_ADMIN_PASSWORD = [System.Net.NetworkCredential]::new('', $developmentPassword).Password
Set-Location backend
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers
```

В другом терминале из корня: `npm --prefix frontend run dev`. Откройте `http://localhost:5173`; Vite направляет API на порт 8000. Не запускайте этот стенд одновременно с управляемой платформой на том же порту. После остановки backend удалите переменную пароля: `Remove-Item Env:APP_FIRST_ADMIN_PASSWORD`; не выводите её значение.

Lifespan backend выполняет миграции и bootstrap автоматически. Переменные конфигурации задаются **до импорта** приложения; изменение окружения требует перезапуска. Настройки читаются также из корневого `.env`; не оставляйте там путь рабочей БД для разработки.

## Карта кода

| Каталог / файл | Ответственность |
| --- | --- |
| `backend/app/api/` | HTTP, DTO, права, транзакционные границы |
| `backend/app/services/` | Задачи, таймеры, инциденты, план, сводка, Argus, очередь |
| `backend/app/db/models.py`, `db/session.py` | ORM и SQLite WAL/FK |
| `backend/app/*schemas.py` | Pydantic-контракты |
| `backend/alembic/versions/` | Последовательные миграции |
| `backend/app/integrations/` | Сетевой Telegram и форматирование |
| `frontend/src/` | React-экраны, API и состояние |
| `control/manager.py`, `controller.py` | Выбор проекта и жизненный цикл |
| `control/archives.py`, `vault.py`, `worker.py` | Копии, шифрование и секреты |
| `control/docker.py`, `dependencies.py`, `tunnel.py` | Хост, WSL/Docker, туннель |
| `control/server.py`, `control/static/` | Локальный HTTP и интерфейс управления |

## Проверки

Из `backend` выполните `..\.venv\Scripts\python.exe -m pytest -q`.
Из корня: `.\.venv\Scripts\python.exe -m pytest control/tests -q`.
Затем `npm --prefix frontend test`, `npm --prefix frontend run build`,
`npm --prefix control/tests test` и `git diff --check`.

Браузерные регрессии: после `npm --prefix frontend run build` установите Chromium командой `npm --prefix frontend exec -- playwright install chromium`, затем выполните `npm --prefix frontend run test:e2e`. Python из `.venv` должен быть первым в PATH; на Windows можно задать `$env:PATH=(Resolve-Path .venv/Scripts).Path+';'+$env:PATH`. Для установленного Edge задайте `$env:AION_BROWSER='msedge'`. Playwright сам поднимает порт 8001 с новой временной базой в `.tmp` и останавливает её после проверки; работающий сервер на этом порту не переиспользуется. Проверяются конкурентное редактирование, потеря ответа создания, черновики, ошибки, история браузера и мобильное размещение. CI запускает backend, frontend, сборку и браузерные тесты; трассы неуспешных браузерных проверок сохраняются как артефакт.

Запускайте Python-наборы последовательно: backend-фикстуры используют общую тестовую папку. Тесты не требуют настоящих токенов; провайдеры подменяются. Некоторые проверки запускают дочерние процессы, поэтому нужны права на создание/удаление собственных временных файлов. При отказе прав не расширяйте очистку на рабочие данные.

Для точечного изменения сначала добавьте регрессию, затем минимальную правку. Проверяйте межпроектный доступ, отказ операции и сохранность истории. Автоматические проверки дополняйте реальным браузером на изолированной БД. После проверки завершите свои серверы и контейнеры, убедитесь, что их порты закрыты.

## Изменение схемы

1. Сохраните проверенный архив и тестовую копию заполненной БД.
2. Измените ORM и добавьте новую Alembic-ревизию; применённые ревизии не переписывайте.
3. Проверьте обновление пустой и заполненной БД, значения по умолчанию, FK и историю.
4. Из `backend`: `..\.venv\Scripts\python.exe -m alembic heads` и `..\.venv\Scripts\python.exe -m alembic upgrade head` **только для настроенного стенда**.
5. Обновите справочник данных, восстановление архива и тесты разделения/удаления проекта, если затронуты связи.

Не используйте `create_all` или `stamp head` для исправления рабочей БД. Неизвестную/более новую схему исследуют на копии. Откат выпуска выполняют совместимым образом приложения и архивом данных, а не принудительной сменой отметки миграции.

## Расширение функций

Новый API добавляется в `api/`, регистрируется в `main.create_app`, валидируется Pydantic и проверяет проект всех переданных ID. Запись, история и outbox должны иметь согласованную транзакцию; внешний вызов выполняйте после commit. Расчёты аналитики и Argus используют `operational.build_summary`.

Frontend использует общий `api.ts`, серверные версии и события проекта. Изменение плана не должно переписывать фактические таймеры. Не добавляйте автоматический повтор неидемпотентной записи после сетевой ошибки.

При изменении зависимостей обновляйте соответствующий lock-файл: backend и control закреплены отдельно, frontend и DOM-тесты имеют отдельные npm lock-файлы. Production-сборка использует lock-файлы; одна правка `requirements.txt` не меняет образ.

## Выпуск

Версия приложения задаётся в `backend/app/__init__.py`; согласуйте её с тегами образа и проверками готовности. Не определяйте совместимость только по имени zip или npm-версии. Проверьте многоэтапную Docker-сборку, чистый запуск, миграцию копии, вход, frontend/API и цикл архив → восстановление.

Обновление и откат: [справочник оператора](09-operations-runbook.md). Перед публикацией проверьте документацию, ссылки и отсутствие реальных данных/секретов в составе поставки.
