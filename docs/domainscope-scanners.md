# Управление сканерами DomainScope

DomainScope содержит шесть независимых сканеров. Каждый — отдельный цикл со своим расписанием, env-переменными и опционально override'ом куда слать SARIF. Включаются/выключаются независимо.

## Сводная таблица

| Сканер                           | ENV-флаг                      | Default | Интервал (default)                              | SARIF override    |
| -------------------------------- | ----------------------------- | ------- | ----------------------------------------------- | ----------------- |
| **Subfinder + DNS**              | всегда вкл (часть discovery)  | on      | `DOMAINSCOPE_TIME_LOOP_DISCOVERY` = 21600s (6ч) | —                 |
| **Nmap port-scan + fingerprint** | всегда вкл (часть portscan)   | on      | `DOMAINSCOPE_TIME_LOOP_PORTSCAN` = 7200s (2ч)   | —                 |
| **Nuclei HTTP**                  | `DOMAINSCOPE_NUCLEI_ENABLED`  | `false` | `DOMAINSCOPE_TIME_LOOP_NUCLEI` = 3600s (1ч)     | `NUCLEI_SARIF_*`  |
| **OpenVAS CVE**                  | `DOMAINSCOPE_OPENVAS_ENABLED` | `false` | `DOMAINSCOPE_TIME_LOOP_OPENVAS` = 86400s (24ч)  | `OPENVAS_SARIF_*` |
| **TLSX**                         | `DOMAINSCOPE_TLSX_ENABLED`    | `false` | `DOMAINSCOPE_TIME_LOOP_TLSX` = 21600s (6ч)      | `TLSX_SARIF_*`    |
| **OWASP ZAP**                    | `DOMAINSCOPE_ZAP_ENABLED`     | `false` | `DOMAINSCOPE_TIME_LOOP_ZAP` = 14400s (4ч)       | `ZAP_SARIF_*`     |

Каждый сканер можно включить/выключить независимо — задайте `*_ENABLED=true/false` и перезапустите daemon. Discovery и portscan — встроены в core и всегда работают (можно лишь регулировать интервал).

## 1. Subfinder + DNS resolver (discovery)

**Что делает:**

- Запускает discovery для каждого seed-домена из `DOMAINSCOPE_DOMAINS` (через встроенный subfinder)
- Все найденные поддомены → DNS resolve (A/AAAA/CNAME записей)
- Новые домены добавляются в БД с `source=subfinder`
- Опционально: тянет дополнительные seed-домены из Hub (`scope_entry`) и NetBox (`netbox_dns`)

**Конфиг:**

```ini
DOMAINSCOPE_DOMAINS=example.com,subsidiary.com
DOMAINSCOPE_TIME_LOOP_DISCOVERY=21600        # каждые 6 часов
```

**Логи:**

```
INFO Subfinder cycle starting, seeds=2
INFO  example.com: 47 new subdomains found
INFO  subsidiary.com: 12 new subdomains found
INFO DNS resolved: 59/59 domains
```

## 2. Nmap port-scan + fingerprint

**Что делает:**

- Для каждого IP из БД запускает `nmap -sV -p <PORTS>`
- Извлекает service, product, version, banner
- Опционально: HTTP-fingerprinting (через native `net/http` Go)
- Результаты → `port_scans` таблица + SARIF в Hub

**Конфиг:**

```ini
DOMAINSCOPE_TIME_LOOP_PORTSCAN=7200          # каждые 2 часа
DOMAINSCOPE_TARGET_PORTS=22,80,443,3306,5432,8080,8443    # CSV
DOMAINSCOPE_SCANNER_WORKERS=20               # параллельные горутины (default: 20)
DOMAINSCOPE_SCANNER_MIN_RATE=500             # nmap --min-rate (0 = выключено)
DOMAINSCOPE_FINGERPRINT_TIMEOUT=10           # секунды на HTTP-fingerprint
```

**Производительность:**

- `SCANNER_WORKERS=20` — норма для 1k IP при базовом наборе портов
- `MIN_RATE=500` — агрессивный скан; уменьшите до `200` если провайдер шумит на abuse-traffic
- `MIN_RATE=0` — режим по умолчанию nmap (адаптивный)

**Безопасность:**

Nmap по умолчанию делает SYN-scan (требует raw sockets → CAP_NET_RAW). В docker-режиме DomainScope получает capability автоматически. В bare-metal:

```bash
sudo setcap cap_net_raw+ep /usr/local/bin/domain-scope
```

## 3. Nuclei HTTP scanner

**Что делает:**

- Берёт все обнаруженные HTTP/HTTPS эндпоинты (порты 80, 443, 8080, 8443 и любые с HTTP-fingerprint)
- Прогоняет встроенный nuclei с подключёнными templates
- Каждое срабатывание (info/low/medium/high/critical) → SARIF находка

**Включение:**

```ini
DOMAINSCOPE_NUCLEI_ENABLED=true
DOMAINSCOPE_NUCLEI_TEMPLATES_PATH=/app/nuclei-templates
DOMAINSCOPE_NUCLEI_CONCURRENCY=50            # параллельные запросы (default: 50)
DOMAINSCOPE_NUCLEI_SCAN_TIMEOUT=7200         # максимум на цикл, сек (default: 7200 = 2ч)
DOMAINSCOPE_NUCLEI_REQUEST_TIMEOUT=10        # 10s на HTTP-запрос
DOMAINSCOPE_TIME_LOOP_NUCLEI=3600            # каждый час
```

**Templates:**

Контейнер `nuclei-templates-init` загружает templates в общий volume при первом старте и обновляет при последующих запусках. Для air-gapped окружений путь к templates можно переопределить переменной `DOMAINSCOPE_NUCLEI_TEMPLATES_PATH` (например, монтируйте локальный набор как volume).

**Override SARIF для nuclei:**

```ini
DOMAINSCOPE_NUCLEI_SARIF_PRODUCT_ID=<отдельный product в Hub>
DOMAINSCOPE_NUCLEI_SARIF_API_TOKEN=<отдельный API key, опц.>
```

> У Nuclei **нет** собственного IP-scope override. Nuclei всегда использует глобальный `DOMAINSCOPE_SARIF_IP_SCOPE`. Per-scanner IP-scope override есть только у OpenVAS (`DOMAINSCOPE_OPENVAS_IP_SCOPE`) и ZAP (`DOMAINSCOPE_ZAP_IP_SCOPE`).

## 4. OpenVAS CVE scanner

**Что делает:**

- Через GMP (Greenbone Management Protocol) на :9390 создаёт scan task в OpenVAS
- Передаёт IP-цели из БД DomainScope
- Дожидается завершения (минуты — часы для большого scope)
- Парсит результаты, формирует SARIF

**Включение:**

```ini
DOMAINSCOPE_OPENVAS_ENABLED=true
DOMAINSCOPE_OPENVAS_HOST=openvas-gvmd        # K8s service / docker container
DOMAINSCOPE_OPENVAS_PORT=9390                # GMP
DOMAINSCOPE_OPENVAS_USERNAME=admin
DOMAINSCOPE_OPENVAS_PASSWORD=<секрет>
DOMAINSCOPE_OPENVAS_SCAN_CONFIG_ID=          # пусто = Full and fast
DOMAINSCOPE_TIME_LOOP_OPENVAS=86400          # каждые 24 часа
```

**Scan configurations** (предустановленные в OpenVAS):

- `daba56c8-73ec-11df-a475-002264764cea` — **Full and fast** (default, рекомендуется)
- `698f691e-7489-11df-9d8c-002264764cea` — Full and very deep (медленнее, ловит больше)
- `bbca7412-a950-11e3-9109-406186ea4fc5` — System Discovery

Скопируйте UUID нужной конфигурации в `DOMAINSCOPE_OPENVAS_SCAN_CONFIG_ID`.

**Производительность:**

OpenVAS-скан занимает много времени. Для 500 IP — типично 4-8 часов. Поэтому `TIME_LOOP_OPENVAS=86400` (раз в сутки).

**Override:**

```ini
DOMAINSCOPE_OPENVAS_SARIF_PRODUCT_ID=<product-openvas>
DOMAINSCOPE_OPENVAS_SARIF_API_TOKEN=<...>
DOMAINSCOPE_OPENVAS_IP_SCOPE=public
```

## 5. TLSX (TLS/SSL analyzer)

**Что делает:**

- Для каждого эндпоинт с HTTPS-портом запрашивает certificate
- Извлекает: issuer, subject, SAN, expiry date, signature algo
- Формирует находки:
  - `LOW` — cert expires in 30 days (`DOMAINSCOPE_TLSX_CERT_EXPIRY_DAYS`)
  - `MEDIUM` — cert expires in 7 days
  - `HIGH` — cert expired
  - `MEDIUM` — weak signature algo (`md5`/`sha1`)

**Включение:**

```ini
DOMAINSCOPE_TLSX_ENABLED=true
DOMAINSCOPE_TLSX_CONCURRENCY=50              # параллельные хосты (default: 50)
DOMAINSCOPE_TLSX_CERT_EXPIRY_DAYS=30         # порог LOW-warning, дней (default: 30)
DOMAINSCOPE_TIME_LOOP_TLSX=21600             # каждые 6 часов
```

**Override:**

```ini
DOMAINSCOPE_TLSX_SARIF_PRODUCT_ID=<product-tls>
DOMAINSCOPE_TLSX_SARIF_API_TOKEN=<...>
```

## 6. OWASP ZAP (DAST)

**Что делает:**

- Использует внешние ZAP daemon'ы по REST API
- Запускает full scan (spider + active scan) по обнаруженным web-приложениям
- Каждое срабатывание → SARIF находка

**Включение:**

```ini
DOMAINSCOPE_ZAP_ENABLED=true
# JSON-массив инстансов: каждый со своим url и api_key (load-balancing).
DOMAINSCOPE_ZAP_INSTANCES_JSON=[{"url":"http://zap-1:8090","api_key":"<key-1>"},{"url":"http://zap-2:8090","api_key":"<key-2>"}]
DOMAINSCOPE_TIME_LOOP_ZAP=14400              # каждые 4 часа
```

`DOMAINSCOPE_ZAP_INSTANCES_JSON` — единственный способ задать инстансы ZAP через ENV (отдельных `DOMAINSCOPE_ZAP_INSTANCES`/`DOMAINSCOPE_ZAP_API_KEY` **нет**). Каждый элемент массива — объект `{"url":"...","api_key":"..."}`; невалидный JSON роняет загрузку конфига. DomainScope round-robin'ит scan'ы между инстансами. Каждый instance держит свою БД сессий и темплейтов.

Для сканирования за аутентификацией задаётся `DOMAINSCOPE_ZAP_CREDENTIALS_JSON` — JSON-массив per-host учётных данных: `[{"host":"app.example.com","username":"u","password":"p","form_url":"https://app.example.com/login"}]`.

**Тонкая настройка:**

Через ZAP context-config (в репо `domainscope/docker/zap-config/`) можно задать:

- Authentication context (для сканирования за SSO)
- Exclude URLs (например, `/logout`)
- Active scan policy (Aggressive / Default / Light)

Конфигурация лежит в каталоге `docker/zap-config/` репозитория DomainScope.

**Override:**

```ini
DOMAINSCOPE_ZAP_SARIF_PRODUCT_ID=<product-zap>
DOMAINSCOPE_ZAP_SARIF_API_TOKEN=<...>
```

## Общие настройки SARIF-upload

Применяются ко всем сканерам, если не переопределены через `<SCANNER>_SARIF_*`:

```ini
DOMAINSCOPE_SARIF_ENABLED=true
DOMAINSCOPE_SARIF_AUTO_UPLOAD=true
# Корень Hub БЕЗ /api/v1 — клиент сам дописывает /api/v1/products/<id>/reports.
# С хвостом /api/v1 путь удвоится → 404 и находки НЕ доедут в Hub.
DOMAINSCOPE_SARIF_API_ENDPOINT=https://hub.example.com
DOMAINSCOPE_SARIF_PRODUCT_ID=<product-uuid>
DOMAINSCOPE_SARIF_API_TOKEN=<api-key>
DOMAINSCOPE_SARIF_SCANNER_NAME=domain-scope          # перепишется на конкретный сканер при upload
DOMAINSCOPE_SARIF_SCANNER_NODE=domain-scope-prod-01  # имя инстанса (для отслеживания)
DOMAINSCOPE_SARIF_IP_SCOPE=all                       # all / public / private
DOMAINSCOPE_SARIF_SAVE_LOCAL=false                   # если true — сохранять копию в /var/lib/domain-scope/sarif/
DOMAINSCOPE_SARIF_LOCAL_PATH=/var/lib/domain-scope/sarif
```

### IP scope filter

`DOMAINSCOPE_SARIF_IP_SCOPE` фильтрует, какие IP попадают в SARIF:

- `all` — все
- `public` — только публичные (исключает RFC1918 = 10/8, 172.16/12, 192.168/16)
- `private` — только приватные

Полезно когда DomainScope сканирует и внешний, и внутренний периметр, но Hub должен видеть только что-то одно (например, только публичный — для compliance-отчётности).

Per-scanner override доступен только для **OpenVAS** и **ZAP** (у Nuclei и TLSX его нет — они всегда используют глобальный `DOMAINSCOPE_SARIF_IP_SCOPE`):

```ini
DOMAINSCOPE_OPENVAS_IP_SCOPE=public          # OpenVAS — только публичные
DOMAINSCOPE_ZAP_IP_SCOPE=all                 # ZAP — везде
```

## Отключение сканера

Для временного отключения — задайте `<SCANNER>_ENABLED=false` и перезапустите:

```bash
docker compose down
sed -i 's/^DOMAINSCOPE_NUCLEI_ENABLED=.*/DOMAINSCOPE_NUCLEI_ENABLED=false/' .env
docker compose up -d
```

Текущие незавершённые scan'ы прерываются.

## Тестовый прогон одного сканера

Самый простой способ — запустить daemon только с одним enabled-сканером и одним seed-доменом:

```ini
DOMAINSCOPE_DOMAINS=example.com
DOMAINSCOPE_TARGET_IPS=
DOMAINSCOPE_NUCLEI_ENABLED=true
DOMAINSCOPE_OPENVAS_ENABLED=false
DOMAINSCOPE_TLSX_ENABLED=false
DOMAINSCOPE_ZAP_ENABLED=false
DOMAINSCOPE_TIME_LOOP_DISCOVERY=60          # форсируем быстро
DOMAINSCOPE_TIME_LOOP_PORTSCAN=120
DOMAINSCOPE_TIME_LOOP_NUCLEI=180
```

Запустить, проверить логи через 5 минут — должны быть видны все три цикла.

## Производительность и лимиты

### Cluster sizing

| Scope    | Без OpenVAS   | С OpenVAS      | С полным стеком (nuclei+openvas+tlsx+zap) |
| -------- | ------------- | -------------- | ----------------------------------------- |
| 100 IP   | 2 CPU / 4 GB  | 4 CPU / 12 GB  | 6 CPU / 16 GB                             |
| 1000 IP  | 4 CPU / 8 GB  | 8 CPU / 24 GB  | 12 CPU / 32 GB                            |
| 10000 IP | 8 CPU / 16 GB | 16 CPU / 48 GB | 24 CPU / 64 GB                            |

### Сетевая нагрузка

- Subfinder: ~10 KB на seed-домен
- Nmap: ~100 KB на IP (SYN-scan)
- Nuclei: ~5-20 MB на эндпоинт (зависит от templates)
- OpenVAS: ~10-50 MB на IP
- ZAP active scan: ~50-200 MB на эндпоинт

### Rate limits

DomainScope **не имеет глобального rate limit** — каждый сканер сам ограничивает себя. Если провайдер начинает шуметь:

- Уменьшите `SCANNER_MIN_RATE` (nmap)
- Уменьшите `NUCLEI_CONCURRENCY`
- Снизьте `TLSX_CONCURRENCY`

## Мониторинг циклов

В БД таблица `cycle_runs` хранит историю:

```sql
SELECT scanner, started_at, finished_at, status, items_processed, items_failed
FROM cycle_runs
ORDER BY started_at DESC
LIMIT 20;
```

Если у вас Prometheus, DomainScope экспортирует:

- `domainscope_cycle_runs_total{scanner,status}`
- `domainscope_cycle_duration_seconds{scanner}`
- `domainscope_scan_items_total{scanner,status}`
- `domainscope_sarif_uploads_total{result}`

## Связанные документы

- [Синхронизация с NetBox](domainscope-netbox.md) — NetBox sync
- [Происхождение записей периметра](domainscope-trails.md) — discovery trails
