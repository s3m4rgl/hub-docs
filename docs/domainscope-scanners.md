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

- Собирает исходные зоны: `DOMAINSCOPE_DOMAINS`, включения периметра Hub
  (`scope_entry`) и зоны NetBox DNS (`netbox_dns`, только при включённом
  экспорте DNS). Корни из `DOMAINSCOPE_IGNORED_DOMAINS` выбрасываются; при
  подключённом Hub остаются только зоны, которые допускает периметр Hub
- Для зон, у которых подошёл срок, запускает встроенный subfinder — пассивное
  перечисление по набору источников по умолчанию, без медленных источников и
  без ключей API; зоны идут строго по одной
- Резолвит зону и все её поддомены; сохраняются **только IPv4-адреса**
- Отбрасывает поддомены, которые резолвятся только в wildcard-адреса зоны
  (8 проб случайными именами)
- Новые поддомены сохраняются в БД с `source=subfinder`. Без Hub они
  сканируются сразу; при подключённом Hub поддомен без точной записи включения
  не сканируется и уходит в Hub предложением

!!! warning "Известное ограничение: только IPv4, CNAME не сохраняется"
    Резолвер проходит цепочку CNAME, но сохраняет только итоговые IPv4-адреса:
    адреса IPv6 отбрасываются, промежуточные имена CNAME нигде не
    записываются. Хосты, доступные только по IPv6, не сканируются.
    Исправление отслеживается в [DomainScope#5](https://gitlab.com/hub_infosec/DomainScope/-/work_items/5).

!!! warning "Известное ограничение: расписание зон не настраивается (0.33)"
    Каждая зона перечисляется не чаще раза в 24 часа, за цикл — не больше 25
    зон: сначала никогда не перечислявшиеся, затем самые давние. У пропущенных
    зон известные поддомены берутся из БД и резолвятся заново. Оба значения
    зашиты в код, переменных окружения для них нет; расписание хранится в
    памяти и после перезапуска начинается заново. Поэтому новый поддомен старой
    зоны появляется с задержкой до суток и больше. Исправление отслеживается в
    [DomainScope#9](https://gitlab.com/hub_infosec/DomainScope/-/work_items/9).

Что именно перечисляется, когда поддомен сканируется сразу, а когда уходит
предложением в Hub, и чего discovery не умеет — на странице
[Расширение периметра](domainscope-scope-discovery.md).

**Конфиг:**

```ini
DOMAINSCOPE_DOMAINS=example.com,subsidiary.com
DOMAINSCOPE_TIME_LOOP_DISCOVERY=21600        # каждые 6 часов
```

**Логи:**

```
INFO  discovery cycle started
INFO  subfinder started          {"domains": 2, "enumerating": 2, "reused_from_db": 0, "zone_interval": "24h0m0s", "budget": 25}
INFO  subfinder phase complete   {"domains": 2}
INFO  dns resolve phase done     {"scannable_ips": 59, "ignored_ips": 0, "ignored_domains": 0, "pending_proposals": 0}
INFO  discovery cycle done       {"scannable_ips": 59, "ignored_ips": 0}
```

Найденные поддомены по отдельности пишутся на уровне debug
(`subfinder done` с числом `subdomains`), wildcard-зона — на уровне warn
(`wildcard DNS detected for zone`).

## 2. Nmap port-scan + fingerprint

**Что делает:**

- Для каждого адреса **текущего** резолва активных доменов, адресов из
  периметра Hub (или NetBox без Hub) и `DOMAINSCOPE_TARGET_IPS` запускает
  `nmap -p <PORTS> -T4 -sS --min-rate 500` (при
  `DOMAINSCOPE_SCANNER_SCAN_TYPE=connect` вместо `-sS` —
  `-sT -Pn --unprivileged`, без host-discovery)
- Протокол на открытом порту определяет fingerprintx, а не `nmap -sV` — по
  одному запросу на каждый домен, ведущий на адрес (Host и SNI);
  нераспознанный порт записывается как `unknown`
- На TLS-портах читает альтернативные имена сертификата и сохраняет свои
  (под исходными зонами или резолвящиеся в уже сканированный адрес) с
  `source=tls_san`
- Результаты → таблицы `ip_data` и `findings` в БД + SARIF в Hub

**Конфиг:**

```ini
DOMAINSCOPE_TIME_LOOP_PORTSCAN=7200          # каждые 2 часа
DOMAINSCOPE_TARGET_PORTS=22,80,443,3306,5432,8080,8443    # CSV, диапазоны 1000-2000
DOMAINSCOPE_SCANNER_WORKERS=20               # параллельные горутины (default: 20)
DOMAINSCOPE_SCANNER_MIN_RATE=500             # nmap --min-rate (0 = выключено)
DOMAINSCOPE_FINGERPRINT_TIMEOUT=10           # секунды на fingerprint (в образе — 10, дефолт кода — 5)
```

!!! note "Цели берутся из текущего резолва, а не из истории (0.32)"

    Раньше цели строились по журналу «домен когда-либо резолвился в этот
    адрес», который не чистится никогда: адрес, однажды попавший в базу,
    сканировался вечно — даже после снятия домена со скоупа, его блокировки
    или потери резолва. Замер на боевой инсталляции: 196 из 353 опрошенных
    публичных адресов не входили ни в один активный включающий диапазон.

    Теперь источником целей служит текущий резолв доменов в состоянии
    «активен», а отбраковка видна в журнале сводными счётчиками по каждой
    причине — молчаливое сужение списка целей неотличимо от поломки сканера.
    История резолвов при этом сохраняется и продолжает использоваться в
    [происхождении записей](domainscope-trails.md).

    Там же изменилась подпись находки: её подписывает **активный домен**, а
    не вся история адреса.

**Производительность:**

- `SCANNER_WORKERS=20` — норма для 1k IP при базовом наборе портов
- `MIN_RATE=500` — агрессивный скан; уменьшите до `200` если провайдер шумит на abuse-traffic
- `MIN_RATE=0` — режим по умолчанию nmap (адаптивный)
- Мягче к чувствительным сетям: `SCANNER_TIMING_TEMPLATE=3`, `SCANNER_MIN_RATE=50` + `SCANNER_MAX_RATE=100`, `SCANNER_SCAN_DELAY=10ms` (`MAX_RATE` меньше `MIN_RATE` — ошибка старта, а `MIN_RATE` по умолчанию 500)
- Хосты, не отвечающие на ping, но с открытыми портами: `SCANNER_SKIP_HOST_DISCOVERY=true`
- Медленный канал: `SCANNER_MAX_RTT_TIMEOUT=2s`, `SCANNER_HOST_TIMEOUT=15m`

Все параметры nmap и ограничения на произвольные аргументы — в
[справочнике переменных](env-domainscope.md#тонкая-настройка-nmap-034).

Какие порты сканируются по умолчанию при каждом способе установки, как задать
свои (`TARGET_PORTS` или `SCANNER_TOP_PORTS`) и почему от этого зависят Nuclei,
ZAP и TLSX — в разделе [Порты сканирования](env-domainscope.md#порты-сканирования).

**Безопасность:**

Nmap по умолчанию делает SYN-scan (требует raw sockets → CAP_NET_RAW). В Docker-образе процесс работает от root, а `NET_RAW` входит в набор capability Docker по умолчанию. Вне контейнера запускайте DomainScope от root либо переключитесь на `DOMAINSCOPE_SCANNER_SCAN_TYPE=connect`: nmap запускается отдельным процессом с `-sS` без `--privileged` (через `DOMAINSCOPE_SCANNER_NMAP_EXTRA_ARGS` её тоже не передать), поэтому `setcap` на бинарь DomainScope не помогает.

## 3. Nuclei HTTP scanner

**Что делает:**

- Берёт порты, которые nmap нашёл открытыми и fingerprint определил как HTTP/HTTPS (номер порта значения не имеет; порт вне `TARGET_PORTS` сюда не попадёт)
- Прогоняет встроенный nuclei с подключёнными templates
- Запускает только шаблоны уровней из YAML `nuclei.severity` (по умолчанию `medium`, `high`, `critical`; через ENV не задаётся); срабатывание → SARIF находка

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

Контейнер `nuclei-templates-init` загружает templates в общий volume при первом старте и обновляет при последующих запусках. Для air-gapped окружений смонтируйте локальный набор как volume и укажите пути в `DOMAINSCOPE_NUCLEI_TEMPLATES_PATHS`: по умолчанию заданы семь поддиректорий `/app/nuclei-templates/http/*`, и пока они заданы, `DOMAINSCOPE_NUCLEI_TEMPLATES_PATH` не действует.

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

**Scan configurations:**

При пустом `DOMAINSCOPE_OPENVAS_SCAN_CONFIG_ID` DomainScope ищет конфигурацию
**Full and fast** по имени, а если не находит — берёт её стандартный UUID
`daba56c8-73ec-11df-a475-002264764cea`. Для другой конфигурации скопируйте её
UUID из Greenbone Web UI (Configuration → Scan Configs) в
`DOMAINSCOPE_OPENVAS_SCAN_CONFIG_ID`.

**Port list:** по умолчанию `All TCP ports`; другой лист задаётся
`DOMAINSCOPE_OPENVAS_PORT_LIST` (UUID или точное имя), см.
[Порты сканирования](env-domainscope.md#как-порты-влияют-на-другие-сканеры).

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

- Для каждого открытого порта с TLS-протоколом по fingerprint (`https`, `imaps`, `pop3s`, `smtps`, `ldaps`) устанавливает TLS-соединение по IP и читает сертификат
- Формирует находки:
  - `HIGH` — сертификат истёк (`expired_cert`)
  - `MEDIUM` — сертификат истекает в ближайшие `DOMAINSCOPE_TLSX_CERT_EXPIRY_DAYS` дней, по умолчанию 30 (`expiring_cert`)
  - `MEDIUM` — самоподписанный сертификат (`self_signed_cert`)
  - `MEDIUM` — TLS 1.0 или TLS 1.1 (`tls_old_version`)
- Несовпадение имени в сертификате не проверяется: скан идёт по IP, и такая находка была бы ложной

**Включение:**

```ini
DOMAINSCOPE_TLSX_ENABLED=true
DOMAINSCOPE_TLSX_CONCURRENCY=50              # параллельные хосты (default: 50)
DOMAINSCOPE_TLSX_CERT_EXPIRY_DAYS=30         # порог expiring_cert, дней (default: 30)
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
- По обнаруженным web-приложениям запускает Spider, затем AJAX Spider (`DOMAINSCOPE_ZAP_AJAX_SPIDER_TIMEOUT`, по умолчанию 300 с) и Active Scan
- Один хост повторно сканируется не раньше чем через `DOMAINSCOPE_ZAP_RESCAN_PERIOD` (по умолчанию 86400 с)
- В SARIF уходят находки с риском от YAML `zap.min_risk` и выше (по умолчанию `medium`); остальные остаются только в базе DomainScope

**Включение:**

```ini
DOMAINSCOPE_ZAP_ENABLED=true
# JSON-массив инстансов: каждый со своим url и api_key (load-balancing).
DOMAINSCOPE_ZAP_INSTANCES_JSON=[{"url":"http://zap-1:8090","api_key":"<key-1>"},{"url":"http://zap-2:8090","api_key":"<key-2>"}]
DOMAINSCOPE_TIME_LOOP_ZAP=14400              # каждые 4 часа
```

`DOMAINSCOPE_ZAP_INSTANCES_JSON` — единственный способ задать инстансы ZAP через ENV (отдельных `DOMAINSCOPE_ZAP_INSTANCES`/`DOMAINSCOPE_ZAP_API_KEY` **нет**). Каждый элемент массива — объект `{"url":"...","api_key":"..."}`; невалидный JSON роняет загрузку конфига. У каждого инстанса своя очередь заданий; хост попадает в очередь по хешу корневого домена (все поддомены одного домена — в один инстанс), а если этот инстанс занят, а другой свободен, — в свободный.

Для сканирования за аутентификацией задаётся `DOMAINSCOPE_ZAP_CREDENTIALS_JSON` — JSON-массив per-host учётных данных: `[{"host":"app.example.com","username":"u","password":"p","form_url":"https://app.example.com/login"}]`.

**Тонкая настройка:**

- политика Active Scan — `DOMAINSCOPE_ZAP_ACTIVE_SCAN_POLICY`: имя политики,
  уже заведённой в ZAP; пусто — `Default Policy`;
- сканирование за формой входа — `DOMAINSCOPE_ZAP_CREDENTIALS_JSON` (см. выше);
- таймаут AJAX Spider и период повторного скана — переменные из блока выше.

Каталог `docker/zap-config/` репозитория DomainScope — домашний каталог ZAP
(`config.xml`) для dev-стенда `docker/docker-compose.dev.yml`; DomainScope его не
читает.

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
# Корень Hub — клиент сам дописывает /api/v1/products/<id>/reports
# (хвост /api/v1, если он есть, отрезается).
DOMAINSCOPE_SARIF_API_ENDPOINT=https://hub.example.com
DOMAINSCOPE_SARIF_PRODUCT_ID=<product-uuid>
DOMAINSCOPE_SARIF_API_TOKEN=<api-key>
DOMAINSCOPE_SARIF_SCANNER_NAME=DomainScope           # engine отчётов порт-скана (default); Nuclei — <имя>/Nuclei,
                                                     # у OpenVAS, TLSX и ZAP имена фиксированные
DOMAINSCOPE_SARIF_SCANNER_NODE=domain-scope-prod-01  # имя инстанса (для отслеживания)
DOMAINSCOPE_SARIF_IP_SCOPE=all                       # all / public / private
DOMAINSCOPE_SARIF_SAVE_LOCAL=false                   # default true — копия отчётов на диске
DOMAINSCOPE_SARIF_LOCAL_PATH=/var/log/domain-scope/sarif   # значение в Docker-образе
```

### IP scope filter

`DOMAINSCOPE_SARIF_IP_SCOPE` определяет, какие адреса сканируются и попадают в SARIF:

- `all` — все
- `public` — только публичные: без RFC 1918 (10/8, 172.16/12, 192.168/16), loopback, link-local и IPv6 ULA (fc00::/7)
- `private` — только приватные (те же диапазоны)

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

### Ресурсы

DomainScope — один под с лимитом **4 ядра и 4 Gi** (запрос — 0.5 ядра и
512 Mi) плюс своя база на 0.5 ядра и 512 Mi. OpenVAS и OWASP ZAP — отдельные
поды со своими лимитами; полные таблицы — в [Расчёте ресурсов](sizing.md).

Размер периметра влияет прежде всего на **длительность циклов**, а не на
память: nmap, nuclei и tlsx обходят цели порциями с заданной
параллельностью. Замеров потребления по числу IP не проводилось. Если цикл
не укладывается в интервал, сначала поднимите параллельность
(`DOMAINSCOPE_NUCLEI_CONCURRENCY`, `DOMAINSCOPE_TLSX_CONCURRENCY`, тайминги nmap — см.
[Тонкая настройка nmap](env-domainscope.md#тонкая-настройка-nmap-034)), затем —
лимит CPU пода, если он упирается в 4 ядра. Лимит памяти поднимайте по
факту OOM, а не заранее.

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

Отдельной таблицы истории циклов и метрик Prometheus у DomainScope нет. Ход
циклов виден в журнале (JSON в stdout) и в readiness-эндпоинте:

- discovery и port scan пишут начало и конец цикла на уровне info
  (`discovery cycle started` / `discovery cycle done`, `port scan cycle
  started` / `port scan cycle done`), port scan — ещё сводку доставки
  `sarif delivery` с `hosts_reported` и `total_findings`;
- остальные сканеры пишут свои шаги: `openvas fresh start`,
  `openvas: scan cycle complete, state cleared`, `tlsx findings synced`,
  `zap scan complete`, загрузку отчётов — `… sarif report uploaded`;
- при `DOMAINSCOPE_HEALTH_ENABLED=true` `GET /ready` отвечает `503`, если
  discovery, port scan, а при включённых сканерах — Nuclei и ZAP не
  завершались дольше двух своих интервалов (или ещё ни разу), либо база
  недоступна. В теле ответа — какой цикл отстал.

## Связанные документы

- [Расширение периметра: обнаружение доменов и адресов](domainscope-scope-discovery.md) — как находятся и предлагаются новые домены
- [Синхронизация с NetBox](domainscope-netbox.md) — NetBox sync
- [Происхождение записей периметра](domainscope-trails.md) — discovery trails
