# Интеграция с Jira

Hub умеет создавать задачи в Jira, переводить их по статусам, синхронизировать обратно (reverse-sync) и автоматически закрывать находки при подтверждённом фиксе. Конфигурация на двух уровнях:

- **Глобально** — env vars (feature flags, SSRF-защита, расписания)
- **Per-project** — `jira_config` в проекте (Hub UI → Project → Jira settings)

## Архитектура

```
   Hub finding (status=open)
        │
        │ User clicks "Create Jira ticket"
        │   ИЛИ автосоздание при auto_create_on_confirm=true
        ▼
   Worker job: jira_create
        │
        ├─ Формирует payload (через template engine)
        ├─ POST /rest/api/2/issue → Jira
        ├─ Сохраняет jira_issue_key в finding
        ├─ (опц.) выполняет initial_transition_chain
        └─ (опц.) добавляет attachments/комментарий

        │
        ▼
   Periodic worker: jira_reverse_sync (раз в N минут)
        │
        ├─ Тянет статусы тикетов из Jira
        ├─ Если статус = Done/Resolved/Fixed → закрывает finding в Hub
        └─ Эталонные статусы — из jira_config.reverse_sync_done_statuses
```

## Переменные окружения

| Переменная                           | Default | Описание                                                                                     |
| ------------------------------------ | ------- | -------------------------------------------------------------------------------------------- |
| `FALLBACK_JIRA_URL`                  | —       | Если у проекта не задан `jira_config.base_url`, используется для генерации ссылок в шаблонах |
| `JIRA_ALLOW_HTTP`                    | `false` | Разрешить ли HTTP без TLS. **Только dev**                                                    |
| `JIRA_ALLOW_LOCAL_DIAL`              | `false` | Разрешить ли коннект к RFC1918. Для self-hosted Jira во внутренней сети — `true`             |
| `JIRA_BASE_URL_ALLOWLIST`            | —       | Whitelist хостов (CSV) — дополнительная защита от SSRF                                       |
| `FEATURE_JIRA_REVERSE_SYNC`          | `false` | Включить периодический reverse-sync worker                                                   |
| `JIRA_REVERSE_SYNC_INTERVAL_MINUTES` | `60`    | Интервал проверки статусов                                                                   |
| `JIRA_REVERSE_SYNC_BATCH_SIZE`       | `500`   | Сколько находки проверяется за tick                                                         |
| `JIRA_SYNC_WORKERS`                  | `4`     | Параллелизм очереди auto-create                                                              |
| `FEATURE_AUTO_VERIFY_FIXES`          | `false` | Auto-close находки, отсутствующих в новом отчёте                                            |

## Per-project конфигурация (jira_config)

Задаётся в интерфейсе: Проект → Настройки → Jira. Пример:

```json
{
  "base_url": "https://jira.example.com",
  "username": "hub-bot",
  "api_token": "<токен>",
  "project_key": "SEC",
  "partial_automation": false,
  "auto_create_on_confirm": true,
  "initial_transition_chain": ["In Progress", "Code Review"],
  "reverse_sync_enabled": true,
  "reverse_sync_done_statuses": ["Done", "Closed", "Resolved", "Fixed"],
  "auto_verify_close_comment": "Закрыто автоматически после проверки исправления",
  "payload_template": "{ \"fields\": { \"issuetype\": { \"name\": \"Bug\" }, ... } }",
  "issuetype_by_engine": { "nuclei": "Vulnerability" }
}
```

| Поле | Назначение |
| --- | --- |
| `base_url` | Адрес Jira. Если не задан, для ссылок используется `FALLBACK_JIRA_URL` |
| `username` | Учётная запись бота |
| `api_token` | Токен доступа. **Секрет**: в ответах API не возвращается |
| `project_key` | Ключ проекта Jira |
| `partial_automation` | `false` — Hub создаёт задачу сам, `true` — открывает форму создания в Jira |
| `auto_create_on_confirm` | Создавать задачу при подтверждении находки |
| `initial_transition_chain` | Переходы, выполняемые сразу после создания |
| `reverse_sync_enabled` | Переносить статус из Jira в Hub для этого проекта |
| `reverse_sync_done_statuses` | Статусы Jira, считающиеся завершающими |
| `auto_verify_close_comment` | Комментарий, добавляемый при автоматическом закрытии |
| `auto_verify_close_transition` | Статус, в который перевести задачу при автозакрытии. Пусто — только комментарий |
| `payload_template` | Шаблон тела запроса к Jira при полной автоматизации |
| `issuetype_by_engine` | Тип задачи в зависимости от сканера, нашедшего проблему |
| `value_maps` | Подстановки значений при заполнении полей |
| `extra_params`, `headers` | Дополнительные параметры и заголовки запроса |

!!! warning "Имена полей легко перепутать"

    Токен хранится в `api_token`, а не в `password`. Автосоздание включается
    полем `auto_create_on_confirm`, а не `create_on_confirm`. Тип задачи
    отдельным полем `issue_type` **не задаётся** — он берётся из
    `payload_template` и при необходимости подменяется по
    `issuetype_by_engine`.

## Два режима автоматизации

### Полная автоматизация (`partial_automation: false`)

Hub сам создаёт задачу через REST API Jira.

**Что нужно:**

- Service account в Jira (рекомендуется отдельный пользователь `hub-bot`)
- Permission на создание issue и переходы по workflow в нужном `project_key`
- Один из методов аутентификации:
  - учётная запись и токен: `username` + `api_token`
  - **PAT** (Personal Access Token) для Jira Data Center

**Как это происходит:**

1. Находка переходит в состояние `confirmed`
2. Если `auto_create_on_confirm: true` — ставит задачу в очередь
3. Worker формирует payload (см. шаблоны ниже), шлёт `POST /rest/api/2/issue`
4. После создания — выполняет `initial_transition_chain` (например, `In Progress` → `Code Review`)
5. Сохраняет `jira_issue_key` в БД, находка получает ссылку в UI

### Частичная автоматизация (`partial_automation: true`)

Hub открывает форму создания задачи в Jira с уже заполненными полями. Оставшееся заполняет человек и сам подтверждает создание.

Используется когда:

- Нет permissions на bot-account
- Корпоративная политика запрещает автоматическое создание issue
- Workflow требует ручной валидации

В UI Hub показывается кнопка `Open in Jira` → редирект на `<base_url>/secure/CreateIssueDetails!init.jspa?...` с query-параметрами.

## Шаблоны

Какой шаблон применяется, зависит от режима:

| Поле `jira_config` | Когда используется |
| --- | --- |
| `payload_template` | Полная автоматизация: шаблон **всего тела запроса** к Jira, включая `fields.issuetype` |
| `partial_summary_template` | Частичная автоматизация: заголовок в предзаполненной форме |
| `partial_description_template` | Частичная автоматизация: описание |
| `partial_row_template` | Частичная автоматизация: строка при объединении нескольких находок |

### Плейсхолдеры

**Сама находка**

| Плейсхолдер | Что подставляется |
| --- | --- |
| `{id}`, `{title}`, `{description}` | Идентификатор, заголовок, описание |
| `{severity}` | `CRITICAL`, `HIGH`, `MEDIUM`, `LOW`, `INFO` |
| `{status}` | Текущее состояние |
| `{engine}` | Сканер, нашедший проблему |
| `{cve}`, `{cwe}` | Идентификаторы уязвимости и класса слабости |
| `{fingerprint}` | Отпечаток из отчёта |
| `{secret_type}` | Тип найденного секрета |
| `{sla_expires_at}` | Срок устранения |
| `{first_seen_at}`, `{last_seen_at}` | Когда обнаружена впервые и в последний раз |
| `{first_seen_at_date:ФОРМАТ}`, `{last_seen_at_date:ФОРМАТ}` | То же с заданным форматом даты, например `{first_seen_at_date:d/MMM/yy}` |

**Где находится**

| Плейсхолдер | Что подставляется |
| --- | --- |
| `{resource}` | Обобщённое местоположение |
| `{ip}`, `{host}`, `{domain}` | Адрес, узел, домен |
| `{port}`, `{port_range}`, `{protocol}` | Порт, диапазон портов, протокол |
| `{service}` | Определённый сервис |
| `{file_path}`, `{line_start}`, `{line_end}` | Файл и строки для находок в коде |
| `{code}` | Фрагмент кода |
| `{open_ports_list}` | Перечень открытых портов узла |

**Контекст Hub**

| Плейсхолдер | Что подставляется |
| --- | --- |
| `{product}`, `{product_name}` | Продукт |
| `{project}`, `{project_name}` | Проект |
| `{hub_url}` | Ссылка на находку в Hub |
| `{finding}` | Сводное представление находки |
| `{members_list}` | Участники |

**Группы находок**

| Плейсхолдер | Что подставляется |
| --- | --- |
| `{count}` | Количество однотипных находок |
| `{findings_list}` | Их перечень |
| `{tags:РАЗДЕЛИТЕЛЬ}` | Метки через разделитель: `{tags:, }`, `{tags:\n}`, `{tags: ~ }` |
| `{all_tags:РАЗДЕЛИТЕЛЬ}` | Все метки группы без повторов, по алфавиту |
| `{agg:ПОЛЕ}` | Собрать значения поля по всем находкам группы |
| `{agg_or:ГРУППА:ПОЛЕ:ИНАЧЕ}` | То же с запасным значением |
| `{agg_or_map:ГРУППА:ПОЛЕ:КАРТА:ИНАЧЕ}` | То же с подстановкой по карте значений `value_maps` |
| `{map:...}`, `{prop:...}` | Подстановка по карте значений и по произвольному свойству |

**Разметка Jira**

`{code}`, `{noformat}`, `{panel}` — вставляются как есть, чтобы задать
форматирование в разметке Jira.

### Пример

```
partial_summary_template: "[{severity}] {title} на {resource}"
partial_description_template: |
  *Критичность:* {severity}
  *Ресурс:* {resource}
  *Сервис:* {service}

  *Описание:*
  {description}

  *Метки:* {tags:, }

  *Источник:* Security Hub, продукт {product} — {hub_url}
```

## Перенос статуса из Jira в Hub

Включается `FEATURE_JIRA_REVERSE_SYNC=true`. Раз в `JIRA_REVERSE_SYNC_INTERVAL_MINUTES` worker:

1. Выбирает batch находки с `jira_issue_key IS NOT NULL` и не закрытых
2. Для каждого — `GET /rest/api/2/issue/<key>` → читает текущий статус
3. Если статус ∈ `reverse_sync_done_statuses` (default: `Done`, `Closed`, `Resolved`, `Fixed`) — закрывает находку в Hub, проставляя состояние `fixed`
4. Логирует action в audit-log

**Отключить per-project:**

```json
"reverse_sync_enabled": false
```

**Изменить эталонные статусы:**

```json
"reverse_sync_done_statuses": ["Done", "Verified", "На проде"]
```

## Автоматическое закрытие исправленных находок

Замыкает цикл: после деплоя фикса свежий отчёт сканера не содержит этот находка — Hub помечает его как `fixed`.

### Тройная защита

Все три условия должны быть `true`:

1. Глобально: `FEATURE_AUTO_VERIFY_FIXES=true`
2. На проекте: `projects.auto_verify_fixes_enabled = true`
3. При загрузке отчёта: form-параметр `verify_fixes=true`

Без всех трёх частичный скан (например, только одного контейнера) может массово закрыть валидные находки.

### Что происходит

Когда приходит отчёт с `verify_fixes=true`:

1. Hub отбирает открытые находки того же сканера в том же продукте;
2. сравнивает их с находками из нового отчёта по хешу дедупликации;
3. те, которых в новом отчёте нет, **не закрываются сразу** — им наращивается
   счётчик последовательных отсутствий;
4. находка закрывается только после `AUTO_VERIFY_ABSENT_THRESHOLD`
   последовательных проверок, давших «отсутствует» (по умолчанию три). Любое
   обнаружение сбрасывает счётчик в ноль;
5. если у закрытой находки есть задача в Jira — к ней добавляется комментарий
   из `auto_verify_close_comment`, а при заданном
   `auto_verify_close_transition` задача ещё и переводится в указанный статус.

!!! warning "Кворум обязателен"

    Ранняя версия закрывала находку по одному наблюдению. На работающей
    установке это привело к массовому ложному закрытию: значительная часть
    находок вернулась при следующем сканировании. Значение `1` возвращает
    именно то поведение — не ставьте его.

Если `auto_verify_close_transition` не задан, задача остаётся в текущем
статусе и к ней добавляется только комментарий — закрывает её человек.

### Пример настройки

Настройки проекта:

```json
{
  "auto_verify_fixes_enabled": true,
  "auto_verify_close_comment": "Находка не воспроизводится в новом отчёте — закрыта автоматически.",
  "auto_verify_close_transition": "Resolved"
}
```

И при загрузке отчёта:

```bash
curl -X POST https://hub.example.com/api/v1/products/<id>/reports \
  -H "X-API-Key: $HUB_API_KEY" \
  -F "file=@scan.sarif" \
  -F "verify_fixes=true"
```

## SSRF-защита

По умолчанию Hub блокирует исходящие коннекты к приватным сетям при работе с Jira (защита от подмены `base_url` злоумышленником). Для self-hosted Jira в корпсети:

```ini
JIRA_ALLOW_LOCAL_DIAL=true
```

**Никогда не включайте в production-облаке** — даст возможность злоумышленнику читать internal metadata services (AWS IMDS, GCP metadata).

Дополнительная защита — `JIRA_BASE_URL_ALLOWLIST`:

```ini
JIRA_BASE_URL_ALLOWLIST=jira.example.com,jira.partner.com
```

## Создание Jira-ботa

### Cloud Jira

1. Создать service-аккаунт `hub-bot@example.com` в Atlassian admin
2. В User profile → Security → Create API token
3. В Project → Settings → Permissions: дать ботy роли `Developer` (или эквивалент с правами создавать issue)
4. В Hub: `auth_type=basic`, `username=hub-bot@example.com`, `password=<api-token>`

### Self-hosted Jira (Data Center)

1. Создать `hub-bot` user
2. Profile → Personal Access Tokens → Create token
3. В Hub: `auth_type=basic`, `username=hub-bot`, `password=<PAT>`

## Проверка интеграции

### Тестовое создание issue

После настройки `jira_config` переведите в Hub любой находка в статус `confirmed` — worker попытается создать задача в Jira. Результат и ошибки видны в логах worker:

```bash
docker compose logs worker | grep -i jira
```

### Проверка переноса статуса

```bash
# Найти finding с привязанным тикетом
docker compose exec postgres psql -U securityhub -d securityhub -c \
  "SELECT id, title, jira_issue_key, status FROM findings WHERE jira_issue_key IS NOT NULL LIMIT 5;"

# Закрыть тикет в Jira
# Подождать JIRA_REVERSE_SYNC_INTERVAL_MINUTES + 1 минуту
# Проверить в Hub — finding должен быть status=fixed

# Логи worker
docker compose logs -f worker | grep jira_reverse_sync
```

## Типовые проблемы

| Симптом                         | Что проверить                                                                                               |
| ------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| `401 Unauthorized` при создании | Проверить username/password. Для Jira Cloud — должен быть API token, не пароль                              |
| `403 Forbidden`                 | Bot не имеет permission `Create Issue` в нужном project                                                     |
| `Transition not allowed`        | `initial_transition_chain` пытается перейти по статусу, недоступному в workflow                             |
| Findings закрываются массово    | Проверьте, что `FEATURE_AUTO_VERIFY_FIXES` НЕ включён или `verify_fixes` не передаётся при частичных сканах |
| `SSRF blocked`                  | Self-hosted Jira во внутренней сети — нужен `JIRA_ALLOW_LOCAL_DIAL=true`                                    |
