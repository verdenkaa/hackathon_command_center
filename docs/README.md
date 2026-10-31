# Документация Aion

Имена модулей: Aion — платформа, Ouroboros Daemon — управление и стабильность, Argus — ИИ, Hermes — Telegram, Agora — доска, Chronos — Гант.

Переносимая поставка, локальная панель, ключи, копии и статус приёмки: [17-portable-operations.md](17-portable-operations.md). Для управляемого Docker-запуска этот документ уточняет прежние инструкции эксплуатации.

Планирование, правила пересчёта, API и проверка: [14-planning.md](14-planning.md).
Telegram, защищённый токен, очередь и полное удаление аккаунтов: [16-telegram-and-accounts.md](16-telegram-and-accounts.md).

Проект имеет два слоя документации, и их важно не смешивать:

1. **Продуктовые требования** (`01`–`06`, `agents_plan.md`) — написаны до разработки. Они фиксируют, что и зачем нужно, но не описывают текущий код. Расхождения с реализацией перечислены в [07-implementation-status.md](07-implementation-status.md).
2. **As-built документация** (`07`–`10` и каталог [../specifications/](../specifications/README.md)) — описывает фактическое поведение прототипа: структуру кода, API, модель данных, потоки, эксплуатацию и известные пробелы.

## Индекс

### Продуктовые требования (исторические)

| Файл | Содержание |
| --- | --- |
| [01-product.md](01-product.md) | Цель продукта, границы MVP, роли и основные сценарии |
| [02-functional-requirements.md](02-functional-requirements.md) | Поведение ключевых функций и используемые данные |
| [03-architecture-and-operations.md](03-architecture-and-operations.md) | Требования к архитектуре, развёртыванию, хранению и безопасности |
| [04-quality-and-acceptance.md](04-quality-and-acceptance.md) | Стратегия качества, песочница, критерии приёмки |
| [05-open-questions.md](05-open-questions.md) | Зафиксированные технические решения |
| [06-UI.md](06-UI.md) | Справочник UI/UX: визуальный язык и компоновка |
| [agents_plan.md](agents_plan.md) | Поэтапный план разработки, по которому создавался прототип |

### As-built документация

| Файл | Содержание |
| --- | --- |
| [07-implementation-status.md](07-implementation-status.md) | Матрица «требование → реализация → тесты → статус», сводка MVP |
| [08-development-guide.md](08-development-guide.md) | Онбординг, карта кода, соглашения, рецепты расширения, тесты, отладка |
| [09-operations-runbook.md](09-operations-runbook.md) | Запуск и сопровождение, бэкапы/восстановление, типовые сбои, чек-листы |
| [10-known-gaps-and-roadmap.md](10-known-gaps-and-roadmap.md) | Пробелы, техдолг и приоритизированный план развития |
| [../specifications/README.md](../specifications/README.md) | Технические спецификации: стек, данные, API, фронтенд, фоновые задачи, безопасность, потоки |

## Как читать

- Исправления ручной проверки, правила колонок и ограничения прогнозов: [13-manual-testing-fixes.md](13-manual-testing-fixes.md).
- Для быстрого тестирования: [12-sandbox.md](12-sandbox.md) — демо-набор, автопроверки и очистка тестового проекта.

- Актуальный объём после стабилизации: [11-stabilization.md](11-stabilization.md). Этот раздел уточняет устаревшие таблицы реализации в документах `07`–`10` и спецификациях. Экран документов и редактор исключены; ИИ и Telegram остаются проверяемыми моками.

- Новому разработчику: [08-development-guide.md](08-development-guide.md) → [../specifications/01-stack-and-layout.md](../specifications/01-stack-and-layout.md) → [../specifications/07-flows.md](../specifications/07-flows.md).
- Перед изменением API или схемы БД: [../specifications/03-api.md](../specifications/03-api.md) и [../specifications/02-data-model.md](../specifications/02-data-model.md).
- Перед демонстрацией или деплоем: [07-implementation-status.md](07-implementation-status.md) и [09-operations-runbook.md](09-operations-runbook.md).
- Перед планированием следующей итерации: [10-known-gaps-and-roadmap.md](10-known-gaps-and-roadmap.md).

## Статусы формулировок

В продуктовых документах используются исходные пометки:

- **Обязательно** — согласованное продуктовое требование.
- **Техническое направление** — предпочтительный подход, проверенный или скорректированный при реализации.
- **Открытый вопрос** — решение не принято.

В as-built документах используются только проверяемые статусы: *реализовано*, *реализовано частично*, *не реализовано*, *расходится с требованием*.

## Правила поддержки документации

Документация считается частью результата, а не комментарием к нему. При изменении поведения обновляйте:

| Изменение в коде | Что обновить |
| --- | --- |
| Новый/изменённый эндпоинт, код ошибки | `specifications/03-api.md`, при необходимости `specifications/07-flows.md` |
| Модель, поле, миграция, инвариант | `specifications/02-data-model.md` |
| Новый экран, компонент, метод клиента | `specifications/04-frontend.md` |
| Фоновая задача, интеграция, формат бэкапа | `specifications/05-jobs-and-integrations.md`, `docs/09-operations-runbook.md` |
| Аутентификация, права, лимиты, тесты | `specifications/06-security-and-tests.md` |
| Завершённый этап или новый пробел | `docs/07-implementation-status.md`, `docs/10-known-gaps-and-roadmap.md` |
| Изменение запуска, конфигурации, структуры каталогов | `specifications/01-stack-and-layout.md`, `README.md` |

Требования из `01`–`06` не переписывайте под текущий код: если реализация разошлась с требованием, зафиксируйте это в `07-implementation-status.md` и решите отдельно, менять код или требование.
