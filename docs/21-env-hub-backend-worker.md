# Переменные окружения — Hub (backend + worker)

Справочник всех переменных окружения Go-компонентов Security Hub: **backend** (HTTP API) и **worker** (фоновые задачи). Worker запускается тем же `config.Load()`, что и backend, поэтому читает тот же набор переменных; в колонке «Компонент» отмечено, где переменная реально влияет.

Колонка «По умолчанию»: `[code]` — литерал в Go, `[chart]` — значение из Helm-чарта (`charts/security-scan-hub/values.yaml`). Если значения расходятся, указаны оба.

> Секреты (`DB_PASSWORD`, `JWT_SECRET`, `KEYCLOAK_CLIENT_SECRET`, `LOCAL_ADMIN_PASSWORD`, `LLM_API_KEY` и т.п.) в Helm передаются через `secretKeyRef` (k8s Secret), а не plain values. В production задавайте их через секрет-менеджер (Vault / External Secrets / SealedSecrets).

## Аутентификация, авторизация, SSO

| Переменная | Назначение | Значения | По умолчанию | Компонент |
|---|---|---|---|---|
| `AUTH_MODE` | Режим аутентификации | `LOCAL` \| `SSO` (иное → fatal) | `SSO` [code] / `LOCAL` [chart] | оба |
| `SSO_PROVIDERS` | Список активных SSO-провайдеров (через запятую). Каждый провайдер даёт кнопку на странице логина. `keycloak` настраивается через `KEYCLOAK_*`; остальные — через `OIDC_<NAME>_*` | CSV (имена в нижнем регистре) | `keycloak` | оба |
| `APP_ENV` | Окружение приложения. В не-`development` включаются https-гейты и обязательность секретов | `development` \| `production` \| `test` | `development` [code] / `production` [chart] | оба |
| `KEYCLOAK_URL` | Внутренний URL Keycloak (backend → KC) | URL | `http://localhost:9090` [code] / `""` [chart] | оба |
| `KEYCLOAK_PUBLIC_URL` | Публичный URL Keycloak (редиректы браузера). Пусто → берётся `KEYCLOAK_URL` | URL | `""` | оба |
| `KEYCLOAK_REALM` | Realm Keycloak | строка | `securityhub` [code] / `""` [chart] | оба |
| `KEYCLOAK_CLIENT_ID` | Client ID в Keycloak | строка | `security-hub` [code] / `""` [chart] | оба |
| `KEYCLOAK_CLIENT_SECRET` | Client secret. При `AUTH_MODE=SSO` и не-dev — **обязательная** (fatal без неё) | строка (секрет) | `change-me` [code] | оба |
| `KEYCLOAK_JWKS_URL` | Переопределение `jwks_uri` из OIDC discovery (Docker/K8s split network) | URL; в prod обязан `https://` | `""` | оба |
| `KEYCLOAK_TOKEN_URL` | Переопределение `token_endpoint` | URL; в prod обязан `https://` | `""` | оба |
| `KC_JWKS_URL` | JWKS для валидации внешних Keycloak JWT (transparent SSO / atom-idp) | URL; в prod обязан `https://` | `""` | оба |
| `KC_ISSUER` | Ожидаемый `iss` во внешнем JWT | URL; в prod обязан `https://` | `""` | оба |
| `KC_AUDIENCES` | Разрешённые `aud` (client_id) внешних JWT | CSV-список | `""` | оба |
| `KC_AUTO_PROVISION` | Автосоздание пользователей в БД при первом входе по внешнему JWT | `true` \| `false` | `false` | оба |
| `FEATURE_SECURITY_HUB_INTEGRATION` | Мастер-флаг прозрачного SSO + эндпоинта `/findings/by-correlation-keys` | `true` \| `false` | `false` | оба |
| `ATOM_IDP_BASE_URL` | Доп. CORS-origin для atom-idp | URL | `""` | backend |
| `GOOGLE_OAUTH_CLIENT_ID` | Google OAuth client id | строка | `""` | оба |
| `GOOGLE_OAUTH_CLIENT_SECRET` | Google OAuth client secret | строка (секрет) | `""` | оба |
| `GOOGLE_OAUTH_REDIRECT_URL` | Google OAuth redirect URL | URL | `http://localhost:8080/api/v1/auth/google/callback` | оба |

### Generic OIDC-провайдеры (`OIDC_<NAME>_*`)

Для каждого провайдера, указанного в `SSO_PROVIDERS` (кроме `keycloak`), задаётся набор переменных с префиксом `OIDC_<UPPER(NAME)>_`. Пример: провайдер `azure` → переменные `OIDC_AZURE_*`.

| Переменная | Назначение | Значения | По умолчанию | Компонент |
|---|---|---|---|---|
| `OIDC_<NAME>_DISPLAY_NAME` | Метка кнопки входа в UI | строка | имя провайдера | оба |
| `OIDC_<NAME>_DISCOVERY_URL` | URL OIDC well-known (`/.well-known/openid-configuration`). Обязательна, если не заданы все endpoint-overrides явно | URL | `""` | оба |
| `OIDC_<NAME>_CLIENT_ID` | Client ID в IdP | строка | `""` | оба |
| `OIDC_<NAME>_CLIENT_SECRET` | Client Secret | строка (секрет) | `""` | оба |
| `OIDC_<NAME>_SCOPES` | Запрашиваемые scopes — через **пробел** | строка | `openid profile email` | оба |
| `OIDC_<NAME>_AUTO_PROVISION` | Автосоздание пользователей в БД при первом входе (роль `viewer`). `false` — принимать только уже существующих | `true` \| `false` | `true` | оба |
| `OIDC_<NAME>_TRUST_EMAIL` | Доверять email из IdP как верифицированному, даже если `email_verified` отсутствует в токене. **Обязательна для Microsoft Entra ID (Azure AD v2)** — без неё любой вход через Azure завершается 403 | `true` \| `false` | `false` | оба |
| `OIDC_<NAME>_AUTH_URL` | Переопределение authorization endpoint | URL | из discovery | оба |
| `OIDC_<NAME>_TOKEN_URL` | Переопределение token endpoint | URL | из discovery | оба |
| `OIDC_<NAME>_JWKS_URL` | Переопределение jwks_uri | URL | из discovery | оба |
| `OIDC_<NAME>_ISSUER` | Переопределение issuer | URL | из discovery | оба |
| `OIDC_<NAME>_END_SESSION_URL` | Переопределение end_session_endpoint | URL | из discovery | оба |

> Разрешение endpoints: явный override > discovery document > ошибка при старте. Redirect URI, который нужно зарегистрировать в IdP: `{FRONTEND_URL}/auth/callback`.
| `JWT_SECRET` | Секрет подписи внутренних JWT. В не-dev — **обязательная** (fatal) | строка (секрет) | `change-this-secret-key` [code] | оба |
| `ACCESS_TOKEN_TTL_MINUTES` | TTL access-токена | целое ≥1 | `15` | оба |
| `REFRESH_TOKEN_TTL_DAYS` | TTL refresh-токена | целое ≥1 | `7` | оба |
| `LOCAL_ADMIN_PASSWORD` | Пароль seed-админа в `LOCAL`-режиме (логин `admin@localhost.local`). Без неё на чистой БД вход невозможен | строка (секрет) | `""` | backend |
| `ALLOWED_ORIGINS` | CORS allowlist (без `*`) | CSV URL | `http://localhost:3000,http://localhost:8084` | оба |

## База данных

| Переменная | Назначение | Значения | По умолчанию | Компонент |
|---|---|---|---|---|
| `DB_HOST` | Хост PostgreSQL | hostname | `localhost` [code] | оба |
| `DB_PORT` | Порт PostgreSQL | число | `5432` | оба |
| `DB_NAME` | Имя БД | строка | `securityhub` | оба |
| `DB_USER` | Пользователь БД | строка | `securityhub` | оба |
| `DB_PASSWORD` | Пароль БД. В не-dev — **обязательная** (fatal) | строка (секрет) | `securityhub123` [code] | оба |
| `DB_SSLMODE` | Режим SSL (`disable`/`require`/`verify-full`, …) | enum libpq | `disable` | оба |

## LLM / Sandbox (активная верификация находок)

| Переменная | Назначение | Значения | По умолчанию | Компонент |
|---|---|---|---|---|
| `LLM_BASE_URL` | Базовый URL LLM API | URL | `""` | оба |
| `LLM_API_KEY` | Ключ LLM API | строка (секрет) | `""` | оба |
| `LLM_MODEL` | Имя модели | строка | `glm-4-plus` | оба |
| `LLM_DRY_RUN` | Не обращаться к LLM (заглушка) | `true` \| `false` | `false` [code] / `true` [chart] | оба |
| `LLM_FALSE_POSITIVE_THRESHOLD` | Порог уверенности для отсева false-positive | float `0..1` | `0.9` | оба |
| `LLM_WORKERS` | Кол-во LLM-воркеров | целое | `5` [code] | оба |
| `LLM_PROMPTS_DIR` | Каталог с промптами | путь | `""` | оба |
| `LLM_REQUEST_TIMEOUT_SECONDS` | Таймаут запроса к LLM | целое (сек) | `180` | оба |
| `SANDBOX_TYPE` | Тип песочницы | `""` (выкл) \| `docker` \| `kubernetes` | `""` [code] / worker `kubernetes` [chart] | worker |
| `SANDBOX_IMAGE` | Docker-образ песочницы | image ref | `dexionius/sshub-sandbox-tools:latest` | оба |
| `SANDBOX_TIMEOUT_SECONDS` | Таймаут выполнения в песочнице | целое (сек) | `120` | оба |
| `SANDBOX_OUTPUT_LIMIT_KB` | Лимит вывода песочницы | целое (КБ) | `10` | оба |
| `SANDBOX_NAMESPACE` | k8s namespace для pod песочницы | строка | `""` (= namespace релиза) | оба |
| `SANDBOX_KUBECONFIG` | Путь к kubeconfig; пусто → in-cluster | путь | `""` | оба |
| `SANDBOX_WG_SECRET_NAME` | Имя k8s Secret с WireGuard-ключами | строка | `""` | оба |
| `SANDBOX_WG_POD_IP` | WireGuard IP pod (CIDR) | CIDR | `10.200.0.3/32` | оба |
| `SANDBOX_WG_PRIVATE_KEY` | WireGuard приватный ключ (docker/local) | строка (секрет) | `""` | оба |
| `SANDBOX_WG_SERVER_PUBLIC_KEY` | WireGuard публичный ключ сервера | строка | `""` | оба |
| `SANDBOX_WG_SERVER_ENDPOINT` | WireGuard endpoint сервера | host:port | `""` | оба |

## Уведомления (Telegram / Mattermost)

| Переменная | Назначение | Значения | По умолчанию | Компонент |
|---|---|---|---|---|
| `NOTIFICATIONS_DRY_RUN` | Не отправлять реальные уведомления | `true` \| `false` | `false` | оба |
| `TELEGRAM_NOTIFICATION_WORKERS` | Кол-во Telegram-воркеров (River не принимает 0) | целое ≥1 | `5` | worker |
| `MATTERMOST_NOTIFICATION_WORKERS` | Кол-во Mattermost-воркеров | целое ≥1 | `10` | worker |

> Токен Telegram-бота хранится в конфигурации уведомлений в БД (через UI), а не в env.

## Очереди River (concurrency воркеров)

| Переменная | Назначение | Значения | По умолчанию | Компонент |
|---|---|---|---|---|
| `DISPATCHER_WORKERS` | Воркеры диспетчера событий | целое | `10` | worker |
| `JIRA_SYNC_WORKERS` | Воркеры синхронизации с Jira | целое | `4` | worker |
| `FINDING_COPY_WORKERS` | Воркеры fan-out копирования находок | целое | `4` | worker |
| `JIRA_REVERSE_SYNC_WORKERS` | Воркеры обратной синхронизации Jira→Hub | целое | `1` | worker |
| `DUAL_VERIFY_WORKERS` | Воркеры dual-verify | целое | `2` | worker |
| `FRONTEND_BASE_URL` | Базовый URL фронта для ссылок в уведомлениях | URL | `http://localhost:3000` | worker |

## Jira (интеграция, маршрутизация, webhook, SSRF-гард)

| Переменная | Назначение | Значения | По умолчанию | Компонент |
|---|---|---|---|---|
| `FALLBACK_JIRA_URL` | URL Jira, если у проекта не задан `jira_config.base_url` | URL | `""` | оба |
| `FEATURE_FINDING_COPY` | Включить fan-out копирование находок | `true` \| `false` | `false` | оба |
| `FEATURE_JIRA_REVERSE_SYNC` | Включить периодический Jira→Hub sync статусов | `true` \| `false` | `false` | оба |
| `JIRA_REVERSE_SYNC_INTERVAL_MINUTES` | Период тика reverse-sync | целое (мин) | `60` | оба |
| `JIRA_REVERSE_SYNC_BATCH_SIZE` | Размер батча reverse-sync | целое | `500` | оба |
| `FEATURE_JIRA_ENGINE_ROUTING` | Per-engine issuetype override (`issuetype_by_engine`) | `true` \| `false` | `true` | worker |
| `FEATURE_JIRA_WEBHOOK` | Jira→Hub webhook receiver (при `false` → 404) | `true` \| `false` | `true` | backend |
| `HUB_BASE_URL` | Публичный URL Hub для callback-URL webhook и ссылок | URL | `""` | оба |
| `JIRA_ALLOW_HTTP` | Разрешить `http://` для Jira base URL (SSRF-гард) | `true` \| `false` | `false` | оба |
| `JIRA_ALLOW_LOCAL_DIAL` | Разрешить обращение к локальным/приватным адресам Jira | `true` \| `false` | `false` | оба |
| `JIRA_BASE_URL_ALLOWLIST` | Allowlist допустимых Jira base URL | CSV/список | `""` (без ограничения) | оба |

## Dual-verify (Hub ↔ DomainScope)

| Переменная | Назначение | Значения | По умолчанию | Компонент |
|---|---|---|---|---|
| `FEATURE_DUAL_VERIFY` | Мастер-флаг dual_confirm flow | `true` \| `false` | `false` | оба |
| `DOMAINSCOPE_VERIFY_URL` | Endpoint сканера для POST verify-finding. В prod обязан `https://` | URL | `""` | оба |
| `DOMAINSCOPE_VERIFY_API_KEY` | Outbound API-key Hub→DomainScope | строка (секрет) | `""` | оба |
| `DOMAINSCOPE_VERIFY_HMAC_SECRET` | HMAC-подпись исходящих запросов | строка (секрет) | `""` | оба |
| `SCANNER_CALLBACK_API_KEY` | Inbound API-key для callback от сканера | строка (секрет) | `""` | оба |
| `SCANNER_CALLBACK_HMAC_SECRET` | Primary HMAC inbound callback (32+ байт) | строка (секрет) | `""` | оба |
| `SCANNER_CALLBACK_HMAC_SECRET_PREVIOUS` | Доп. HMAC-ключ на окно ротации | строка (секрет) | `""` | оба |
| `DUAL_VERIFY_CALLBACK_BASE_URL` | Публичный URL Hub для генерации callback_url. При `FEATURE_DUAL_VERIFY=true` пустой → fail-fast | URL | `""` | оба |
| `DUAL_VERIFY_SCANNER_TIMEOUT` | Таймаут ожидания callback | duration | `60s` | оба |
| `DUAL_VERIFY_SCHEDULER_INTERVAL` | Период тика scheduler | duration | `15m` | оба |
| `DUAL_VERIFY_BATCH_SIZE` | Кандидатов за тик | целое | `100` | оба |
| `DUAL_VERIFY_MAX_CONCURRENT` | Глобальный cap конкурентности | целое | `5` | оба |
| `DUAL_VERIFY_PER_PROJECT_HOURLY_CLOSURE_CAP` | Лимит закрытий/час на проект | целое | `10` | оба |
| `DUAL_VERIFY_RETRY_BACKOFF` | Задержки между retry | CSV duration | `30m,2h,6h` | оба |
| `DUAL_VERIFY_INCONCLUSIVE_COOLDOWN` | Окно перед re-enqueue inconclusive | duration | `720h` | оба |
| `DUAL_VERIFY_REAPER_INTERVAL` | Период тика reaper | duration | `1h` | оба |

## Manual Rescan (Hub → сканеры)

| Переменная | Назначение | Значения | По умолчанию | Компонент |
|---|---|---|---|---|
| `FEATURE_MANUAL_RESCAN` | Включить ручной rescan | `true` \| `false` | `false` | backend |
| `DOMAINSCOPE_RESCAN_URL` | URL DomainScope для rescan/probe | URL | `""` | оба |
| `DOMAINSCOPE_RESCAN_API_KEY` | API-key DomainScope rescan | строка (секрет) | `""` | оба |
| `IAC_SCANNER_RESCAN_URL` | URL iac-scanner для rescan | URL | `""` | оба |
| `IAC_SCANNER_RESCAN_API_KEY` | API-key iac-scanner rescan | строка (секрет) | `""` | оба |
| `RESCAN_TIMEOUT_SECONDS` | Таймаут rescan/probe-запроса | целое (сек) | `10` | оба |
| `RESCAN_HOST_ALLOWLIST` | Allowlist хостов rescan (SSRF-гард) | список | `""` | оба |

## Auto-verify fixes

| Переменная | Назначение | Значения | По умолчанию | Компонент |
|---|---|---|---|---|
| `FEATURE_AUTO_VERIFY_FIXES` | Гейт авто-закрытия находок после импорта (часть тройного гейта) | `true` \| `false` | `false` | оба |

## Сервер, хранилище, логи, лимиты, лицензия

| Переменная | Назначение | Значения | По умолчанию | Компонент |
|---|---|---|---|---|
| `SERVER_PORT` | Порт HTTP-сервера | число | `8080` [code] / `8082` [chart] | backend |
| `FRONTEND_URL` | URL фронта (редиректы, ссылки, fallback callback) | URL | `http://localhost:3000` [code] / `https://hub.example.com` [chart] | оба |
| `STORAGE_PATH` | Каталог хранения отчётов | путь | `./storage` [code] / `/app/storage/reports` [chart] | оба |
| `LOGS_PATH` | Каталог логов | путь | `./logs` | оба |
| `LOG_LEVEL` | Уровень логов; переопределяет выбор по `APP_ENV` | `debug` \| `info` \| `warn` \| `error` | `debug` при `APP_ENV=development`, иначе `info` | оба |
| `LOG_FORMAT` | Формат логов | `json` \| `console` | `json` в production | оба |
| `LOG_FILE_SINK_ENABLED` | Писать ли логи в файл (поверх stdout). **В k8s ставьте `false`** — см. [17. Операции → Логирование](17-operations.md#в-kubernetes-выключайте-файловый-лог-синк) | `true` \| `false` | `true` | оба |
| `LOG_MAX_SIZE_MB` | Размер лог-файла до ротации | целое ≥1 | `50` | оба |
| `LOG_MAX_BACKUPS` | Кол-во хранимых ротированных логов | целое ≥0 | `5` | оба |
| `LOG_MAX_AGE_DAYS` | Макс. возраст ротированного лога | целое ≥0 | `30` | оба |
| `LOG_COMPRESS` | Сжимать ротированные логи | `true` \| `false` | `true` | оба |
| `REDIS_URL` | URL Redis | URL | `redis://localhost:6379` | оба |
| `LICENSE_SERVER_URL` | URL лицензионного сервера (пусто = offline) | URL | `""` | оба |
| `MAX_UPLOAD_SIZE_MB` | Лимит размера загрузки | целое ≥1 | `500` | оба |
| `RATE_LIMIT_API` | Rate limit API (req/min) | целое ≥1 | `100` | backend |
| `RATE_LIMIT_AUTH` | Rate limit auth-эндпоинтов (req/min) | целое ≥1 | `10` | backend |
| `CLEANUP_RETENTION_COMPLETED_DAYS` | Хранение завершённых отчётов | целое ≥0 | `7` | worker |
| `CLEANUP_RETENTION_FAILED_DAYS` | Хранение failed-отчётов | целое ≥0 | `30` | worker |
| `CLEANUP_RETENTION_PENDING_DAYS` | Хранение pending-отчётов | целое ≥0 | `0` | worker |
| `CLEANUP_RETENTION_ORPHAN_HOURS` | Удаление orphan-файлов (0 = выкл) | целое ≥0 | `24` | worker |
| `CLEANUP_DRY_RUN` | Cleanup в режиме dry-run | `true` \| `false` | `false` | worker |
| `REFRESH_CLEANUP_RETENTION_DAYS` | Хранение refresh-токенов | целое ≥1 | `30` | worker |

## Устаревшие (legacy)

Читаются только чтобы предупредить оператора (WARN в логе) — расписание cleanup
больше НЕ управляется этими переменными (теперь периодические job'ы River).

| Переменная | Назначение | По умолчанию | Компонент |
|---|---|---|---|
| `CLEANUP_SCHEDULE` | Устар.: расписание report-cleanup (игнорируется, только WARN) | `0 2 * * *` | worker |
| `REFRESH_CLEANUP_SCHEDULE` | Устар.: расписание refresh-token cleanup (игнорируется, только WARN) | `0 3 * * *` | worker |

## Обязательные переменные (fatal без них)

- `JWT_SECRET` — fatal при `APP_ENV != development`.
- `DB_PASSWORD` — fatal при `APP_ENV != development`.
- `KEYCLOAK_CLIENT_SECRET` — fatal при `AUTH_MODE=SSO` и `APP_ENV != development` (если `keycloak` в `SSO_PROVIDERS`).
- `OIDC_<NAME>_CLIENT_ID` / `OIDC_<NAME>_CLIENT_SECRET` — обязательны для каждого провайдера в `SSO_PROVIDERS` кроме `keycloak`.
- `LOCAL_ADMIN_PASSWORD` — de-facto обязательна для `AUTH_MODE=LOCAL` (без неё нет первого админа).
- `DUAL_VERIFY_CALLBACK_BASE_URL` — fail-fast при `FEATURE_DUAL_VERIFY=true`.
- В `production` https-гейты (fatal при `http://`, если заданы): `KEYCLOAK_JWKS_URL`, `KEYCLOAK_TOKEN_URL`, `KC_JWKS_URL`, `KC_ISSUER`, `DOMAINSCOPE_VERIFY_URL`.

> Большинство переменных групп dual-verify, rescan, jira-routing, а также `KC_*`, `REDIS_URL`, `RATE_LIMIT_*` и др. в дефолтном чарте не выставляются — работают на code-дефолтах, пока оператор не пробросит их через `extraEnv`.
