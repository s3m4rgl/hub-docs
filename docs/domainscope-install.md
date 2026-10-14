# Установка DomainScope

DomainScope ставится отдельно от Hub. Поставка — готовый Docker-образ. Сборка из исходников не предполагается.

Два основных способа: **Docker Compose** (рекомендуется для standalone) и **Kubernetes** (как часть umbrella-чарта Hub).

## Способ 1: Docker Compose

### Предусловия

- Docker Engine 24+, Docker Compose v2.20+
- 4.5 vCPU / 4.5 GB RAM (лимиты DomainScope и его базы; запросы — 0.6 ядра и
  0.7 GB); с OpenVAS — ещё 2 vCPU и 8 GB
- 20 GB диска (база DomainScope 5 GB, логи, образ); с OpenVAS — ещё 40 GB под
  базы описаний уязвимостей
- Доступ к Docker registry с образом DomainScope
- Outbound HTTPS (для nuclei-templates и upload в Hub)

### 1. Артефакты поставки

Получите от поставщика:

| Файл                 | Назначение                                   |
| -------------------- | -------------------------------------------- |
| `docker-compose.yml` | Compose-стек со ссылкой на образ DomainScope |
| `.env.example`       | Шаблон конфигурации                          |

Положите в рабочую директорию:

```bash
sudo mkdir -p /opt/domainscope
sudo cp docker-compose.yml .env.example /opt/domainscope/
cd /opt/domainscope
```

### 2. Создать `.env`

```bash
cp .env.example .env
```

Минимальный набор:

```ini
# === DomainScope core ===
DOMAINSCOPE_DOMAINS=example.com,subsidiary.com
DOMAINSCOPE_DSN=host=postgresql user=postgres password=<strong-password> dbname=domainscope port=5432 sslmode=disable

# === Hub integration ===
DOMAINSCOPE_HUB_ENABLED=true
# Корень Hub без /api/v1: здесь хвост не отрезается.
DOMAINSCOPE_HUB_API_ENDPOINT=https://hub.example.com
DOMAINSCOPE_HUB_API_TOKEN=<api-key из Hub Service Account>
DOMAINSCOPE_HUB_PROJECT_IDS=<project-uuid>

# === SARIF upload ===
DOMAINSCOPE_SARIF_ENABLED=true
DOMAINSCOPE_SARIF_AUTO_UPLOAD=true
DOMAINSCOPE_SARIF_PRODUCT_ID=<product-uuid>
# Корень Hub — DomainScope сам дописывает /api/v1/products/<id>/reports
# (хвост /api/v1, если он есть, отрезается).
DOMAINSCOPE_SARIF_API_ENDPOINT=https://hub.example.com
DOMAINSCOPE_SARIF_API_TOKEN=<тот же api-key или отдельный>
# Имя сканера (engine) в отчётах; по умолчанию DomainScope.
DOMAINSCOPE_SARIF_SCANNER_NAME=DomainScope
DOMAINSCOPE_SARIF_SCANNER_NODE=domain-scope-prod-01

# === Опц. фильтры ===
DOMAINSCOPE_SARIF_IP_SCOPE=public      # all / public / private

# === Postgres password ===
POSTGRES_PASSWORD=<strong-password>
```

> **Service Account в Hub**: до старта DomainScope создайте Service Account в Hub (см. [Загрузка отчётов внешних сканеров](integration-sarif.md)) и выдайте ему право `upload_report` **на проект** — одной этой записи достаточно и для загрузки отчётов во все продукты проекта, и для записи предложений, инвентаря и отчёта о резолве. Право `manage_scope` сканеру не нужно. Скопируйте API key — это `DOMAINSCOPE_HUB_API_TOKEN` (он же обычно `DOMAINSCOPE_SARIF_API_TOKEN`).
>
> Полный процесс связки воркера с проектом — [Связка DomainScope и Hub](perimeter-integration.md).

### 3. Запуск

```bash
docker compose pull
docker compose up -d
```

Стек поднимает:

- `nuclei-templates-init` (one-shot, инициализирует templates в volume)
- `postgresql` (БД)
- `domain-scope` — сам сервис, образ `dexionius/domain-scope` (указывайте явный тег версии)

Проверка:

```bash
docker compose ps
docker compose logs -f domain-scope
```

После старта в логах:

```
INFO  discovery cycle started
INFO  subfinder started          {"domains": 1, "enumerating": 1, "reused_from_db": 0, ...}
INFO  subfinder phase complete   {"domains": 1}
INFO  dns resolve phase done     {"scannable_ips": N, "ignored_ips": 0, ...}
INFO  discovery cycle done       {"scannable_ips": N, "ignored_ips": 0}
INFO  port scan cycle started
INFO  sarif delivery             {"hosts_reported": N, "total_findings": N}
INFO  port scan cycle done
```

Сканирование портов ждёт окончания первого цикла обнаружения (`waiting for
first discovery cycle to complete`), если в базе ещё нет данных. Загрузка
отчёта по каждому хосту пишется на уровне debug (`sarif report uploaded`),
ошибка загрузки — на уровне error.

### 4. Проверка состояния

Health-сервер слушает на `:8080` по умолчанию (`DOMAINSCOPE_HEALTH_ADDR`), включается через `DOMAINSCOPE_HEALTH_ENABLED=true`. Проверка изнутри контейнера (в образе есть `wget`, `curl` нет):

```bash
docker compose exec domain-scope wget -qO- http://localhost:8080/health
docker compose exec domain-scope wget -qO- http://localhost:8080/ready
```

`/ready` отвечает `503`, пока не завершились первые циклы discovery и
сканирования портов (и Nuclei, ZAP, если они включены).

## Способ 2: Kubernetes

Чарт DomainScope — `charts/domainscope`. Он ставится сам по себе или в составе
umbrella-чарта `hub-platform` под алиасом `domainscope` (см.
[Развёртывание в Kubernetes](deploy-kubernetes.md)). Отдельного блока `scanners`
в чарте нет: сканеры включаются ключами `domainscope.env.*`, а переменные без
своего ключа (TLSX, тонкая настройка nmap, интервалы Nuclei/TLSX/ZAP, health,
rescan) — списком `domainscope.extraEnv`. Полный перечень переменных —
[Переменные окружения: DomainScope](env-domainscope.md).

### В составе hub-platform

Umbrella сама создаёт секрет `<release>-domainscope-secrets` (DSN, ключ
сервисной учётной записи Hub, ID проекта и продукта, пароль OpenVAS, инстансы
ZAP) и уже включает Hub Scope API, загрузку SARIF, OpenVAS и ZAP. Ключи самого
чарта DomainScope лежат в umbrella на уровень глубже — под
`domainscope.domainscope.*`:

```yaml
domainscope:
  enabled: true
  postgres:
    storage:
      size: 5Gi            # умолчание чарта
  domainscope:
    image:
      tag: "0.34"
    env:
      netboxEnabled: "true"
      netboxApiEndpoint: "https://netbox.example.com"
    extraEnv:
    - name: DOMAINSCOPE_TLSX_ENABLED
      value: "true"

secrets:
  domainscopeNetboxApiToken: "<токен NetBox>"   # попадёт в netboxApiToken секрета
```

!!! warning "Выключая `openvas` или `zap` в umbrella, выключите их и в DomainScope"

    `domainscope.domainscope.env.openvasEnabled` и `zapEnabled` в umbrella
    стоят в `"true"` независимо от `openvas.enabled` и `zap.enabled`. Без
    subchart пароль OpenVAS и список инстансов ZAP в секрете пусты, и
    DomainScope останавливается на проверке конфигурации. Задайте
    `openvasEnabled: "false"` / `zapEnabled: "false"` вместе с выключением
    subchart.

### Отдельный чарт

Без umbrella чарт по умолчанию сам создаёт секрет `<fullname>-secrets` из
блока `secrets` (пустой `postgresPassword` генерируется):

```yaml
secrets:
  sarifApiToken: "<api-key сервисной учётной записи Hub>"
  netboxApiToken: ""
  openvasPassword: ""

domainscope:
  image:
    tag: "0.34"
  env:
    domains: "example.com,subsidiary.com"
    sarifEnabled: "true"
    sarifAutoUpload: "true"
    sarifApiEndpoint: "http://hub-backend:8082"   # корень Hub
    sarifProductId: "<product-uuid>"
    nucleiEnabled: "true"
    openvasEnabled: "false"
    zapEnabled: "false"

postgres:
  enabled: true
  storage:
    size: 5Gi
```

Для Hub Scope API (`domainscope.env.hubEnabled: "true"` и `hubApiEndpoint`)
нужны ключи `hubApiToken` и `hubProjectId`, а их создаваемый чартом секрет не
содержит. В этом случае создайте секрет сами и укажите его в
`secrets.existingSecretName` — тогда чарт свой секрет не создаёт:

```bash
kubectl -n hub create secret generic domainscope-secrets \
  --from-literal=postgresPassword='<strong-random>' \
  --from-literal=dsn='postgres://domainscope:<тот же пароль>@<fullname>-postgres:5432/domainscope?sslmode=disable' \
  --from-literal=hubApiToken='<api-key сервисной учётной записи Hub>' \
  --from-literal=hubProjectId='<project-uuid>' \
  --from-literal=sarifApiToken='<тот же api-key или отдельный>' \
  --from-literal=sarifProductId='<product-uuid>'
```

Ключи `dsn` и `postgresPassword` обязательны всегда, `hubApiToken` и
`hubProjectId` — при `hubEnabled: "true"`; `sarifApiToken`, `sarifProductId`,
`netboxApiToken`, `openvasPassword` и `zapInstancesJson` необязательны.
`<fullname>` — `<release>-domainscope`, а если имя релиза уже содержит
`domainscope`, то само имя релиза.

Чарт не включает health-сервер (liveness-проба — `pgrep`) и не создаёт Service
для DomainScope.

## Связанные сервисы

### OpenVAS

Если включён `DOMAINSCOPE_OPENVAS_ENABLED=true`, нужен внешний OpenVAS cluster. В рамках Kubernetes-поставки доступен subchart `openvas`. Поднимется gvmd/gsad/ospd/redis с собственным feed-init job.

DomainScope подключается:

```ini
DOMAINSCOPE_OPENVAS_HOST=openvas-gvmd
DOMAINSCOPE_OPENVAS_PORT=9390
DOMAINSCOPE_OPENVAS_USERNAME=admin
DOMAINSCOPE_OPENVAS_PASSWORD=<из секрета>
```

### OWASP ZAP

Subchart `owasp-zap`. DomainScope подключается:

```ini
DOMAINSCOPE_ZAP_ENABLED=true
# JSON-массив инстансов (url + api_key на каждый). Отдельных
# DOMAINSCOPE_ZAP_INSTANCES / DOMAINSCOPE_ZAP_API_KEY нет.
DOMAINSCOPE_ZAP_INSTANCES_JSON=[{"url":"http://zap-1:8090","api_key":"<из секрета>"},{"url":"http://zap-2:8090","api_key":"<из секрета>"}]
```

### NetBox

См. [Синхронизация с NetBox](domainscope-netbox.md). Включается:

```ini
DOMAINSCOPE_NETBOX_ENABLED=true
DOMAINSCOPE_NETBOX_API_ENDPOINT=https://netbox.example.com
DOMAINSCOPE_NETBOX_API_TOKEN=<token>
```

## Проверка после установки

```bash
# Версия
docker compose exec domain-scope /domain-scope --version

# Health (при DOMAINSCOPE_HEALTH_ENABLED=true; default :8080, переопределяется DOMAINSCOPE_HEALTH_ADDR)
docker compose exec domain-scope wget -qO- http://localhost:8080/health
docker compose exec domain-scope wget -qO- http://localhost:8080/ready

# Логи (события по циклам)
docker compose logs domain-scope | tail -100

# БД заполняется
docker compose exec postgresql psql -U postgres -d domainscope -c "SELECT COUNT(*) FROM domains;"
docker compose exec postgresql psql -U postgres -d domainscope -c "SELECT COUNT(*) FROM findings;"   # открытые порты

# В Hub приходят отчёты
# Hub UI → Project → Reports — должен появиться новый report через ~5-15 мин после первого цикла
```

## Обновление

```bash
cd /opt/domainscope
docker compose pull
docker compose up -d
```

Указывайте явный тег версии, а не `latest`, и следите, чтобы он существовал у всех компонентов — см. [Обновления](upgrades.md#выбор-версии).

## Резервное копирование

```bash
# БД
docker compose exec postgresql pg_dump -U postgres domainscope | gzip > ds-backup-$(date +%Y%m%d).sql.gz
```

Nuclei templates обычно бэкапить не нужно — пересоздаются автоматически.

## Удаление

```bash
docker compose down -v          # с томами!
sudo rm -rf /opt/domainscope
```

## Manual rescan webhook (опционально)

Если на Hub'e включена функция [«Перепроверить»](manual-rescan.md), DomainScope может принимать обращения от Hub'a и запускать ре-скан по запросу оператора. Без `RESCAN_API_KEY` в окружении этот сервер не стартует.

Переменные окружения DomainScope:

| Переменная                    | Default | Описание                                                                                |
| ----------------------------- | ------- | --------------------------------------------------------------------------------------- |
| `RESCAN_API_KEY`              | —       | shared secret; **должен совпадать** с `DOMAINSCOPE_RESCAN_API_KEY` на Hub'е. Без него HTTP-сервер не стартует. |
| `RESCAN_LISTEN_ADDR`          | `:8087` | bind-адрес HTTP-сервера                                                                  |
| `RESCAN_EXPECTED_PROJECT_ID`  | —       | (опционально) UUID проекта в Hub'е. Если задан, webhook принимает только этот project_id. |

Compose-фрагмент:

```yaml
services:
  domain-scope:
    environment:
      RESCAN_API_KEY: <тот же ключ, что на Hub>
      RESCAN_LISTEN_ADDR: ":8087"
    ports:
      - "8087:8087"
```

После запуска проверить, что сервер поднялся:

```bash
curl http://localhost:8087/healthz
# {"status":"ok"}
```

В Helm-чарте ключей для этих переменных нет: задайте их в
`domainscope.extraEnv` (ключ — через `valueFrom.secretKeyRef`). Service на порт
`8087` чарт не создаёт, его нужно добавить отдельно, чтобы Hub достучался до
сервера.

## Связанные документы

- [Управление сканерами DomainScope](domainscope-scanners.md) — управление сканерами
- [Синхронизация с NetBox](domainscope-netbox.md) — NetBox sync
- [Происхождение записей периметра](domainscope-trails.md) — discovery trails
- [Ручная перепроверка](manual-rescan.md) — UI-кнопки «Перепроверить» и автозакрытие
