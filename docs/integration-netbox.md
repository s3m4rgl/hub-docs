# Интеграция с NetBox

NetBox — IPAM/DCIM, источник правды по IP-адресам, доменам и инфраструктуре. Hub интегрируется с NetBox двумя способами:

1. **Frontend-ссылки** — IP в карточке находки становится кликабельной ссылкой на поиск в NetBox
2. **Sync периметра** — Hub импортирует scope entries (IP + домены) из NetBox в проекты

DomainScope тоже работает с NetBox (импорт целей сканирования без Hub + запись адресов цикла в IPAM). См. [Синхронизация с NetBox](domainscope-netbox.md).

## Сценарий 1: Frontend-ссылки на NetBox

Самый простой режим. В карточке находки поле IP становится ссылкой `<NETBOX_URL>/search/?q=<ip>`.

### Включение

```ini
REACT_APP_NETBOX_BASE_URL=https://netbox.example.com
```

> Слэш в конце не нужен: путь `/search/` дописывается к адресу как есть.

### Особенности

- Build-time для frontend (но runtime-инжектируется через `entrypoint.sh`)
- Для K8s — задайте `frontend.frontend.env.netboxUrl` в Helm values; для compose — переменную окружения контейнера frontend
- Локальная разработка: в `frontend/.env.local`:
  ```ini
  REACT_APP_NETBOX_BASE_URL=https://netbox.example.com
  ```

После задания и перезапуска frontend контейнера ссылки появятся автоматически.

## Сценарий 2: Sync периметра (Hub ← NetBox)

Hub периодически (или по триггеру) тянет список IP/доменов из NetBox в свой scope. Используется для проектов, где периметр определяется в NetBox (IPAM-first).

### Что синхронизируется

| NetBox object                        | Hub scope entry                      |
| ------------------------------------ | ------------------------------------ |
| IP Address                           | `cidr` с маской `/32` (IPv6 — `/128`) |
| Prefix                               | `cidr`                               |
| DNS zone (через NetBox-DNS plugin)   | `domain`                             |
| DNS record `A`/`AAAA`/`CNAME` (через NetBox-DNS plugin) | `domain`; для `A`/`AAAA` и для IP Address с `dns_name` — ещё и связка домен ↔ IP в инвентаре |

Остальные типы DNS-записей не импортируются. Если плагин NetBox-DNS не
установлен (NetBox отвечает `404`), домены просто не загружаются; любая
другая ошибка при их чтении прерывает синхронизацию.

Поля переносятся:

- `address`/`prefix` → `value`
- `description` → `description`
- `tags` → `tags` (если `import_tags=true`)
- `status` → активна запись или отключена (по списку `active_statuses` задания)

### Настройка sync job

Per-project в UI Hub: Project → Scope → Sync jobs → Add. То же через API:
`POST /api/v1/projects/<id>/scope/sync-jobs` (право `manage_scope` для ключа
либо право записи в проект для пользователя), запуск вне расписания —
`POST …/sync-jobs/<sync_job_id>/run`.

| Поле                        | Описание                                                        |
| --------------------------- | --------------------------------------------------------------- |
| `api_endpoint`              | `https://netbox.example.com`; хвостовой `/api` снимается автоматически |
| `api_token`                 | NetBox token (см. ниже)                                         |
| `ip_tags`, `ip_tags_mode`   | Только объекты с указанными тегами; `any` (любой из, по умолчанию) или `all`. Применяется только к Prefix и IP Address |
| `exclude_tags`, `exclude_tags_mode` | Исключить объекты с этими тегами — применяется ко всем типам, включая DNS |
| `include_tenants`, `exclude_tenants` | Отбор по арендаторам NetBox                          |
| `dns_view`                  | Представление NetBox-DNS, из которого читать зоны и записи      |
| `active_statuses`           | Какие NetBox-статусы считать активными (по умолчанию `active`)  |
| `network_type`              | Для `cidr`: `public` (по умолчанию; исключить частные — RFC 1918, CGNAT `100.64.0.0/10`, IPv6 ULA, loopback, link-local), `private` (только частные), `all`. Домены не фильтруются |
| `scope_action`              | Действие для импортированных записей периметра                  |
| `import_tags`               | Сохранять ли теги                                               |
| `auto_remove`               | Удалять пропавшие записи, а не отключать (по умолчанию `false`) |
| `tls_skip_verify`           | Не проверять сертификат NetBox (самоподписанный)                |
| `allow_private_ips`         | Разрешить подключение к NetBox по частному адресу (см. [ниже](#ssrf-и-safety)) |
| `schedule_interval_hours`   | Интервал запуска в часах, например `6`                          |

Поле `schedule_cron` принимается и проверяется на корректность, но
планировщик его не учитывает: периодичность запуска задаёт только
`schedule_interval_hours`.

### Алгоритм diff-sync

При каждом запуске Hub:

1. Берёт текущий список из NetBox с фильтрами
2. Сравнивает со scope entries проекта
3. Применяет действия:

| Состояние                                      | Действие                                                               |
| ---------------------------------------------- | ---------------------------------------------------------------------- |
| Новое в NetBox, нет в Hub                      | `INSERT` (status=`active`)                                             |
| Было в Hub, нет в NetBox                       | отключение либо удаление — по флагу задания `auto_remove`              |
| Было в NetBox, статус не из `active_statuses`  | отключение (или удаление при `auto_remove`) + обновить metadata        |
| Отключено синхронизацией, снова активно в NetBox | `reactivate`                                                         |
| Live в обоих, metadata отличаются              | `UPDATE` (description/tags)                                            |

Открытые находки по записям, которые синхронизация отключила или удалила,
закрываются как исправленные; в журнале действий остаётся запись
`scope_entry_deactivated`.

### Tombstone-защита

Если scope entry отключён вручную (`disabled_by=user`) — автоматический sync **никогда не реактивирует** его и не заводит заново. Это защита от перетирания ручных решений (например, "этот IP — не наш периметр, не надо его сканировать").

Чтобы вернуть entry в активные — админ должен явно нажать «Восстановить» у записи в разделе отключённых (Project → Scope).

### Предложения на сужение периметра

Если DNS-запись указывает на адрес, который NetBox IPAM держит в статусе вне
«активных» статусов задания, синхронизация создаёт предложение **исключить**
домен (сканер `netbox-sync`, пометка «Предлагается исключить» во вкладке
Project → Scope → «Предложения»). Предложение появляется, только если
освобождены **все** известные адреса домена — и по данным NetBox, и по
инвентарю сканера; адрес, которого IPAM не знает, домен удерживает.
Предложение создаётся, только пока домен ещё допускается периметром. За один
прогон — не больше 200 таких предложений, превышение логируется как ошибка.

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
- `external-perimeter` — внешний периметр
- `internal-perimeter` — внутренний
- `exclude-from-scan` — исключения

В sync job фильтруйте по этим тегам.

### 3. Custom fields (опционально)

Для проектов с per-IP метаданными можно завести:

- `owner_team` — команда-владелец
- `risk_score` — приоритет для сортировки

Hub пользовательские поля NetBox не читает. Чтобы сведения попали в Hub,
дублируйте их тегом и включите `import_tags`.

## Переменные окружения

| Переменная                  | Где                    | Описание            |
| --------------------------- | ---------------------- | ------------------- |
| `REACT_APP_NETBOX_BASE_URL` | frontend build/runtime | Для deep-link в UI  |
| Остальное — per-sync-job    | UI Hub                 | URL, token, фильтры |

## Проверка интеграции

### 1. Frontend-ссылка

Откройте находку с заполненным IP. Кликните по IP — должен открыться поиск в NetBox.

### 2. Sync job

```bash
# Логи worker
docker compose logs -f worker | grep -i 'netbox sync'

# Статистика по записям периметра: активные и отключённые, отдельно по типу и действию
docker compose exec postgres psql -U securityhub -d securityhub -c \
  "SELECT entry_type, scope_action, (disabled_at IS NULL) AS active, COUNT(*)
     FROM scan_scope_entries WHERE project_id='<uuid>'
    GROUP BY entry_type, scope_action, active ORDER BY 1,2,3;"

# Итог последнего запуска
docker compose exec postgres psql -U securityhub -d securityhub -c \
  "SELECT name, last_run_at, last_run_status, last_run_result FROM scan_scope_sync_jobs WHERE project_id='<uuid>';"

# Находки, закрытые из-за отключения записей синхронизацией
docker compose exec postgres psql -U securityhub -d securityhub -c \
  "SELECT changed_at, entity_id, new_values->>'scope_value' FROM audit_logs
    WHERE action='scope_entry_deactivated' AND new_values->>'triggered_by'='netbox_sync'
    ORDER BY changed_at DESC LIMIT 10;"
```

## DomainScope ↔ NetBox

Если DomainScope тоже подключён к NetBox, проверьте чтобы не было двойной записи. Рекомендуется:

- DomainScope при `DOMAINSCOPE_NETBOX_ENABLED=true` каждый цикл **пишет** публичные адреса цикла в IPAM с двумя тегами — `DOMAINSCOPE_NETBOX_TAG` (по умолчанию `public-ip`) и `DOMAINSCOPE_NETBOX_CRAWLER_TAG` (по умолчанию `domainscope-crawler`)
- Hub **читает** из NetBox по тегу, который DomainScope **не** проставляет (например, `security-scope`), и с `exclude_tags: domainscope-crawler`. Если фильтр задания совпадёт с `DOMAINSCOPE_NETBOX_TAG`, адреса, найденные сканером, будут сами возвращаться в периметр Hub без разбора
- Админ периодически ревьюит записи с тегом `domainscope-crawler` и руками помечает `security-scope` те, что действительно относятся к периметру

Подробнее: [Синхронизация с NetBox](domainscope-netbox.md).

## SSRF и safety

Hub читает NetBox по URL из БД (per-project). NetBox URL и токен задаются **per-sync-job** в модели `ScanScopeSyncJob` (через UI Hub: Project → Scope → Sync jobs), а не через env-переменные.

Защита от SSRF задаётся тоже per-job:

- по умолчанию подключение к частным, loopback- и link-local-адресам запрещено; адрес проверяется после разрешения имени, и подключение идёт к проверенному адресу (защита от DNS rebinding);
- флаг `allow_private_ips` разрешает NetBox в частной сети, но адреса облачных сервисов метаданных (`169.254.169.254`, `fd00:ec2::254`, `100.100.100.200`, `192.0.0.192`, `metadata.google.internal`) и `localhost` блокируются всегда;
- перенаправления не выполняются — иначе токен ушёл бы на чужой адрес;
- `tls_skip_verify` отключает только проверку сертификата и на SSRF-защиту не влияет.

Глобальных env-переменных для этих ограничений нет. Ограничивайте, кому разрешено заводить sync job (право `manage_scope` для ключа, право записи в проект для пользователя), и при необходимости — сетевыми ACL на уровне инфраструктуры.

## Типовые проблемы

| Симптом                      | Что проверить                                                                                      |
| ---------------------------- | -------------------------------------------------------------------------------------------------- |
| Frontend: IP не кликабельный | `REACT_APP_NETBOX_BASE_URL` задан и контейнер frontend перезапущен. В Helm — задан в `frontend.frontend.env.netboxUrl` |
| Sync падает с `401`          | API token истёк или у токена нет permissions                                                       |
| Sync `403 Forbidden`         | NetBox IP allowlist у токена не включает IP Hub-стенда                                             |
| После sync пропали entries   | Возможно, фильтр `ip_tags` или `network_type` слишком узкий. Сверьте счётчики `total_fetched`, `imported`, `disabled` в `last_run_result` задания |
| Sync падает с ошибкой о частном адресе | NetBox в частной сети — включите у задания `allow_private_ips` |
| Дублируются entries          | Скорее всего, два sync job на один проект. Проверьте Project → Scope → Sync jobs                   |

## Связанные документы

- [Синхронизация с NetBox](domainscope-netbox.md) — sync с DomainScope
