# Интеграция с Jira

Hub умеет создавать задачи в Jira, переводить их по статусам, синхронизировать обратно (reverse-sync) и автоматически закрывать findings при подтверждённом фиксе. Конфигурация на двух уровнях:

- **Глобально** — env vars (feature flags, SSRF-защита, расписания)
- **Per-project** — `jira_config` в проекте (Hub UI → Project → Jira settings)

## Архитектура

```
   Hub finding (status=open)
        │
        │ User clicks "Create Jira ticket"
        │   OR auto-create (если в jira_config: create_on_confirm=true)
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

## Env vars (глобально)

| Переменная                           | Default | Описание                                                                                     |
| ------------------------------------ | ------- | -------------------------------------------------------------------------------------------- |
| `FALLBACK_JIRA_URL`                  | —       | Если у проекта не задан `jira_config.base_url`, используется для генерации ссылок в шаблонах |
| `JIRA_ALLOW_HTTP`                    | `false` | Разрешить ли HTTP без TLS. **Только dev**                                                    |
| `JIRA_ALLOW_LOCAL_DIAL`              | `false` | Разрешить ли коннект к RFC1918. Для self-hosted Jira во внутренней сети — `true`             |
| `JIRA_BASE_URL_ALLOWLIST`            | —       | Whitelist хостов (CSV) — дополнительная защита от SSRF                                       |
| `FEATURE_JIRA_REVERSE_SYNC`          | `false` | Включить периодический reverse-sync worker                                                   |
| `JIRA_REVERSE_SYNC_INTERVAL_MINUTES` | `60`    | Интервал проверки статусов                                                                   |
| `JIRA_REVERSE_SYNC_BATCH_SIZE`       | `500`   | Сколько findings проверяется за tick                                                         |
| `JIRA_SYNC_WORKERS`                  | `4`     | Параллелизм очереди auto-create                                                              |
| `FEATURE_AUTO_VERIFY_FIXES`          | `false` | Auto-close findings, отсутствующих в новом отчёте                                            |

## Per-project конфигурация (jira_config)

В UI: Project → Settings → Jira. В БД хранится как JSONB. Пример:

```json
{
  "base_url": "https://jira.example.com",
  "auth_type": "basic",
  "username": "hub-bot",
  "password": "<token>",
  "project_key": "SEC",
  "issue_type": "Bug",
  "partial_automation": false,
  "create_on_confirm": true,
  "initial_transition_chain": ["In Progress", "Code Review"],
  "reverse_sync_enabled": true,
  "reverse_sync_done_statuses": ["Done", "Closed", "Resolved", "Fixed"],
  "auto_verify_close_comment": "Closed by Hub auto-verify",
  "summary_template": "[{severity}] {title} in {product}",
  "description_template": "..."
}
```

## Два режима автоматизации

### 1. Full automation (`partial_automation: false`)

Hub самостоятельно создаёт тикет через REST API.

**Что нужно:**

- Service account в Jira (рекомендуется отдельный пользователь `hub-bot`)
- Permission на создание issue и переходы по workflow в нужном `project_key`
- Один из методов аутентификации:
  - **Basic** (`auth_type: basic`) — username + Jira API token
  - **PAT** (Personal Access Token) для Jira Data Center

**Workflow:**

1. Hub получает finding со статусом `confirmed`
2. Если `create_on_confirm: true` — ставит job в очередь
3. Worker формирует payload (см. шаблоны ниже), шлёт `POST /rest/api/2/issue`
4. После создания — выполняет `initial_transition_chain` (например, `In Progress` → `Code Review`)
5. Сохраняет `jira_issue_key` в БД, finding получает ссылку в UI

### 2. Partial automation (`partial_automation: true`)

Hub только открывает Jira-UI с предзаполненной формой. Юзер дотыкает поля и сам нажимает Create.

Используется когда:

- Нет permissions на bot-account
- Корпоративная политика запрещает автоматическое создание issue
- Workflow требует ручной валидации

В UI Hub показывается кнопка `Open in Jira` → редирект на `<base_url>/secure/CreateIssueDetails!init.jspa?...` с query-параметрами.

## Template engine

Templates можно задать в `jira_config`:

- `summary_template` — заголовок issue
- `description_template` — тело
- `comment_template` — для комментариев (например, при auto-verify close)

### Поддерживаемые плейсхолдеры

| Плейсхолдер       | Что подставляется                                                             |
| ----------------- | ----------------------------------------------------------------------------- |
| `{title}`         | Заголовок finding                                                             |
| `{description}`   | Описание finding                                                              |
| `{severity}`      | `INFO`/`LOW`/`MEDIUM`/`HIGH`/`CRITICAL`                                       |
| `{resource}`      | `ip:port_range/protocol` или ресурс из SARIF                                  |
| `{ip}`            | IP-адрес                                                                      |
| `{port}`          | Порт                                                                          |
| `{domain}`        | Домен                                                                         |
| `{protocol}`      | Протокол (tcp/udp/http/https)                                                 |
| `{service}`       | Сервис (например, `nginx 1.18`)                                               |
| `{product}`       | Имя продукта в Hub                                                            |
| `{project}`       | Имя проекта в Hub                                                             |
| `{count}`         | Количество однотипных findings                                                |
| `{findings_list}` | Список однотипных (для bulk-issue)                                            |
| `{tags:sep}`      | Теги через разделитель `sep`. Примеры: `{tags:\n}`, `{tags: ~ }`, `{tags:, }` |

### Пример template

```
summary_template: "[{severity}] {title} on {resource}"
description_template: |
  *Severity:* {severity}
  *Resource:* {resource}
  *Service:* {service}

  *Description:*
  {description}

  *Tags:* {tags:, }

  *Source:* Security Hub (Product: {product})
```

## Reverse-Sync (Jira → Hub)

Включается `FEATURE_JIRA_REVERSE_SYNC=true`. Раз в `JIRA_REVERSE_SYNC_INTERVAL_MINUTES` worker:

1. Выбирает batch findings с `jira_issue_key IS NOT NULL` и не закрытых
2. Для каждого — `GET /rest/api/2/issue/<key>` → читает текущий статус
3. Если статус ∈ `reverse_sync_done_statuses` (default: `Done`, `Closed`, `Resolved`, `Fixed`) — закрывает finding в Hub со статусом `fixed`
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

Замыкает цикл: после деплоя фикса свежий отчёт сканера не содержит этот finding — Hub помечает его как `fixed`.

### Тройная защита

Все три условия должны быть `true`:

1. Глобально: `FEATURE_AUTO_VERIFY_FIXES=true`
2. На проекте: `projects.auto_verify_fixes_enabled = true`
3. При загрузке отчёта: form-параметр `verify_fixes=true`

Без всех трёх частичный скан (например, только одного контейнера) может массово закрыть валидные findings.

### Что происходит

Когда приходит SARIF с `verify_fixes=true`:

1. Hub находит все open findings того же engine на том же product
2. Сравнивает с findings из нового отчёта (по dedup_hash)
3. Те, что **отсутствуют** в новом отчёте, помечаются `fixed`
4. Если у них есть `jira_issue_key`:
   - Добавляет комментарий из `auto_verify_close_comment`
   - Опционально выполняет transition (если задан `auto_verify_transition`)

### Пример конфига

```json
{
  "auto_verify_fixes_enabled": true,
  "auto_verify_close_comment": "🟢 Verified by Hub: finding не воспроизводится в новом отчёте.",
  "auto_verify_transition": "Verify Done"
}
```

И при загрузке:

```bash
curl -X POST https://hub.example.com/api/v1/products/<id>/reports \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@sarif.json" \
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

После настройки `jira_config` переведите в Hub любой finding в статус `confirmed` — worker попытается создать тикет в Jira. Результат и ошибки видны в логах worker:

```bash
docker compose logs worker | grep -i jira
```

### Reverse-sync проверка

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
