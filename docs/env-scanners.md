# Переменные окружения: сканеры

Справочник по трём сканер-компонентам. У iac-scanner — обычные env-переменные Go-сервиса; у OpenVAS и OWASP ZAP конфигурация задаётся преимущественно через **значения Helm-чарта** (`charts/openvas/values.yaml`, `charts/owasp-zap/values.yaml`), которые шаблоны раскладывают в env подов и секреты.

## IAC-scanner (Go)

Сканер инфраструктуры-как-кода (KICS). По умолчанию `enabled: false` в чарте — включается после создания Service Account в Hub UI. В чарте задаётся подмножество (`iacScanner.env.*`); `RESCAN_*` и `KICS_QUERIES_PATH` в дефолтном развёртывании не выставляются.

| Переменная | Назначение | Значения | По умолчанию | Обязательна |
|---|---|---|---|---|
| `VMS_API_URL` | Базовый URL Hub API (отправка находок, запрос `scan-enabled`) | URL (обычно с суффиксом `/api/v1`) | — | **Да (fatal)** |
| `VMS_API_KEY` | API-ключ Service Account в Hub (секрет) | строка | — | **Да (fatal)** |
| `DATABASE_DSN` | DSN PostgreSQL собственной БД сканера (секрет) | `postgres://…` / `host=… user=…` | — | **Да (fatal)** |
| `SCAN_WORKERS` | Кол-во параллельных worker сканирования | целое ≥1 | `5` [code] / `3` [chart] | Нет |
| `SCAN_SCHEDULE_INTERVAL` | Период опроса/планирования сканов | Go-duration (`30s`, `5m`) | `5m` [code] / `300s` [chart] | Нет |
| `LOG_LEVEL` | Уровень логирования | `debug` \| `info` \| `warn` \| `error` | `info` | Нет |
| `RESCAN_API_KEY` | Pre-shared secret для hub→scanner webhook `/api/v1/rescan`. **Пуст → rescan-сервер не запускается** (no-auth недопустим) | строка (секрет) | пусто | Нет (нужна для rescan) |
| `RESCAN_LISTEN_ADDR` | Bind-адрес HTTP-сервера rescan | `host:port` | `:8086` | Нет |
| `KICS_QUERIES_PATH` | Путь к KICS queries-ассетам | путь | автодетект → дефолт KICS | Нет |

> Отсутствие `VMS_API_URL` / `VMS_API_KEY` / `DATABASE_DSN` → сервис не стартует. Hub задаёт тот же ключ rescan в своей переменной `IAC_SCANNER_RESCAN_API_KEY`.

## OpenVAS (Greenbone Community)

Один Pod с несколькими контейнерами (pg-gvm, gvmd, gsad, ospd-openvas, openvas-scanner, redis), общение через unix-сокеты. Конфигурируется значениями чарта; внутрь подов env подставляются шаблоном.

### Секреты и основные значения чарта

| Значение (`values.yaml`) | Назначение | Значения | По умолчанию |
|---|---|---|---|
| `secrets.create` | Создавать ли Secret чартом | `true` \| `false` | `true` |
| `secrets.existingSecretName` | Имя готового Secret | строка | `""` |
| `secrets.adminPassword` | Пароль GMP-пользователя `admin` (его использует DomainScope). Пусто → генерируется (24 симв.) | строка | `""` (auto-gen) |
| `secrets.postgresPassword` | Пароль роли `gvmd`. Пусто → генерируется (32 симв.) | строка | `""` (auto-gen) |
| `gvmd.adminUsername` | Имя GMP-admin (env `ADMIN_USERNAME`) | строка | `admin` |
| `feedRelease` | Версия фидов VT/SCAP/CERT/data-objects (env `FEED_RELEASE`) | строка версии | `24.10` |
| `feedInit` (init-контейнеры) | Первичная синхронизация фидов | — | включена; ~5 ГБ, первый старт долгий |

### Сеть, хранилище, ресурсы

| Значение | Назначение | Значения | По умолчанию |
|---|---|---|---|
| `service.gmp.port` | GMP TCP-порт (для DomainScope) | порт | `9390` |
| `service.gsad.port` | gsad HTTP Web API | порт | `9392` |
| `ingress.enabled` | Ingress на gsad Web UI | `true` \| `false` | `true` |
| `ingress.className` | IngressClass | `traefik` \| `nginx` | `traefik` |
| `ingress.host` | Хост gsad | DNS-имя | `openvas.example.com` |
| `tls.mode` | Режим TLS | `selfsigned` \| `letsencrypt` \| `existing` \| `disabled` | `selfsigned` |
| `storage.storageClassName` | StorageClass всех PVC | строка | `local-path` |
| `storage.vtData.size` | PVC под VT-плагины (с запасом) | размер | `15Gi` |
| `storage.pgData.size` / `gvmdData.size` | PVC БД / gvmd | размер | `5Gi` / `2Gi` |
| `resources.gvmd` / `resources.pgGvm` | RAM gvmd / pg-gvm (подняты из-за OOM при импорте SCAP/CERT) | k8s resources | limit 4Gi / 2Gi |

> Первая синхронизация фидов скачивает ~5 ГБ и занимает заметное время; до её завершения OpenVAS не находит уязвимостей. `feedRelease` бампать вместе с образами `*:community`.

## OWASP ZAP

StatefulSet, daemon на TCP `8090`, аутентификация по заголовку `X-ZAP-API-Key`. API-ключ читается из **смонтированного файла секрета** (`/etc/zap-secret/apiKey`), не из cmdline/env — чтобы не светиться в `ps`/`/proc`.

| Значение (`values.yaml`) | Назначение | Значения | По умолчанию |
|---|---|---|---|
| `secrets.create` | Создавать Secret чартом | `true` \| `false` | `true` |
| `secrets.existingSecretName` | Готовый Secret | строка | `""` |
| `secrets.apiKey` | API-ключ ZAP (клиенты/DomainScope шлют в `X-ZAP-API-Key`). Пусто → генерируется (48 симв.), сохраняется при апгрейдах | строка | `""` (auto-gen) |
| `image.repository` / `image.tag` | Образ daemon ZAP (multiarch, на arm64 — нативно) | image / тег | `zaproxy/zap-stable` / `latest` |
| `port` | Порт прослушивания daemon | порт | `8090` |
| `resources.limits` | CPU/RAM daemon (активные сканы едят гигабайты heap) | k8s resources | `4000m` / `4Gi` |
| `storage.size` | PVC `/home/zap/.ZAP` (сессии, контексты, политики) | размер | `10Gi` |
| `service.port` | ClusterIP-сервис ZAP API | порт | `8090` |
| `ingress.enabled` | Ingress на ZAP API (нужен только для внешних desktop-клиентов; UI у daemon нет) | `true` \| `false` | `false` |
| `tls.mode` | Режим TLS | `selfsigned` \| … | `selfsigned` |
| `jvmOpts` | JVM-опции daemon (env `JAVA_OPTS`, напр. `-Xmx`) | строка флагов | `-Xmx2g` |

## WireGuard egress (OpenVAS и OWASP ZAP)

Для реальных сканов «снаружи» оба сканера поддерживают egress через WireGuard-sidecar. Блок `wireguard.*` идентичен в обоих чартах.

| Значение | Назначение | Значения | По умолчанию |
|---|---|---|---|
| `wireguard.enabled` | Включить WG egress-sidecar | `true` \| `false` | `false` |
| `wireguard.existingSecretName` | Готовый WG-секрет | строка | `""` |
| `wireguard.privateKey` | Приватный ключ WG (секрет). **Обязателен при `enabled=true`** | base64-ключ | `""` |
| `wireguard.serverPublicKey` | Публичный ключ пира. **Обязателен при `enabled=true`** | base64-ключ | `""` |
| `wireguard.serverEndpoint` | `host:port` WG-сервера. **Обязателен при `enabled=true`** | host:port | `""` |
| `wireguard.podIp` | IP пода в WG-сети | CIDR `/32` | `10.200.0.3/32` (openvas) / `10.200.0.4/32` (zap) |
| `wireguard.serviceCidr` | Service CIDR кластера (остаётся на дефолт-шлюзе) | CIDR | `10.43.0.0/16` |
| `wireguard.podCidr` | Pod CIDR кластера | CIDR | `10.42.0.0/16` |

> Генерация ключей — см. `scripts/wg/`. Без WireGuard исходящий трафик сканеров идёт через дефолтный шлюз ноды.
