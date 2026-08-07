# Переменные окружения: DomainScope

Большинство переменных DomainScope имеют префикс `DOMAINSCOPE_` (конфиг агента). Несколько переменных префикса НЕ имеют — это rescan/probe HTTP-сервер, логгер и DNS-резолвер (см. раздел «Без префикса DOMAINSCOPE_» в конце). Приоритет конфигурации: **ENV > YAML (`config-example.yml` / `/etc/domain-scope/settings.yml`) > defaults в `LoadConfig()`**.

- bool принимает `true/false/1/0/yes/no/on/off` (регистронезависимо);
- числа — unsigned int; списки — через запятую;
- источник истины по дефолтам — `DefaultConfig()` в `internal/pkg/configuration/config.go`.

В Helm задаются через `domainscope.env.*`. Секреты (`DSN`, `*_API_TOKEN`, `*_PASSWORD`, `*_HMAC_SECRET`, `ZAP_*_JSON`) идут через `secretKeyRef`/Vault.

## Окружение / общее

| Переменная | Назначение | Значения | По умолчанию |
|---|---|---|---|
| `DOMAINSCOPE_ENV` | Индикатор окружения. В `production` secret-несущие endpoints обязаны быть `https://` (если нет соответствующего `*_INSECURE`) | `production` \| `prod` \| `dev` \| строка | пусто (= не-prod); fallback на `APP_ENV` |

## Scope / домены

| Переменная | Назначение | Значения | По умолчанию |
|---|---|---|---|
| `DOMAINSCOPE_DOMAINS` | Домены для мониторинга/сканирования | CSV доменов | пусто (берётся из YAML/Hub Scope API) |
| `DOMAINSCOPE_IGNORED_DOMAINS` | Корневые зоны, всегда игнорируемые (напр. `reg.ru`) | CSV доменов | пусто |
| `DOMAINSCOPE_TARGET_IPS` | IP для прямого сканирования | CSV IP | пусто |
| `DOMAINSCOPE_TARGET_PORTS` | Порты сканирования | `80,443,1000-2000` (одиночные + диапазоны) | пусто |
| `DOMAINSCOPE_FINGERPRINT_TIMEOUT` | Таймаут fingerprinting, сек | uint | `5` |

## Scanner (nmap)

| Переменная | Назначение | Значения | По умолчанию |
|---|---|---|---|
| `DOMAINSCOPE_SCANNER_WORKERS` | Число параллельных worker скана | uint | `20` |
| `DOMAINSCOPE_SCANNER_MIN_RATE` | nmap `--min-rate`, пакетов/сек | uint, `0` = выкл | `500` |
| `DOMAINSCOPE_SCANNER_MAX_UNKNOWN_PORTS_PER_IP` | Порог аномалии: ≥N портов `unknown`+пустой fingerprint на одном IP → отбрасываются как scan-артефакт | uint, `0` = фильтр выкл | `20` |
| `DOMAINSCOPE_SCANNER_SCAN_TYPE` | Тип nmap-скана портов (см. ниже) | `syn` \| `connect` | `syn` |

### `DOMAINSCOPE_SCANNER_SCAN_TYPE` — syn против connect

- **`syn`** (по умолчанию): TCP SYN-скан (`nmap -sS`). Быстрый, но **требует raw-сокетов** (root или `CAP_NET_RAW`). Для обычных привилегированных установок.
- **`connect`**: TCP connect-скан (`nmap -sT -Pn --unprivileged`). Не требует raw-сокетов. Нужен там, где raw-сокеты недоступны:
  - rootless-контейнеры;
  - qemu-эмуляция (amd64-образ на arm64-ноде) — при `syn` nmap падает с `pcap_open_live() failed`;
  - ограниченные seccomp-профили.

  `connect` медленнее `syn`, но не требует повышенных привилегий. Доступно начиная с версии 0.26.

## Time-loops (интервалы циклов, сек)

| Переменная | Назначение | Значения | По умолчанию |
|---|---|---|---|
| `DOMAINSCOPE_TIME_LOOP` | Общий интервал между сборами | uint | `3600` |
| `DOMAINSCOPE_TIME_LOOP_DISCOVERY` | Discovery-цикл (subfinder + DNS + NetBox IPAM) | uint | `21600` (6 ч) |
| `DOMAINSCOPE_TIME_LOOP_PORTSCAN` | Port scan цикл (nmap + fingerprint + SARIF) | uint | `7200` (2 ч) |
| `DOMAINSCOPE_TIME_LOOP_NUCLEI` | Nuclei HTTP-скан цикл | uint | `3600` (1 ч) |
| `DOMAINSCOPE_TIME_LOOP_OPENVAS` | OpenVAS цикл | uint | `86400` (24 ч) |
| `DOMAINSCOPE_TIME_LOOP_TLSX` | TLSX цикл | uint | `21600` (6 ч) |
| `DOMAINSCOPE_TIME_LOOP_ZAP` | ZAP цикл | uint | `14400` (4 ч) |

## База данных

| Переменная | Назначение | Значения | По умолчанию |
|---|---|---|---|
| `DOMAINSCOPE_DSN` | Строка подключения PostgreSQL (секрет) | DSN (`host=… user=… sslmode=disable`) | пусто (де-факто обязательна; в Helm — из Secret) |

## SARIF (выгрузка находок в Hub)

| Переменная | Назначение | Значения | По умолчанию |
|---|---|---|---|
| `DOMAINSCOPE_SARIF_ENABLED` | Включить генерацию SARIF | bool | `false` |
| `DOMAINSCOPE_SARIF_AUTO_UPLOAD` | Автозагрузка отчётов в Hub API | bool | `false` |
| `DOMAINSCOPE_SARIF_PRODUCT_ID` | ID продукта в Hub (обязателен при auto_upload) | строка | пусто |
| `DOMAINSCOPE_SARIF_API_ENDPOINT` | URL Hub API (корень **без** `/api/v1` — клиент дописывает сам) | URL | пусто |
| `DOMAINSCOPE_SARIF_API_TOKEN` | Токен загрузки SARIF (секрет) | строка | пусто |
| `DOMAINSCOPE_SARIF_SCANNER_NAME` | Название сканера | строка | `DomainScope` |
| `DOMAINSCOPE_SARIF_SCANNER_NODE` | Имя узла сканера | строка | `os.Hostname()` |
| `DOMAINSCOPE_SARIF_SAVE_LOCAL` | Сохранять отчёты локально | bool | `true` |
| `DOMAINSCOPE_SARIF_LOCAL_PATH` | Путь локального сохранения | путь | `/tmp/domain-scope/sarif` |
| `DOMAINSCOPE_SARIF_IP_SCOPE` | Фильтр IP в SARIF | `all` \| `public` \| `private` | `all` |
| `DOMAINSCOPE_SARIF_INSECURE` | Разрешить `http://` api_endpoint в prod | bool | `false` |

> При `auto_upload=true` обязательны `product_id`, `api_endpoint`, `api_token`. В prod `api_endpoint` обязан `https://`, если нет `SARIF_INSECURE=true`.

## Hub Scope API (получение scope из Hub)

| Переменная | Назначение | Значения | По умолчанию |
|---|---|---|---|
| `DOMAINSCOPE_HUB_ENABLED` | Тянуть scope (домены) из Hub | bool | `false` |
| `DOMAINSCOPE_HUB_API_ENDPOINT` | URL Hub API | URL | пусто |
| `DOMAINSCOPE_HUB_API_TOKEN` | Токен сервис-аккаунта (X-API-Key, секрет) | строка | пусто |
| `DOMAINSCOPE_HUB_PROJECT_IDS` | UUID проектов Hub | CSV UUID | пусто |
| `DOMAINSCOPE_HUB_INSECURE` | Разрешить `http://` Hub endpoint в prod | bool | `false` |

> При `enabled=true` обязательны `api_endpoint`, `api_token`, `project_ids`; в prod — `https://` (если нет `HUB_INSECURE=true`).

## NetBox

| Переменная | Назначение | Значения | По умолчанию |
|---|---|---|---|
| `DOMAINSCOPE_NETBOX_ENABLED` | Импорт IP из NetBox IPAM | bool | `false` |
| `DOMAINSCOPE_NETBOX_API_ENDPOINT` | URL NetBox | URL | пусто |
| `DOMAINSCOPE_NETBOX_API_TOKEN` | API-токен NetBox (секрет) | строка | пусто |
| `DOMAINSCOPE_NETBOX_TAG` | Тег IP для фильтрации импорта | строка | `public-ip` |
| `DOMAINSCOPE_NETBOX_CRAWLER_TAG` | Тег для IP, добавленных DomainScope | строка | `domainscope-crawler` |
| `DOMAINSCOPE_NETBOX_INSECURE` | Пропустить TLS-проверку | bool | `false` |
| `DOMAINSCOPE_NETBOX_IGNORE_SCAN_TAG` | Тег исключения из сканирования | строка | `ignore-scan` |
| `DOMAINSCOPE_NETBOX_PENDING_REVIEW_TAG` | Тег зон, ожидающих проверки | строка | `pending-review` |
| `DOMAINSCOPE_NETBOX_TENANT` | Slug тенанта NetBox | строка | пусто (без фильтра) |
| `DOMAINSCOPE_NETBOX_DNS_EXPORT_ENABLED` | Экспорт доменов в NetBox DNS plugin | bool | `false` |
| `DOMAINSCOPE_NETBOX_DNS_EXPORT_VIEW` | Имя DNS view | строка | `default` |
| `DOMAINSCOPE_NETBOX_DNS_EXPORT_SOA_MNAME` | FQDN nameserver (обязателен при dns_export) | FQDN | пусто |
| `DOMAINSCOPE_NETBOX_DNS_EXPORT_SOA_RNAME` | Email SOA | строка | `hostmaster.<zone>` |

> `dns_export.enabled=true` требует `NETBOX_ENABLED=true` и `SOA_MNAME`. В prod `api_endpoint` — `https://` (если нет `NETBOX_INSECURE=true`).

## Nuclei

| Переменная | Назначение | Значения | По умолчанию |
|---|---|---|---|
| `DOMAINSCOPE_NUCLEI_ENABLED` | Включить nuclei HTTP-скан | bool | `false` |
| `DOMAINSCOPE_NUCLEI_TEMPLATES_PATH` | Базовая директория шаблонов (legacy) | путь | `/app/nuclei-templates` |
| `DOMAINSCOPE_NUCLEI_TEMPLATES_PATHS` | Список директорий/файлов шаблонов (приоритетнее PATH) | CSV путей | 7 поддиректорий `http/*` |
| `DOMAINSCOPE_NUCLEI_TAGS` | Теги шаблонов | CSV | `exposure,panel,debug,misconfig,vuln,cve,default-login,rce` |
| `DOMAINSCOPE_NUCLEI_CONCURRENCY` | Параллельные запросы | uint | `50` |
| `DOMAINSCOPE_NUCLEI_REQUEST_TIMEOUT` | Сек на один запрос | uint | `10` |
| `DOMAINSCOPE_NUCLEI_SCAN_TIMEOUT` | Сек на весь nuclei-шаг (макс 86400) | uint | `7200` |
| `DOMAINSCOPE_NUCLEI_GROUP_CONCURRENCY` | Параллельно сканируемых групп хостов | uint ≥1 | `1` |
| `DOMAINSCOPE_NUCLEI_DEBUG_FIRST_N` | Сканировать только первые N групп | uint, `0` = все | `0` |
| `DOMAINSCOPE_NUCLEI_TARGET_FILE` | Файл с таргетами (1 URL/строку) | путь | пусто (= из БД) |
| `DOMAINSCOPE_NUCLEI_SARIF_PRODUCT_ID` | Override SARIF product_id для nuclei | строка | пусто (= глобальный) |
| `DOMAINSCOPE_NUCLEI_SARIF_API_TOKEN` | Override SARIF токена (секрет) | строка | пусто (= глобальный) |
| `DOMAINSCOPE_NUCLEI_FP_ROOT_MATCH_THRESHOLD` | Порог массового FP root-match на хост | uint, `0` = выкл | `4` |
| `DOMAINSCOPE_TRUSTED_IP_TAGS` | Теги NetBox IPAM «наших» IP (фильтр для nmap+nuclei) | CSV | пусто (без фильтра) |
| `DOMAINSCOPE_TRUSTED_IP_STATUSES` | Допустимые статусы IP в NetBox | CSV | `active,deprecated` |

## OpenVAS / Greenbone (клиент GMP)

| Переменная | Назначение | Значения | По умолчанию |
|---|---|---|---|
| `DOMAINSCOPE_OPENVAS_ENABLED` | Включить OpenVAS (GMP via gsad) | bool | `false` |
| `DOMAINSCOPE_OPENVAS_HOST` | gsad host | host | `localhost` |
| `DOMAINSCOPE_OPENVAS_PORT` | gsad порт | int >0 | `9390` |
| `DOMAINSCOPE_OPENVAS_INSECURE` | Пропустить TLS-проверку gsad (self-signed) | bool | `false` |
| `DOMAINSCOPE_OPENVAS_USERNAME` | GMP username | строка | пусто |
| `DOMAINSCOPE_OPENVAS_PASSWORD` | GMP password (секрет) | строка | пусто |
| `DOMAINSCOPE_OPENVAS_SCAN_CONFIG_ID` | ID конфигурации скана | строка | пусто (= `Full and fast`) |
| `DOMAINSCOPE_OPENVAS_SARIF_PRODUCT_ID` | Override SARIF product_id | строка | пусто (= глобальный) |
| `DOMAINSCOPE_OPENVAS_SARIF_API_TOKEN` | Override SARIF токена (секрет) | строка | пусто (= глобальный) |
| `DOMAINSCOPE_OPENVAS_IP_SCOPE` | Фильтр IP для OpenVAS | `all` \| `public` \| `private` | пусто (= глобальный) |
| `DOMAINSCOPE_OPENVAS_SUPPRESSED_NVT_NAMES` | NVT-названия (подстроки), исключаемые из SARIF | CSV | пусто |

> При `enabled=true` обязательны `HOST`, `PORT`, `USERNAME`, `PASSWORD`.

## TLSX

| Переменная | Назначение | Значения | По умолчанию |
|---|---|---|---|
| `DOMAINSCOPE_TLSX_ENABLED` | Включить TLS/SSL аудит | bool | `false` |
| `DOMAINSCOPE_TLSX_CONCURRENCY` | Параллельность (>0) | uint | `50` |
| `DOMAINSCOPE_TLSX_CERT_EXPIRY_DAYS` | Порог предупреждения об истечении серта, дней | uint | `30` |
| `DOMAINSCOPE_TLSX_SARIF_PRODUCT_ID` | Override SARIF product_id | строка | пусто (= глобальный) |
| `DOMAINSCOPE_TLSX_SARIF_API_TOKEN` | Override SARIF токена (секрет) | строка | пусто (= глобальный) |

## OWASP ZAP (клиент)

| Переменная | Назначение | Значения | По умолчанию |
|---|---|---|---|
| `DOMAINSCOPE_ZAP_ENABLED` | Включить ZAP веб-скан | bool | `false` |
| `DOMAINSCOPE_ZAP_RESCAN_PERIOD` | Период повторного скана хоста, сек | uint | `86400` (24 ч) |
| `DOMAINSCOPE_ZAP_AJAX_SPIDER_TIMEOUT` | Таймаут AJAX Spider, сек | uint | `300` |
| `DOMAINSCOPE_ZAP_ACTIVE_SCAN_POLICY` | Имя политики Active Scan | строка | пусто (= `Default Policy`) |
| `DOMAINSCOPE_ZAP_IP_SCOPE` | Фильтр IP для ZAP | `all` \| `public` \| `private` | пусто (= глобальный) |
| `DOMAINSCOPE_ZAP_SARIF_PRODUCT_ID` | Override SARIF product_id | строка | пусто (= глобальный) |
| `DOMAINSCOPE_ZAP_SARIF_API_TOKEN` | Override SARIF токена (секрет) | строка | пусто (= глобальный) |
| `DOMAINSCOPE_ZAP_INSTANCES_JSON` | JSON-массив инстансов ZAP (содержит API-ключи, секрет). Перезаписывает YAML | JSON `[{"url":…,"api_key":…}]` | пусто (обязателен при ZAP enabled) |
| `DOMAINSCOPE_ZAP_CREDENTIALS_JSON` | JSON-массив per-host creds (секрет) | JSON `[{"host","username","password","form_url"}]` | пусто |

## Metabase (CMDB-обогащение)

| Переменная | Назначение | Значения | По умолчанию |
|---|---|---|---|
| `DOMAINSCOPE_METABASE_ENABLED` | CMDB-обогащение IP из Metabase | bool | `false` |
| `DOMAINSCOPE_METABASE_BASE_URL` | URL Metabase | URL | пусто |
| `DOMAINSCOPE_METABASE_API_TOKEN` | X-Metabase-API-Key (секрет) | строка | пусто |
| `DOMAINSCOPE_METABASE_INSECURE` | Разрешить `http://` base_url в prod | bool | `false` |
| `DOMAINSCOPE_METABASE_DATABASE_ID` | ID базы данных в Metabase | int | `2` |
| `DOMAINSCOPE_METABASE_SERVERS_TABLE_ID` | ID таблицы «Servers And Clusters» | int | `19` |

## Адрес проверки состояния

| Переменная | Назначение | Значения | По умолчанию |
|---|---|---|---|
| `DOMAINSCOPE_HEALTH_ENABLED` | HTTP `/health` + `/ready` для k8s probes | bool | `false` |
| `DOMAINSCOPE_HEALTH_ADDR` | Адрес health-сервера | `host:port` | `:8080` |

## Scope hardening + Rescan/Verify API (security)

| Переменная | Назначение | Значения | По умолчанию |
|---|---|---|---|
| `DOMAINSCOPE_SCOPE_FAIL_OPEN` | При недоступности Hub scope: `false` = fail-CLOSED (пропустить цикл, безопасно), `true` = fail-OPEN (скан по config-доменам, риск out-of-scope) | bool | `false` |
| `DOMAINSCOPE_PROBE_HMAC_SECRET` | HMAC-секрет для `POST /api/v1/probe`. Не задан → `/probe` 401 (fail-closed). Секрет | строка | пусто |
| `DOMAINSCOPE_VERIFY_API_KEY` | Включает inbound `POST /api/v1/verify-finding` (dual_verify). Секрет | строка | пусто |
| `DOMAINSCOPE_VERIFY_HMAC_SECRET` | HMAC inbound verify-находка. Обязателен если задан `VERIFY_API_KEY` (иначе fatal). Секрет | строка | пусто |
| `DOMAINSCOPE_HUB_CALLBACK_API_KEY` | API-ключ исходящего callback в Hub. Обязателен при verify. Секрет | строка | пусто |
| `DOMAINSCOPE_HUB_CALLBACK_HMAC_SECRET` | HMAC исходящего callback. Обязателен при verify. Секрет | строка | пусто |
| `DOMAINSCOPE_HUB_CALLBACK_HOSTS` | Allowlist хостов callback по HTTPS (anti-SSRF) | CSV хостов | пусто |
| `DOMAINSCOPE_HUB_CALLBACK_HTTP_HOSTS` | Allowlist хостов callback по HTTP (anti-SSRF) | CSV хостов | пусто |

## Без префикса DOMAINSCOPE_ (rescan/probe сервер, логгер, DNS)

Эти переменные читаются напрямую (не через `config_env.go`), поэтому НЕ имеют
префикса `DOMAINSCOPE_`.

| Переменная | Назначение | Значения | По умолчанию |
|---|---|---|---|
| `RESCAN_API_KEY` | **Мастер-переключатель** inbound rescan/probe/verify HTTP-сервера. Не задан → сервер не стартует (весь блок rescan/verify неактивен). Секрет | строка | пусто |
| `RESCAN_LISTEN_ADDR` | Адрес прослушивания rescan-сервера | `host:port` | пусто (дефолт внутри сервера) |
| `RESCAN_EXPECTED_PROJECT_ID` | Если задан — принимаются только rescan-запросы с совпадающим `project_id`; иначе любой | UUID | пусто (любой) |
| `PROBE_ALLOW_PRIVATE` | Разрешить probe/verify приватные (RFC1918) адреса (anti-SSRF override) | `true` \| `false` | `false` |
| `SCANNER_DNS_SERVER` | Кастомный DNS-сервер для резолва целей | `host[:port]` | пусто (= системный resolver) |
| `LOG_LEVEL` | Уровень логирования | `debug` \| `info` \| `warn` \| `error` | внутренний дефолт логгера |
| `APP_ENV` | Fallback для `DOMAINSCOPE_ENV`, если тот не задан | `production` \| `dev` \| … | пусто |

## Условно обязательные переменные

Жёстко обязательных «всегда» нет (`DSN` имеет YAML-дефолт). Условно (валидация/ fatal на старте):

- `DSN` — де-факто обязателен для работы.
- `HUB_ENABLED=true` → `HUB_API_ENDPOINT`, `HUB_API_TOKEN`, `HUB_PROJECT_IDS`.
- `NETBOX_ENABLED=true` → `NETBOX_API_ENDPOINT`, `NETBOX_API_TOKEN`; при `NETBOX_DNS_EXPORT_ENABLED=true` ещё `NETBOX_DNS_EXPORT_SOA_MNAME`.
- `SARIF_ENABLED=true`+`SARIF_AUTO_UPLOAD=true` → `SARIF_PRODUCT_ID`, `SARIF_API_ENDPOINT`, `SARIF_API_TOKEN`.
- `OPENVAS_ENABLED=true` → `OPENVAS_HOST`, `OPENVAS_PORT`, `OPENVAS_USERNAME`, `OPENVAS_PASSWORD`.
- `DOMAINSCOPE_ZAP_ENABLED=true` → `DOMAINSCOPE_ZAP_INSTANCES_JSON` (≥1 инстанс с `url`+`api_key`).
- `METABASE_ENABLED=true` → `METABASE_BASE_URL`.
- `VERIFY_API_KEY` задан → `VERIFY_HMAC_SECRET`, `HUB_CALLBACK_API_KEY`, `HUB_CALLBACK_HMAC_SECRET`.
- В **production** все secret-несущие endpoints обязаны быть `https://`, если не выставлен соответствующий `*_INSECURE=true`.
