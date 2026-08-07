# Диагностика

Каталог симптом → причина → fix. Обновляйте при появлении новых кейсов.

## Hub: запуск и базовая работа

### Backend в crash-loop

```bash
docker compose logs backend
# или
kubectl -n hub logs deploy/hub-backend
```

| Признак в логах                                         | Причина                       | Fix                                                    |
| ------------------------------------------------------- | ----------------------------- | ------------------------------------------------------ |
| `JWT_SECRET not set`                                    | Переменная не задана / пустая | Задать в `.env` или helm values                        |
| `dial tcp ...:5432: connect: connection refused`        | БД недоступна                 | Проверить postgres-контейнер, `DB_HOST`                |
| `password authentication failed for user "securityhub"` | Неверный `DB_PASSWORD`        | Сверить с тем, что задано в postgres                   |
| `goose: failed to apply migration`                      | Конфликт миграций             | См. логи goose; обычно — расхождение версий backend/БД |
| `panic: ...`                                            | Баг                           | Reissue в трекер; приложите stacktrace                 |

### Frontend 502 Bad Gateway

| Что                                      | Проверка                                                    |
| ---------------------------------------- | ----------------------------------------------------------- |
| Backend стартанул?                       | `docker compose ps backend` — `Up`?                         |
| Backend отвечает на 8082?                | `curl http://localhost:8082/version`                        |
| Frontend nginx видит backend?            | Проверить `REACT_APP_API_URL` build-arg + entrypoint inject |
| Reverse-proxy (nginx/traefik) корректен? | `nginx -t`, логи `/var/log/nginx/error.log`                 |

### "Версия: dev" в UI

Образ собран без version build-args (баг билда на стороне поставщика). Попросите перевыпуск образа.

### Миграции не применяются

```bash
docker compose exec postgres psql -U securityhub securityhub -c \
  "SELECT version_id, tstamp FROM goose_db_version ORDER BY tstamp DESC LIMIT 5;"
```

- Если таблицы нет — goose не запустился. Логи backend → искать `goose`
- Если есть, но новые миграции не накатились — проверьте, что в `backend/migrations/` есть новые файлы
- Если зависло — посмотрите `SELECT * FROM pg_stat_activity WHERE state='active'` — возможно, миграция длинная

### Loading forever в UI после логина

| Причина                                         | Fix                                                                               |
| ----------------------------------------------- | --------------------------------------------------------------------------------- |
| Frontend не может загрузить чанки (вылетел 404) | Проверить, что вся статика в `frontend-dist/` доступна (`curl -I`)                |
| API возвращает 401 на `/api/v1/users/me`        | JWT истёк или подпись не проверяется. Сверьте `JWT_SECRET` между backend и worker |
| CORS error                                      | `ALLOWED_ORIGINS` не включает frontend-domain                                     |

## Auth / Keycloak

### "Login failed" после редиректа из Keycloak

| Признак                                             | Причина                                                                          | Fix                                                                  |
| --------------------------------------------------- | -------------------------------------------------------------------------------- | -------------------------------------------------------------------- |
| URL: `/auth/keycloak/callback?error=invalid_client` | `KEYCLOAK_CLIENT_SECRET` неверный                                                | Сверить в Keycloak → Clients → Credentials                           |
| `404` на token exchange                             | `KEYCLOAK_TOKEN_URL` указан неправильно (или auto-discovery вернул internal URL) | Задать `KEYCLOAK_TOKEN_URL` явно (HTTPS!)                            |
| `JWT signature invalid`                             | `KEYCLOAK_JWKS_URL` устарел или указывает не на тот realm                        | Очистить кэш JWKS (рестарт backend); задать `KEYCLOAK_JWKS_URL` явно |
| `Audience mismatch`                                 | В `KC_AUDIENCES` нет нужного значения                                            | Добавить или настроить Audience mapper в Keycloak                    |

### Transparent SSO: внешний JWT отклоняется

```bash
docker compose logs backend | grep -i "jwt\|keycloak"
```

Чек-лист:

1. `FEATURE_SECURITY_HUB_INTEGRATION=true`
2. `KC_JWKS_URL` доступен из backend (`curl` из контейнера)
3. `KC_ISSUER` точно совпадает с `iss` в JWT (включая trailing slash)
4. `KC_AUDIENCES` содержит `aud` из JWT
5. `exp` валидный (часы синхронизированы)

Декодировать JWT (без подписи):

```bash
echo '<JWT>' | cut -d. -f2 | base64 -d 2>/dev/null | jq
```

## Jira

### Создание тикета: `401 Unauthorized`

- Cloud Jira: пароль — это **API token**, не пароль аккаунта
- Self-hosted: PAT истёк (Jira DC)
- Проверить вручную: `curl -u username:token <jira>/rest/api/2/myself`

### Создание: `403 Forbidden`

Bot не имеет permission `Create Issue` в нужном `project_key`. Проверьте Project → Permissions.

### `Transition not allowed`

`initial_transition_chain` или `auto_verify_transition` пытается перевести по статусу, недоступному в workflow. Проверьте Project → Workflow в Jira UI — какие переходы разрешены из текущего статуса.

### Reverse-sync не работает

```bash
docker compose logs worker | grep jira_reverse_sync
```

| Симптом                               | Fix                                                                                                             |
| ------------------------------------- | --------------------------------------------------------------------------------------------------------------- |
| Worker не запускается                 | `FEATURE_JIRA_REVERSE_SYNC=true` задан? Worker рестартован?                                                     |
| Worker идёт, но ничего не обновляется | `reverse_sync_done_statuses` совпадает с реальными статусами Jira? Default — `Done`/`Closed`/`Resolved`/`Fixed` |
| `SSRF blocked`                        | Self-hosted Jira в LAN → `JIRA_ALLOW_LOCAL_DIAL=true`                                                           |

### Автоматически закрылось лишнее

Сначала проверьте, что все три условия действительно были выполнены — без
любого из них закрытие не должно происходить:

1. `FEATURE_AUTO_VERIFY_FIXES=true` — на всей установке;
2. признак `auto_verify_fixes_enabled` — в настройках проекта;
3. `verify_fixes=true` — в параметрах конкретной загрузки.

Затем проверьте кворум: закрытие должно происходить только после
`AUTO_VERIFY_ABSENT_THRESHOLD` последовательных проверок, давших
«отсутствует» (по умолчанию 3). Текущее состояние счётчика хранится в поле
`auto_verify_absent_streak` каждой находки — любое обнаружение сбрасывает его
в ноль.

```sql
-- Что закрылось за период и с каким счётчиком отсутствий
SELECT id, title, current_status, auto_verify_absent_streak, updated_at
FROM findings
WHERE current_status = 'fixed'
  AND updated_at BETWEEN '2026-06-01' AND '2026-06-02'
ORDER BY updated_at;
```

!!! danger "Перед откатом"

    Массовый откат состояний — необратимая операция, затрагивающая сроки
    устранения и связанные задачи в трекере. Сделайте резервную копию базы,
    выполните запрос сначала как `SELECT`, убедитесь в объёме выборки — и
    только потом меняйте состояния. Возвращать следует в то состояние, в
    котором находка была до закрытия (обычно `confirmed` или `in_progress`),
    а не в несуществующее `open`.

    Если условия из списка выше **не** выполнялись, а закрытие всё равно
    произошло — это дефект, и его стоит зафиксировать до отката, сохранив
    выборку.

## Notifications

### Уведомления не приходят

```bash
# Глубина очереди > 0? Worker крутит?

# 2. Логи
docker compose logs worker | grep -i notif

# 3. dry-run проверка
# В env: NOTIFICATIONS_DRY_RUN=true → перезапустить worker
# Логи должны показать сообщение, которое было бы отправлено
```

| Симптом                              | Fix                                                              |
| ------------------------------------ | ---------------------------------------------------------------- |
| Очередь пустая, но events происходят | Notification rules не настроены в Project → Notifications        |
| Очередь растёт, не уменьшается       | Worker не запущен (`docker compose ps worker`)                   |
| Telegram: 400 Bad Request            | Chat ID формат: для каналов `-100...`, для групп — отрицательный |
| Telegram: chat not found             | Бот не добавлен в чат                                            |
| Mattermost: 400 / 404                | Webhook удалён в Mattermost — пересоздайте                       |

## SARIF Upload

### Сканер работает, но находки НЕ появляются в Hub (`404 page not found` при upload)

Симптом в логах DomainScope (или другого сканера):

```
zap sarif upload failed — находки НЕ доставлены в Hub  error="404 — маршрут или продукт не найден ..."
```

Сканер находит уязвимости, но загрузка SARIF возвращает **404**. `page not found` — это
ответ Hub на **несматченный маршрут**, почти всегда это misconfig, а НЕ отсутствие ресурса:

1. **`*_SARIF_API_ENDPOINT` содержит `/api/v1`.** Endpoint должен быть **корнем Hub**
   (`https://hub.example.com`), клиент сам дописывает `/api/v1/products/<id>/reports`.
   С хвостом `/api/v1` путь удваивается → 404. *(Клиент DomainScope **НЕ** стрипает
   хвостовой `/api/v1` — он строит URL через `url.JoinPath(baseURL, "/api/v1/products/...")`,
   поэтому endpoint обязан быть корнем без `/api/v1`. Любой хвост `/api/v1` в endpoint'е
   приведёт к удвоению пути и 404.)*
2. **`*_SARIF_PRODUCT_ID` пустой или указывает на несуществующий в Hub продукт.**
   В Helm проверьте, что `sarifProductId` зарезолвился (umbrella прокидывает UUID
   default-продукта через secret). Пустой product_id раньше молча схлопывал URL.

Проверка из пода сканера:

```bash
# Должно вернуть 202/4xx с JSON, а НЕ "404 page not found":
curl -s -o /dev/null -w '%{http_code}\n' -X POST \
  -H "X-API-Key: $DOMAINSCOPE_SARIF_API_TOKEN" -F file=@/dev/null \
  "$DOMAINSCOPE_SARIF_API_ENDPOINT/api/v1/products/$DOMAINSCOPE_SARIF_PRODUCT_ID/reports"
```

Стартовый лог сканера (`sarif upload configured`) печатает `api_endpoint`,
`product_id_set`, `auto_upload` — сверьте их сразу после старта.

### `413 Payload Too Large`

```nginx
# nginx
client_max_body_size 200M;
```

```yaml
# K8s ingress
nginx.ingress.kubernetes.io/proxy-body-size: 200m
```

### `422 Unprocessable Entity: limit exceeded`

SARIF превысил один из hard-лимитов (см. [`integration-sarif.md`](integration-sarif.md)):

- Разбейте отчёт на несколько (несколько runs в разных файлах)
- Уменьшите количество results (фильтр на стороне сканера)

### Findings не дедуплицируются

Между прогонами сканера `rule_id` и `location.physicalLocation.artifactLocation.uri` должны быть стабильны. Если сканер генерит уникальные ID каждый раз — finding'и будут размножаться.

Проверка dedup_hash:

```sql
SELECT rule_id, location, COUNT(*)
FROM findings
WHERE product_id = '<uuid>'
GROUP BY rule_id, location
HAVING COUNT(*) > 5
ORDER BY COUNT(*) DESC;
```

### Severity всегда INFO

Сканер не выставляет `level` / `properties.severity` — выставьте поле в SARIF на стороне сканера (см. [`integration-sarif.md`](integration-sarif.md)).

### `500 Internal Server Error — Failed to save file` при upload

В отличие от 404 (misconfig endpoint), 500 «Failed to save file» означает, что
запрос **дошёл** до Hub, но backend не смог записать файл отчёта на диск:

- **PVC переполнен (ENOSPC).** Backend пишет отчёты в `STORAGE_PATH`
  (`/app/storage/reports`), файлы хранятся по retention (`CLEANUP_RETENTION_*`,
  по умолчанию completed 7 дней). При частых сканах раздел забивается. Увеличьте
  `pvc.backendStorage.size` (по умолчанию в чарте 5Gi) или уменьшите retention.
  > На k3s `local-path` лимит PVC не энфорсится (раздел = диск ноды), поэтому
  > переполнение проявляется только на реальных CSI (Ceph/Longhorn/cloud).
- **Нет прав на запись.** Backend — non-root (uid 10001). Каталог
  `/app/storage` должен быть writable для группы fsGroup. Чарт ставит
  `fsGroup: 10001` — если переопределяли securityContext, проверьте права:
  `kubectl -n <ns> exec deploy/<rel>-backend -- ls -la /app/storage`.

Проверка занятости:

```bash
kubectl -n <ns> exec deploy/<rel>-backend -- df -h /app/storage
```

## Развёртывание на k3s (storage / DNS / порядок запуска)

### PVC висит в `Pending`, поды не стартуют

```bash
kubectl -n <ns> get pvc
kubectl -n <ns> describe pvc <name>   # ищите "no persistent volumes available" / "storageclass not found"
```

- **`storageclass not found`** — в чарте указан несуществующий `storageClassName`.
  Чарты по умолчанию оставляют его **пустым** (`""`) → кластер берёт свой
  default storageclass (работает на k3s, облаках). Если задавали явно — проверьте
  `kubectl get storageclass` и впишите существующий.
- Нет default storageclass в кластере — задайте `storageClassName` для всех PVC
  явно (values каждого чарта) либо пометьте storageclass как default.

### Сканер не находит цели / нет находок (DNS из подов)

Симптом: в логах DomainScope `ip resolve failed ... no such host`, discovery
завершается с `scannable_ips:0`.

Причина: нода использует systemd-resolved, `/etc/resolv.conf` указывает на stub
`127.0.0.53`, недостижимый из подов. CoreDNS по умолчанию форвардит на него.

```bash
kubectl -n kube-system get cm coredns -o jsonpath='{.data.Corefile}' | grep forward
# плохо: forward . /etc/resolv.conf  →  должно быть: forward . 1.1.1.1 8.8.8.8
```

`install.sh` чинит это автоматически (флаг `--dns "<ip...>"` для своих
резолверов, `--no-dns-fix` чтобы не трогать). Вручную — см.
[ручную установку](deploy-k3s-manual.md), шаг «Фикс DNS».

> Для сканирования **внутренней** инфраструктуры (split-horizon DNS) укажите
> внутренние резолверы: `--dns "10.0.0.53 10.0.0.54"`.

### `hub scope unavailable, fail-closed` — сканер пропускает циклы

DomainScope не смог получить scope из Hub Scope API и (безопасно) пропустил скан.
Обычно это **гонка старта**: DomainScope поднялся раньше готовности Hub backend.

Чарт ставит init-контейнер `wait-for-hub`, который ждёт `/health` backend перед
стартом DomainScope — на штатной установке гонки нет. Если видите это **после**
старта — проверьте доступность backend и валидность SA-токена:

```bash
kubectl -n <ns> logs deploy/<rel>-domainscope-domainscope -c domainscope | grep -i scope
# scope_unavail должно стать 0 после готовности backend
```

### Backend/worker в CrashLoop в первые минуты

Чарт ставит init-контейнер `wait-for-postgres` (backend/worker ждут БД перед
стартом). Если CrashLoop сохраняется после готовности postgres — смотрите логи
backend (миграции, секреты): `kubectl -n <ns> logs deploy/<rel>-backend`.

### `post-install hooks failed` при `helm install`

seed-admin Job (создаёт admin + default-проект) ждёт, пока backend домигрирует
БД. На медленном старте (холодный pull образов, эмуляция amd64 на ARM) дефолтных
5 мин helm не хватает. `install.sh` ставит `--timeout 15m`; для ручного helm
добавьте `--timeout 15m` (или `HELM_TIMEOUT=30m ./install.sh`).

## LLM / Sandbox

### LLM-jobs не выполняются

- Backend имеет `LLM_WORKERS=0`? (должен)
- Worker имеет `LLM_WORKERS > 0`? (должен)
- `LLM_API_KEY` и `LLM_BASE_URL` заданы в worker?
- Проверьте логи worker по записям про queue `llm_triage` — глубина > 0, есть failed jobs?

### `429 Too Many Requests`

Превышен rate limit провайдера. Уменьшите `LLM_WORKERS` (например, 3 → 1) или попросите квоту у провайдера.

### Sandbox не запускается

```
ERROR sandbox failed: image not found
```

Проверьте:

- `SANDBOX_IMAGE` доступен (`docker pull` из worker)
- Для приватного registry — credentials прокинуты (`docker login` в worker host)
- В k8s — image pull secret прикреплён к serviceAccount

### Sandbox timeout

Увеличьте `SANDBOX_TIMEOUT_SECONDS` (default 120). Для медленных сетей — 300-600.

## DomainScope

### Discovery не находит ничего нового

```bash
docker compose -f /opt/domainscope/docker/docker-compose.yml logs domain-scope | grep -i subfinder
```

| Признак                             | Fix                                                                  |
| ----------------------------------- | -------------------------------------------------------------------- |
| `subfinder: no sources configured`  | Discovery-провайдеры недоступны из сети — проверьте outbound HTTPS |
| `DNS resolve failed`                | Нет DNS-resolver'a в контейнере. Проверьте `/etc/resolv.conf`        |
| Cycle крутится, но domains в БД нет | Проверьте `DOMAINSCOPE_DOMAINS` — задан?                             |

### Nuclei не сканирует

| Признак                            | Fix                                                                   |
| ---------------------------------- | --------------------------------------------------------------------- |
| `nuclei-templates not found`       | `nuclei-templates-init` контейнер должен отработать. Проверьте volume |
| `DOMAINSCOPE_NUCLEI_ENABLED=false` | Поставьте `true` и перезапустите                                      |
| Cycle не стартует                  | Проверьте, что в БД есть HTTP-targets (`port_scans` с port 80/443)    |

### OpenVAS не подключается

- `DOMAINSCOPE_OPENVAS_HOST` доступен из DomainScope контейнера? `docker compose exec domain-scope nc -zv $DOMAINSCOPE_OPENVAS_HOST 9390`
- Креды правильные? Логин в OpenVAS UI работает?
- Feed init завершился? OpenVAS первые 10-30 минут после старта качает CVE-фиды и не отвечает на GMP

### SARIF не приходит в Hub

```bash
docker compose -f /opt/domainscope/docker/docker-compose.yml logs domain-scope | grep -i sarif
```

| Признак                       | Fix                                                                     |
| ----------------------------- | ----------------------------------------------------------------------- |
| `401 Unauthorized`            | `DOMAINSCOPE_HUB_API_TOKEN` неверный или истёк                          |
| `403 Forbidden`               | Service Account не имеет permission на product                          |
| `connection refused`          | `DOMAINSCOPE_HUB_API_ENDPOINT` не доступен. Проверьте сетевую связность |
| Cycle вообще не делает upload | `DOMAINSCOPE_SARIF_AUTO_UPLOAD=true`?                                   |

### Scope proposals не появляются

```bash
# Hub side
docker compose exec postgres psql -U securityhub -d securityhub -c \
  "SELECT created_at, source, scanner_name, value FROM scope_proposals
   WHERE created_at > NOW() - INTERVAL '24 hours' ORDER BY created_at DESC LIMIT 20;"
```

Если пусто — DomainScope не шлёт. Логи:

```bash
docker compose -f /opt/domainscope/docker/docker-compose.yml logs domain-scope | grep proposal
```

## NetBox

### Sync падает с `403`

NetBox token имеет IP allowlist? Добавьте IP Hub/DomainScope.

### Дубликаты scope entries

Проверьте, что не запущены два sync job на один проект (UI Hub → Project → Scope → Sync jobs).

## Performance

### БД медленная

```sql
-- Топ медленных запросов (если pg_stat_statements включён)
SELECT query, calls, mean_exec_time, max_exec_time
FROM pg_stat_statements
ORDER BY mean_exec_time DESC LIMIT 10;

-- Активные подключения
SELECT pid, state, query_start, query FROM pg_stat_activity
WHERE state='active' ORDER BY query_start;

-- Bloat
SELECT schemaname, tablename, n_dead_tup, n_live_tup
FROM pg_stat_user_tables WHERE n_dead_tup > 1000
ORDER BY n_dead_tup DESC;
```

Возможные фиксы:

- `VACUUM ANALYZE` (или `VACUUM FULL` для bloat > 30%)
- Добавить индекс на колонки, по которым WHERE
- Увеличить `shared_buffers` / `work_mem`

### Worker отстаёт от очередей

```bash
# Глубина очередей через логи worker
# Если > 1000 и растёт — добавьте воркеров:
```

В compose:

```yaml
worker:
  deploy:
    replicas: 2 # вместо 1
```

В K8s:

```bash
kubectl scale deploy hub-worker --replicas=3 -n hub
```

Или увеличьте параллелизм внутри:

```ini
DISPATCHER_WORKERS=20
TELEGRAM_NOTIFICATION_WORKERS=10
MATTERMOST_NOTIFICATION_WORKERS=20
```

## Сбор диагностики для bug report

При issue в трекер прикладывайте:

```bash
# 1. Версии
curl https://hub.example.com/version
# DomainScope:
docker compose exec domain-scope domain-scope --version

# 2. Конфиг (без секретов!)
docker compose config | grep -v PASSWORD | grep -v SECRET | grep -v TOKEN

# 3. Логи последнего часа
docker compose logs --since 1h backend > backend.log
docker compose logs --since 1h worker > worker.log

# 4. Состояние очередей (если проблема с jobs)

# 5. Состояние БД (если связано)
docker compose exec postgres psql -U securityhub -d securityhub -c \
  "SELECT version_id FROM goose_db_version ORDER BY tstamp DESC LIMIT 1;"

# 6. Stacktrace (если panic)
# Из логов backend
```

Обращение в поддержку — через канал, предоставленный поставщиком.

## Связанные документы

- [`operations.md`](operations.md) — backup, мониторинг
- [`upgrades.md`](upgrades.md) — rollback при неудачном обновлении


## Если это не неисправность

Часть наблюдаемого поведения — не сбой, а известное свойство: сообщение о
ненайденном на диске файле отчёта при каждой загрузке, отсутствие счётчиков в
ответе на загрузку, схлопывание находок без CVE на одном порту. Прежде чем
искать причину, сверьтесь с [Известными ограничениями](limitations.md).
