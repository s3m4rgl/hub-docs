# Установка DomainScope

DomainScope ставится отдельно от Hub. Поставка — готовый Docker-образ. Сборка из исходников не предполагается.

Два основных способа: **Docker Compose** (рекомендуется для standalone) и **Kubernetes** (как часть umbrella-чарта Hub).

## Способ 1: Docker Compose

### Предусловия

- Docker Engine 24+, Docker Compose v2.20+
- 4 vCPU / 8 GB RAM минимум (с OpenVAS: 6+12)
- 50 GB disk (Nuclei templates, OpenVAS feeds, БД)
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
DOMAINSCOPE_HUB_API_ENDPOINT=https://hub.example.com
DOMAINSCOPE_HUB_API_TOKEN=<api-key из Hub Service Account>
DOMAINSCOPE_HUB_PROJECT_IDS=<project-uuid>

# === SARIF upload ===
DOMAINSCOPE_SARIF_ENABLED=true
DOMAINSCOPE_SARIF_AUTO_UPLOAD=true
DOMAINSCOPE_SARIF_PRODUCT_ID=<product-uuid>
# Корень Hub БЕЗ /api/v1 — DomainScope сам дописывает /api/v1/products/<id>/reports.
# С хвостом /api/v1 путь удвоится → 404 и находки НЕ доедут в Hub.
DOMAINSCOPE_SARIF_API_ENDPOINT=https://hub.example.com
DOMAINSCOPE_SARIF_API_TOKEN=<тот же api-key или отдельный>
DOMAINSCOPE_SARIF_SCANNER_NAME=domain-scope
DOMAINSCOPE_SARIF_SCANNER_NODE=domain-scope-prod-01

# === Опц. фильтры ===
DOMAINSCOPE_SARIF_IP_SCOPE=public      # all / public / private

# === Postgres password ===
POSTGRES_PASSWORD=<strong-password>
```

> **Service Account в Hub**: до старта DomainScope создайте Service Account в Hub (см. [Загрузка отчётов внешних сканеров](integration-sarif.md)) с permission на нужный project/product. Скопируйте API key — это `DOMAINSCOPE_HUB_API_TOKEN`.

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
INFO Starting discovery cycle (loop=21600s)
INFO Subfinder found N new subdomains for example.com
INFO Resolving DNS for N domains
INFO Starting port scan cycle
INFO SARIF uploaded to https://hub.example.com (results=N)
```

### 4. Проверка состояния

Health-сервер слушает на `:8080` по умолчанию (`DOMAINSCOPE_HEALTH_ADDR`), включается через `DOMAINSCOPE_HEALTH_ENABLED=true`:

```bash
curl http://127.0.0.1:8080/health
curl http://127.0.0.1:8080/ready
```

## Способ 2: Kubernetes

DomainScope включён в umbrella-чарт `hub-platform` (см. [Развёртывание в Kubernetes](deploy-kubernetes.md)).

В `values.yaml`:

```yaml
domainscope:
  enabled: true
  image:
    tag: "0.30"

  env:
    DOMAINSCOPE_DOMAINS: "example.com,subsidiary.com"
    DOMAINSCOPE_HUB_API_ENDPOINT: "http://hub-backend:8082"

  postgres:
    enabled: true
    storage: 30Gi

  scanners:
    nuclei:
      enabled: true
    openvas:
      enabled: false # требует отдельный openvas chart
    tlsx:
      enabled: true
    zap:
      enabled: false # требует отдельный owasp-zap chart

  secrets:
    existingSecretName: domainscope-secrets
```

Секрет:

```bash
kubectl -n hub create secret generic domainscope-secrets \
  --from-literal=postgresPassword='<strong-random>' \
  --from-literal=hubApiToken='<token from Hub SA>' \
  --from-literal=netboxApiToken='<если NetBox sync>'
```

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
docker compose exec domain-scope domain-scope --version

# Health (default :8080, переопределяется DOMAINSCOPE_HEALTH_ADDR)
curl http://localhost:8080/health
curl http://localhost:8080/ready

# Логи (события по циклам)
docker compose logs domain-scope | tail -100

# БД заполняется
docker compose exec postgresql psql -U postgres -d domainscope -c "SELECT COUNT(*) FROM domains;"
docker compose exec postgresql psql -U postgres -d domainscope -c "SELECT COUNT(*) FROM port_scans;"

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
  domainscope:
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

## Связанные документы

- [Управление сканерами DomainScope](domainscope-scanners.md) — управление сканерами
- [Синхронизация с NetBox](domainscope-netbox.md) — NetBox sync
- [Происхождение записей периметра](domainscope-trails.md) — discovery trails
- [Ручная перепроверка](manual-rescan.md) — UI-кнопки «Перепроверить» и автозакрытие
