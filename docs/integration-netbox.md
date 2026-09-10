# Интеграция с NetBox

NetBox — IPAM/DCIM, источник правды по IP-адресам, доменам и инфраструктуре. Hub интегрируется с NetBox двумя способами:

1. **Frontend-ссылки** — IP в карточке находка становятся кликабельными ссылками на поиск в NetBox
2. **Sync периметра** — Hub импортирует scope entries (IP + домены) из NetBox в проекты

DomainScope тоже работает с NetBox (импорт целей сканирования + экспорт обнаруженных IP). См. [Синхронизация с NetBox](domainscope-netbox.md).

## Сценарий 1: Frontend-ссылки на NetBox

Самый простой режим. В карточке находка каждый IP становится ссылкой `<NETBOX_URL>/search/?q=<ip>`.

### Включение

```ini
REACT_APP_NETBOX_BASE_URL=https://netbox.example.com/
```

> Важен слэш в конце.

### Особенности

- Build-time для frontend (но runtime-инжектируется через `entrypoint.sh`)
- Для compose/K8s — задайте в `frontend.env.netboxUrl` в Helm values, или в `.env` при сборке
- Локальная разработка: в `frontend/.env.local`:
  ```ini
  REACT_APP_NETBOX_BASE_URL=https://netbox.example.com/
  ```

После задания и перезапуска frontend контейнера ссылки появятся автоматически.

## Сценарий 2: Sync периметра (Hub ← NetBox)

Hub периодически (или по триггеру) тянет список IP/доменов из NetBox в свой scope. Используется для проектов, где периметр определяется в NetBox (IPAM-first).

### Что синхронизируется

| NetBox object                        | Hub scope entry                      |
| ------------------------------------ | ------------------------------------ |
| IP Address                           | `cidr` (с маской /32 если single IP) |
| Prefix                               | `cidr`                               |
| FHRP Group                           | (опц.) множественные IP              |
| DNS record (через NetBox-DNS plugin) | `domain`                             |

Поля переносятся:

- `address`/`prefix` → `value`
- `description` → `description`
- `tags` → `tags` (если `import_tags=true`)
- `status` → `active`/`disabled`

### Настройка sync job

Per-project в UI Hub: Project → Scope → Sync jobs → Add:

| Поле                        | Описание                                                        |
| --------------------------- | --------------------------------------------------------------- |
| **NetBox URL**              | `https://netbox.example.com`                                    |
| **API Token**               | NetBox token (см. ниже)                                         |
| **Filter: tags**            | Только объекты с указанными тегами (CSV)                        |
| **Filter: exclude_tags**    | Исключить с этими тегами                                        |
| **Filter: active_statuses** | Какие NetBox-статусы считать активными (default: `active`)      |
| **Filter: network_type**    | `public` (исключить RFC1918), `private` (только RFC1918), `all` |
| **import_tags**             | Сохранять ли теги                                               |
| **Interval**                | Например, `interval_hours: 6` или `cron: "0 */6 * * *"`         |

### Алгоритм diff-sync

При каждом запуске Hub:

1. Берёт текущий список из NetBox с фильтрами
2. Сравнивает со scope entries проекта
3. Применяет действия:

| Состояние                                      | Действие                                                               |
| ---------------------------------------------- | ---------------------------------------------------------------------- |
| Новое в NetBox, нет в Hub                      | `INSERT` (status=`active`)                                             |
| Было в Hub, нет в NetBox                       | `appeared=false` → soft-disable либо hard-delete (по политике проекта) |
| Было в NetBox, статус ≠ active                 | `disable` + сохранить metadata                                         |
| Было `disabled` в Hub, снова `active` в NetBox | `reactivate`                                                           |
| Live в обоих, metadata отличаются              | `UPDATE` (description/tags)                                            |

### Tombstone-защита

Если scope entry помечен админом как `disabled_by=user` — автоматический sync **никогда не реактивирует**. Это защита от перетирания ручных решений (например, "этот IP — не наш периметр, не надо его сканировать").

Чтобы вернуть entry в активные — админ должен явно `Activate` в Hub UI.

## Настройка NetBox

### 1. API Token

NetBox UI → Profile → API Tokens → Add:

- **Description:** `securityhub-sync`
- **Expires:** опционально, например +1 год
- **Permissions:** read-only достаточно для sync; write нужен только если Hub/DomainScope пишет обратно
- **Allowed IPs:** CIDR Hub-стенда (рекомендуется)

### 2. Tags

Заведите теги для разметки активов:

- `security-scope` — основной периметр для сканирования
- `external-perimeter` — внешний перимметр
- `internal-perimeter` — внутренний
- `exclude-from-scan` — исключения

В sync job фильтруйте по этим тегам.

### 3. Custom fields (опционально)

Для проектов с per-IP метаданными можно завести:

- `owner_team` — команда-владелец (передаётся в Hub как тег)
- `risk_score` — приоритет для сортировки

## Переменные окружения

| Переменная                  | Где                    | Описание            |
| --------------------------- | ---------------------- | ------------------- |
| `REACT_APP_NETBOX_BASE_URL` | frontend build/runtime | Для деep-link в UI  |
| Остальное — per-sync-job    | UI Hub                 | URL, token, фильтры |

## Проверка интеграции

### 1. Frontend-ссылка

Откройте находка с IP в адресе. Кликните по IP — должен открыться поиск в NetBox.

### 2. Sync job

```bash
# Логи worker
docker compose logs -f worker | grep netbox_sync

# Статистика по записям периметра: активные и отключённые, отдельно по типу и действию
docker compose exec postgres psql -U securityhub -d securityhub -c \
  "SELECT entry_type, scope_action, (disabled_at IS NULL) AS active, COUNT(*)
     FROM scan_scope_entries WHERE project_id='<uuid>'
    GROUP BY entry_type, scope_action, active ORDER BY 1,2,3;"

# Audit-log
docker compose exec postgres psql -U securityhub -d securityhub -c \
  "SELECT created_at, action, payload FROM audit_logs WHERE action LIKE 'netbox_sync%' ORDER BY created_at DESC LIMIT 10;"
```

## DomainScope ↔ NetBox

Если DomainScope тоже подключён к NetBox, проверьте чтобы не было двойной записи. Рекомендуется:

- DomainScope **пишет** обнаруженные IP в NetBox с тегом `domainscope-discovered`
- Hub **читает** из NetBox с фильтром `tags: security-scope` (без discovery-тегов)
- Админ периодически ревьюит `domainscope-discovered` и руками помечает `security-scope`, что подтверждает добавление в перимметр

Подробнее: [Синхронизация с NetBox](domainscope-netbox.md).

## SSRF и safety

Hub читает NetBox по URL из БД (per-project). NetBox URL и токен задаются **per-sync-job** в модели `ScanScopeSyncJob` (через UI Hub: Project → Scope → Sync jobs), а не через env-переменные.

> **Важно:** глобальных env-гардов SSRF для NetBox-sync (вида `NETBOX_ALLOW_LOCAL_DIAL` / `NETBOX_BASE_URL_ALLOWLIST`) в backend **нет** — такие переменные не реализованы. Доступ к приватным сетям не ограничивается env-конфигом; конфигурация целевого NetBox целиком определяется per-job (URL + token + фильтры). Предполагается, что NetBox находится внутри доверенной корпоративной сети. Ограничивайте, кому разрешено заводить sync job (право `write` на проект), и при необходимости — сетевыми ACL на уровне инфраструктуры.

## Типовые проблемы

| Симптом                      | Что проверить                                                                                      |
| ---------------------------- | -------------------------------------------------------------------------------------------------- |
| Frontend: IP не кликабельный | `REACT_APP_NETBOX_BASE_URL` задан **и контейнер перезапущен**. Пересобирать образ НЕ нужно: значение подменяется в бандле на старте (`entrypoint.sh`), см. [переменные frontend](env-frontend.md). В Helm — `frontend.frontend.env.netboxUrl` |
| Sync падает с `401`          | API token истёк или у токена нет permissions                                                       |
| Sync `403 Forbidden`         | NetBox IP allowlist у токена не включает IP Hub-стенда                                             |
| После sync пропали entries   | Возможно, фильтр `tags` слишком узкий. Запустите sync в dry-run режиме (UI)                        |
| Дублируются entries          | Скорее всего, два sync job на один проект. Проверьте Project → Scope → Sync jobs                   |

## Связанные документы

- [Синхронизация с NetBox](domainscope-netbox.md) — sync с DomainScope
