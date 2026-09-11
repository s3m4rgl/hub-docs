# Переменные окружения: backend и worker

Справочник всех переменных окружения Go-компонентов Security Hub: **backend** (HTTP API) и **worker** (фоновые задачи). Worker запускается тем же `config.Load()`, что и backend, поэтому читает тот же набор переменных; в колонке «Компонент» отмечено, где переменная реально влияет.

Колонка «По умолчанию»: `[code]` — литерал в Go, `[chart]` — значение из Helm-чарта (`charts/security-scan-hub/values.yaml`). Если значения расходятся, указаны оба.

> Секреты (`DB_PASSWORD`, `JWT_SECRET`, `KEYCLOAK_CLIENT_SECRET`, `LOCAL_ADMIN_PASSWORD`, `LLM_API_KEY` и т.п.) в Helm передаются через `secretKeyRef` (k8s Secret), а не plain values. В production задавайте их через секрет-менеджер (Vault / External Secrets / SealedSecrets).

## Аутентификация, авторизация, SSO

| Переменная | Назначение | Значения | По умолчанию | Компонент |
|---|---|---|---|---|
| `AUTH_MODE` | Режим аутентификации | `LOCAL` \| `SSO` (иное → аварийный останов) | `SSO` [code] / `LOCAL` [chart] | оба |
| `SSO_PROVIDERS` | Список активных провайдеров через запятую. Каждый даёт кнопку на странице входа. `keycloak` настраивается через `KEYCLOAK_*`, остальные — через `OIDC_<ИМЯ>_*` | список через запятую, имена строчными | `keycloak` | оба |
| `APP_ENV` | Окружение. В не-`development` включаются проверки `https` и обязательность секретов | `development` \| `production` \| `test` | **`production`** [code] | оба |
| `ALLOW_DEV_MODE` | Разрешает обход аутентификации по служебному токену разработки. Требует **одновременно** `APP_ENV=development`. Принимается **только** точное значение `true` | `true` \| `false` | `false` | backend |
| `BOOTSTRAP_ADMIN_EMAILS` | Адреса, получающие роль администратора при первом входе через IdP. Нужен, чтобы завести первого администратора, не выключая SSO. Сравнение регистронезависимое; адрес без подтверждения провайдером роль не получает. При старте пишется предупреждение — **уберите переменную**, как только администратор заведён | список адресов через запятую | `""` | backend |
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
| `OIDC_<NAME>_DISCOVERY_URL` | URL OIDC well-known (`/.well-known/openid-configuration`). Обязательна, если не заданы все эндпоинт-overrides явно | URL | `""` | оба |
| `OIDC_<NAME>_CLIENT_ID` | Client ID в IdP | строка | `""` | оба |
| `OIDC_<NAME>_CLIENT_SECRET` | Client Secret | строка (секрет) | `""` | оба |
| `OIDC_<NAME>_SCOPES` | Запрашиваемые scopes — через **пробел** | строка | `openid profile email` | оба |
| `OIDC_<NAME>_AUTO_PROVISION` | Автосоздание пользователей в БД при первом входе (роль `viewer`). `false` — принимать только уже существующих | `true` \| `false` | `true` | оба |
| `OIDC_<NAME>_TRUST_EMAIL` | Доверять email из IdP как верифицированному, даже если `email_verified` отсутствует в токене. **Обязательна для Microsoft Entra ID (Azure AD v2)** — без неё любой вход через Azure завершается 403 | `true` \| `false` | `false` | оба |
| `OIDC_<NAME>_AUTH_URL` | Переопределение authorization эндпоинт | URL | из discovery | оба |
| `OIDC_<NAME>_TOKEN_URL` | Переопределение token эндпоинт | URL | из discovery | оба |
| `OIDC_<NAME>_JWKS_URL` | Переопределение jwks_uri | URL | из discovery | оба |
| `OIDC_<NAME>_ISSUER` | Переопределение issuer | URL | из discovery | оба |
| `OIDC_<NAME>_END_SESSION_URL` | Переопределение end_session_endpoint | URL | из discovery | оба |

> Разрешение адресов: явное переопределение важнее сведений из документа
> обнаружения; если не хватает и того и другого — старт прерывается. Адрес
> возврата, который нужно зарегистрировать у провайдера:
> `{FRONTEND_URL}/auth/callback`.

### Токены и доступ

| Переменная | Назначение | Значения | По умолчанию | Компонент |
|---|---|---|---|---|
| `JWT_SECRET` | Секрет подписи внутренних токенов. Вне `development` — **обязательная**, иначе аварийный останов | строка (секрет) | `change-this-secret-key` [code] | оба |
| `LICENSE_SECRET` | Отдельный секрет для лицензионных данных. Если не задан — берётся `JWT_SECRET`. Задавайте явно на новых установках, чтобы `JWT_SECRET` можно было менять независимо | строка (секрет) | значение `JWT_SECRET` | оба |
| `ACCESS_TOKEN_TTL_MINUTES` | Срок жизни токена доступа | целое ≥ 1 | `15` | backend |
| `REFRESH_TOKEN_TTL_DAYS` | Срок жизни токена обновления | целое ≥ 1 | `7` | backend |
| `LOCAL_ADMIN_PASSWORD` | Пароль первого администратора в режиме `LOCAL`. Без него на чистой базе войти невозможно | строка (секрет) | `""` | backend |
| `ALLOWED_ORIGINS` | Список разрешённых источников для межсайтовых запросов. Значение `*` отклоняется | адреса через запятую | `http://localhost:3000,http://localhost:8084` | backend |
| `TRUSTED_PROXIES` | Адреса и подсети обратных прокси, которым разрешено подменять адрес клиента заголовками `X-Forwarded-For` / `X-Real-IP`. **Пусто — не доверять никому**: адресом клиента считается адрес TCP-соединения | список IP или CIDR через запятую | `""` | backend |

!!! warning "`TRUSTED_PROXIES` и ограничение частоты"

    По умолчанию заголовки пересылки игнорируются полностью — это безопасно,
    потому что иначе клиент мог бы подделать свой адрес и обойти ограничение
    частоты обращений к эндпоинтам входа, а в журнале действий остался бы
    чужой адрес.

    Обратная сторона: если Hub стоит за обратным прокси и переменная не
    задана, все запросы будут выглядеть пришедшими с адреса прокси —
    ограничение частоты станет общим на всех. Задавайте её, когда прокси
    действительно есть, и не задавайте, когда его нет.

## База данных

| Переменная | Назначение | Значения | По умолчанию | Компонент |
|---|---|---|---|---|
| `DB_HOST` | Хост PostgreSQL | hostname | `localhost` [code] | оба |
| `DB_PORT` | Порт PostgreSQL | число | `5432` | оба |
| `DB_NAME` | Имя БД | строка | `securityhub` | оба |
| `DB_USER` | Пользователь БД | строка | `securityhub` | оба |
| `DB_PASSWORD` | Пароль базы. Вне `development` — **обязательная**, иначе аварийный останов | строка (секрет) | `securityhub123` [code] | оба |
| `DB_SSLMODE` | Режим TLS (`disable`, `require`, `verify-full` и другие значения libpq) | перечисление | `disable` | оба |
| `DB_MAX_OPEN_CONNS` | Верхний предел соединений с базой на процесс | целое ≥ 1 | `25` | оба |
| `DB_MAX_IDLE_CONNS` | Сколько соединений держать открытыми в простое | целое ≥ 0 | `5` | оба |
| `DB_CONN_MAX_LIFETIME_MINUTES` | Максимальное время жизни соединения | целое ≥ 1 | `30` | оба |

> Предел соединений действует **на процесс**. Каждая реплика backend и worker
> открывает свой пул: при пяти репликах с настройками по умолчанию это уже 125
> соединений — сверяйтесь с `max_connections` базы.

## LLM / Sandbox (активная верификация находок)

| Переменная | Назначение | Значения | По умолчанию | Компонент |
|---|---|---|---|---|
| `LLM_BASE_URL` | Базовый URL LLM API | URL | `""` | оба |
| `LLM_API_KEY` | Ключ LLM API | строка (секрет) | `""` | оба |
| `LLM_MODEL` | Имя модели | строка | `glm-4-plus` | оба |
| `LLM_DRY_RUN` | Не обращаться к LLM (заглушка) | `true` \| `false` | `false` [code] / `true` [chart] | оба |
| `LLM_FALSE_POSITIVE_THRESHOLD` | Порог уверенности для отсева false-positive | float `0..1` | `0.9` | оба |
| `LLM_WORKERS` | Кол-во LLM-worker | целое | `5` [code] | оба |
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
| `SANDBOX_WG_SERVER_ENDPOINT` | WireGuard эндпоинт сервера | host:port | `""` | оба |

## Уведомления

| Переменная | Назначение | Значения | По умолчанию | Компонент |
|---|---|---|---|---|
| `NOTIFICATIONS_DRY_RUN` | Не отправлять уведомления по-настоящему | `true` \| `false` | `false` | worker |
| `FRONTEND_BASE_URL` | Базовый адрес интерфейса для ссылок внутри уведомлений | адрес | `http://localhost:3000` | worker |

> С 0.33 все каналы доставки — плагины. Токены ботов, адреса вебхуков и
> пороги задаются в настройках канала на карточке проекта, а не переменными
> окружения; сами плагины устанавливаются администратором. Переменные
> `MATTERMOST_NOTIFICATION_WORKERS`, `MAXRU_NOTIFICATION_WORKERS` и
> `MATTERMOST_ALLOW_LOCAL_DIAL` удалены — см. [Уведомления](integration-notifications.md).

### Электронная почта

Параметры SMTP самого Hub. Они действуют, пока плагин `email-notifier` не
задал собственных: цепочка — проект → установка плагина → эти переменные.

| Переменная | Назначение | Значения | По умолчанию | Компонент |
|---|---|---|---|---|
| `SMTP_HOST` | Сервер отправки. Пусто — отправка по почте не работает | имя узла | `""` | worker |
| `SMTP_PORT` | Порт | число | `587` | worker |
| `SMTP_USERNAME` | Учётная запись | строка | `""` | worker |
| `SMTP_PASSWORD` | Пароль | строка (секрет) | `""` | worker |
| `SMTP_FROM` | Адрес отправителя | адрес почты | `""` | worker |
| `SMTP_TLS_MODE` | Режим TLS: `starttls` (обычно порт 587) или прямой TLS | строка | `starttls` | worker |

## Параллелизм очередей

| Переменная | Очередь | По умолчанию |
|---|---|---|
| `DISPATCHER_WORKERS` | Очередь по умолчанию: диспетчер событий, разбор отчётов | `10` |
| `SARIF_PROCESSING_WORKERS` | Разбор загруженных отчётов | `4` |
| `TELEGRAM_NOTIFICATION_WORKERS` | Уведомления в Telegram | `5` |
| `EMAIL_NOTIFICATION_WORKERS` | Уведомления по электронной почте встроенным путём | `5` |
| `FINDING_COPY_WORKERS` | Копирование находок между продуктами | `4` |
| `DUAL_VERIFY_WORKERS` | Перепроверка вторым источником | `2` |
| `PLUGIN_FINDING_SOURCE_SYNC_WORKERS` | Опрос источников-плагинов | `4` |

Все значения — для процесса `worker`. Ноль не допускается: очередь с нулевым
параллелизмом не обрабатывается. Число обработчиков очереди обогащения
находок отдельной переменной не имеет — оно на единицу меньше
`PLUGIN_RUNNER_PER_PLUGIN_LIMIT`.

## Учёт задач и исходящие обращения

Встроенная интеграция с Jira удалена в 0.33: задачи ведут плагины-провайдеры,
их настройки живут в конфигурации плагина для проекта. Переменных окружения у
самой интеграции почти не осталось.

| Переменная | Назначение | Значения | По умолчанию | Компонент |
|---|---|---|---|---|
| `TICKET_STATUS_POLL_INTERVAL_MINUTES` | Период опроса статусов задач у провайдера — второй канал закрытия там, где трекер не дотягивается до Hub | целое (мин) | `60` | worker |
| `TICKET_STATUS_POLL_BATCH_SIZE` | Потолок находок за один прогон опроса | целое | `500` | worker |
| `HUB_BASE_URL` | Публичный адрес Hub для ссылок и адресов обратного вызова | URL | `""` | оба |
| `FEATURE_FINDING_COPY` | Копирование находок между продуктами | `true` \| `false` | `false` | оба |

### SSRF-гард: по подсистемам, а не одним рычагом

Раньше `JIRA_ALLOW_HTTP` и `JIRA_ALLOW_LOCAL_DIAL` управляли исходящими
обращениями и не-Jira клиентов. Теперь у каждой подсистемы свои переменные с
её префиксом:

| Префикс | Подсистема |
|---|---|
| `VCS_` | Статусы коммитов и комментарии в GitHub/GitLab |
| `RESCAN_` | Обращения к сканерам при ручной перепроверке |
| `IAC_SOURCE_` | Получение исходников для сканера инфраструктурного кода |

Для каждого префикса действуют три переменные: `<ПРЕФИКС>_ALLOW_HTTP`,
`<ПРЕФИКС>_ALLOW_LOCAL_DIAL` и `<ПРЕФИКС>_HOST_ALLOWLIST` (список узлов через
запятую). По умолчанию все три пусты: только `https` и только публичные
адреса.

Если в окружении остались `JIRA_ALLOW_*`, Hub один раз на подсистему пишет
предупреждение: переменная больше не действует, задайте собственную. Это
ужесточение, и молчать о нём значило бы получить «интеграция сломалась после
обновления» вместо «настройку переименовали».

Исходящие обращения плагинов ограничиваются отдельно — `PLUGIN_EGRESS_*`, см.
[Платформу плагинов](#платформа-плагинов).

## Dual-verify (Hub ↔ DomainScope)

| Переменная | Назначение | Значения | По умолчанию | Компонент |
|---|---|---|---|---|
| `FEATURE_DUAL_VERIFY` | Мастер-флаг dual_confirm flow | `true` \| `false` | `false` | оба |
| `DOMAINSCOPE_VERIFY_URL` | Эндпоинт сканера для POST verify-находка. В prod обязан `https://` | URL | `""` | оба |
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

## Автоматическое закрытие исправленных находок

| Переменная | Назначение | Значения | По умолчанию | Компонент |
|---|---|---|---|---|
| `FEATURE_AUTO_VERIFY_FIXES` | Глобальное разрешение автоматически закрывать исправленные находки. Одно из **трёх** условий: нужны ещё признак в настройках проекта и `verify_fixes=true` при загрузке отчёта | `true` \| `false` | `false` | оба |
| `AUTO_VERIFY_PROBE_RETRIES` | Сколько раз подряд проверять отсутствие находки внутри одной проверки. Любой ответ «на месте» или «неопределённо» немедленно оставляет находку открытой | целое ≥ 1 | `3` | worker |
| `AUTO_VERIFY_ABSENT_THRESHOLD` | Сколько **последовательных** проверок должны дать «отсутствует» до закрытия. Любое обнаружение сбрасывает счётчик. Значение `1` возвращает прежнее поведение «закрывать по одному наблюдению» | целое ≥ 1 | `3` | worker |

!!! danger "Не ставьте `AUTO_VERIFY_ABSENT_THRESHOLD=1`"

    Именно такое поведение было раньше и привело к массовому ложному
    закрытию настоящих находок: значительная часть вернулась при следующем
    сканировании. Два уровня защиты — повторы внутри проверки и кворум между
    проверками — добавлены как реакция на этот случай и по отдельности
    недостаточны.

## Сервер, хранилище, логи, лимиты, лицензия

| Переменная | Назначение | Значения | По умолчанию | Компонент |
|---|---|---|---|---|
| `SERVER_PORT` | Порт HTTP-сервера | число | `8080` [code] / `8082` [chart] | backend |
| `FRONTEND_URL` | URL фронта (редиректы, ссылки, fallback callback) | URL | `http://localhost:3000` [code] / `https://hub.example.com` [chart] | оба |
| `STORAGE_PATH` | Каталог хранения отчётов | путь | `./storage` [code] / `/app/storage/reports` [chart] | оба |
| `LOGS_PATH` | Каталог логов | путь | `./logs` | оба |
| `LOG_MAX_SIZE_MB` | Размер лог-файла до ротации | целое ≥1 | `50` | оба |
| `LOG_MAX_BACKUPS` | Кол-во хранимых ротированных логов | целое ≥0 | `5` | оба |
| `LOG_MAX_AGE_DAYS` | Макс. возраст ротированного лога | целое ≥0 | `30` | оба |
| `LOG_COMPRESS` | Сжимать ротированные журналы | `true` \| `false` | `true` | оба |
| `LOG_LEVEL` | Уровень подробности: `debug`, `info`, `warn`, `error`. Переопределяет уровень, выведенный из `APP_ENV`, не меняя формат вывода — можно включить подробный вывод в промышленной среде для диагностики | строка | по `APP_ENV`: `development` → `debug`, иначе `info` | оба |
| `LICENSE_SERVER_URL` | Адрес сервера лицензий. Пусто — проверка не выполняется | адрес | `""` | оба |
| `MAX_UPLOAD_SIZE_MB` | Предел размера загружаемого файла. Обратите внимание: предел **разбора** — 50 МиБ, он ниже | целое ≥ 1 | `500` | backend |
| `RATE_LIMIT_API` | Частота обращений к обычным эндпоинтам, запросов в минуту | целое ≥ 1 | `100` | backend |
| `RATE_LIMIT_API_USER` | Второй слой лимита — по личности, запросов в минуту. Работает вместе с общим полом по адресу | целое ≥ 1 | `300` | backend |
| `RATE_LIMIT_API_SERVICE_ACCOUNT` | То же для ключа сервисного аккаунта | целое ≥ 1 | `1200` | backend |
| `TRUSTED_PROXIES` | Прокси, чьему `X-Forwarded-For` можно верить. Без списка адрес клиента подделывается заголовком в обход лимитера | список адресов/сетей | `""` | backend |
| `HTTP_REQUEST_TIMEOUT_SECONDS` | Потолок времени HTTP-запроса. Ставит дедлайн контексту: зависший запрос отменяется и отдаёт соединение пулу. Долгие по построению маршруты (загрузка отчёта, выгрузки, экспорт) исключены. `0` выключает | целое ≥ 0 | `120` | backend |
| `MIGRATION_LOCK_WAIT_SECONDS` | Сколько реплика ждёт блокировку миграций при старте | целое ≥ 1 | `180` | оба |
| `MIGRATIONS_DIR` | Каталог с SQL-миграциями. Пусто — поиск по встроенному списку путей. Нужен только при нестандартной раскладке файлов (пакеты `.deb`/`.rpm`) | путь | `""` | оба |
| `LOG_FILE_SINK_ENABLED` | Писать журнал в файл (`LOGS_PATH`) дополнительно к стандартному выводу. В k8s журналы собираются со стандартного вывода, и файловый приёмник там — лишний источник отказов | `true` \| `false` | `true` | оба |
| `RATE_LIMIT_AUTH` | Частота обращений к эндпоинтам входа, запросов в минуту | целое ≥ 1 | `10` | backend |
| `CLEANUP_RETENTION_COMPLETED_DAYS` | Хранение обработанных отчётов, суток | целое ≥ 0 | `7` | worker |
| `CLEANUP_RETENTION_FAILED_DAYS` | Хранение отчётов с ошибкой разбора, суток | целое ≥ 0 | `30` | worker |
| `CLEANUP_RETENTION_PENDING_DAYS` | Хранение необработанных отчётов, суток | целое ≥ 0 | `0` | worker |
| `CLEANUP_RETENTION_ORPHAN_HOURS` | Через сколько часов удалять файлы без записи в базе. `0` отключает | целое ≥ 0 | `24` | worker |
| `CLEANUP_BATCH_SIZE` | Размер порции при очистке — и при выборке из базы, и при обходе каталога. Определяет память на одну порцию. `0` — значение по умолчанию из кода; значения выше 10 000 обрезаются | целое 0…10 000 | `0` | worker |
| `CLEANUP_DRY_RUN` | Очистка без удаления: только сообщения о том, что было бы удалено | `true` \| `false` | `false` | worker |
| `REFRESH_CLEANUP_RETENTION_DAYS` | Хранение токенов обновления, суток | целое ≥ 1 | `30` | worker |

## Наблюдаемость

| Переменная | Назначение | Значения | По умолчанию | Компонент |
|---|---|---|---|---|
| `METRICS_ENABLED` | Отдавать метрики Prometheus | `true` \| `false` | `true` | все |
| `METRICS_PORT` | **Отдельный** порт метрик, не совпадает с `SERVER_PORT`. Свой реестр у каждого долгоживущего процесса: backend, worker, pentagi-worker | число | `9090` | все |
| `METRICS_COLLECT_INTERVAL_SECONDS` | Период сбора бизнес-показателей (находки по критичности и статусу, открытые нарушения сроков, очередь задач). Считает только backend. Минимум 10 | целое ≥ 10 | `60` | backend |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | Адрес коллектора трейсов. Пусто — экспорт выключен, но спаны создаются и контекст переносится. Схема решает транспорт: `http://` — без TLS, `https://` — с TLS. Адрес без схемы роняет старт | URL | `""` | все |
| `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` | То же, приоритетнее базовой переменной | URL | `""` | все |
| `OTEL_TRACES_SAMPLER_ARG` | Доля трейсов, начинаемых здесь. Решение вышестоящего сервиса сохраняется — иначе трейсы получаются с дырами | `0.0`…`1.0` | `1.0` | все |
| `UPDATE_CHECK_ENABLED` | Проверять, вышла ли новая версия, и показывать уведомление | `true` \| `false` | `false` | backend |
| `UPDATE_CHECK_URL` | Адрес источника сведений о версиях. Умолчания нет намеренно | URL | `""` | backend |
| `UPDATE_CHECK_INTERVAL_HOURS` | Период проверки, не чаще раза в час | целое ≥ 1 | `24` | backend |
| `RBAC_POLICY_REFRESH_SECONDS` | Период сверки прав с базой. Политики живут в памяти процесса: без перечита правки с других реплик и мимо API не подхватываются до перезапуска. `0` выключает | целое ≥ 0 | `15` | оба |
| `RESCAN_AUTH_PROBE_SECONDS` | Период пробы: принимает ли сканер перепроверки общий ключ. Без пробы расхождение ключей видно только при первом нажатии кнопки. `0` выключает | целое ≥ 0 | `3600` | backend |

!!! warning "Порт метрик не публикуется наружу"

    Аутентификации у него нет (сбор метрик не носит сессию пользователя), а
    ряды описывают внутреннее состояние: объёмы находок по критичности,
    вердикты сканеров, заблокированные обращения. В Docker Compose порт
    намеренно не пробрасывается на хост, в Kubernetes сбор идёт напрямую с
    пода, а ingress на него не маршрутизирует.

## Платформа плагинов

| Переменная | Назначение | По умолчанию |
|---|---|---|
| `PLUGIN_RUNNER_GLOBAL_LIMIT` | Предел одновременно работающих процессов плагинов | значение из кода |
| `PLUGIN_RUNNER_PER_PLUGIN_LIMIT` | Предел одновременных запусков одного плагина | `4` |
| `PLUGIN_RUNNER_KEEP_WARM_SECONDS` | Сколько держать процесс готовым после работы | значение из кода |
| `WASM_RUNNER_BINARY_PATH` | Путь к исполняемому файлу среды исполнения плагинов | значение из кода |
| `ENRICH_TAGS_RATE_LIMIT_PER_MINUTE` | Предел ручных запусков обогащения находки | значение из кода |
| `PLUGIN_EGRESS_ALLOWLIST` | Узлы, к которым плагинам разрешено обращаться | `""` |
| `PLUGIN_EGRESS_ALLOW_HTTP` | Разрешить плагинам схему `http` | `false` |
| `PLUGIN_EGRESS_ALLOW_LOCAL_DIAL` | Разрешить плагинам обращения к локальным и внутренним адресам | `false` |
| `PLUGIN_CATALOG_ALLOWLIST` | Разрешённые адреса каталогов плагинов | `""` |
| `PLUGIN_CATALOG_ALLOW_HTTP` | Разрешить `http` для каталога | `false` |
| `PLUGIN_CATALOG_ALLOW_LOCAL_DIAL` | Разрешить локальные адреса для каталога | `false` |
| `PLUGIN_OCI_ALLOWLIST` | Разрешённые реестры образов, откуда ставятся плагины | `""` |
| `PLUGIN_OCI_ALLOW_HTTP` | Разрешить `http` для реестра | `false` |
| `PLUGIN_OCI_ALLOW_LOCAL_DIAL` | Разрешить локальные адреса для реестра | `false` |

### Нативные плагины (Tier 2)

Отдельный процесс на плагин, общение по gRPC. Значения по умолчанию подобраны
так, чтобы аварийно завершающийся плагин не перезапускался бесконечно и не
оставался выключенным навсегда.

| Переменная | Назначение | По умолчанию |
|---|---|---|
| `PLUGIN_NATIVE_GLOBAL_LIMIT` | Предел одновременно живущих процессов нативных плагинов | `10` |
| `PLUGIN_NATIVE_MEMORY_LIMIT_MB` | Предел памяти на процесс | `256` |
| `PLUGIN_NATIVE_RPC_TIMEOUT_SECONDS` | Тайм-аут вызова плагина | `15` |
| `PLUGIN_NATIVE_SHUTDOWN_GRACE_SECONDS` | Сколько ждать штатной остановки | `10` |
| `PLUGIN_NATIVE_MAX_CRASH_RESTARTS` | Перезапусков после падения в пределах окна | `10` |
| `PLUGIN_NATIVE_CRASH_WINDOW_SECONDS` | Длина окна подсчёта падений | `3600` |
| `PLUGIN_NATIVE_MAX_RESTARTS_PER_DAY` | Потолок перезапусков за сутки | `50` |
| `PLUGIN_NATIVE_RESTART_BACKOFF_BASE_SECONDS` | Начальная пауза перед перезапуском | `5` |
| `PLUGIN_NATIVE_RESTART_BACKOFF_MAX_SECONDS` | Предельная пауза | `300` |
| `PLUGIN_NATIVE_LEASE_TTL_SECONDS` | Срок аренды процесса — при нескольких репликах плагин держит ровно одна | `30` |
| `PLUGIN_NATIVE_LEASE_RENEWAL_INTERVAL_SECONDS` | Период продления аренды | `5` |
| `PLUGIN_NATIVE_LEASE_RENEWAL_TIMEOUT_SECONDS` | Тайм-аут продления | `5` |
| `PLUGIN_NATIVE_LEASE_CLAIM_GRACE_SECONDS` | Отсрочка перед перехватом чужой аренды | `5` |
| `PLUGIN_NATIVE_LEASE_SELF_FENCE_SECONDS` | Через сколько реплика сама снимает свой процесс, потеряв аренду | `20` |
| `PLUGIN_NATIVE_ROUTE_RATE_LIMIT_DEFAULT_PER_MINUTE` | Частота обращений к маршрутам плагина по умолчанию | `60` |
| `PLUGIN_NATIVE_ROUTE_RATE_LIMIT_MAX_PER_MINUTE` | Потолок, выше которого плагин запросить не может | `600` |
| `PLUGIN_NATIVE_SANDBOX_ENABLED` | Изоляция средствами ОС. Выкатывается двумя шагами: сначала профиль, потом флаг | `false` |

Подробнее о модели исполнения и разрешениях — [Плагины](plugins.md).

## Автономное тестирование на проникновение

Отдельная возможность, выключенная по умолчанию: находки в состояниях
«принятый риск» и «не будет исправлено», доступные извне, передаются во
внешнюю систему автономного тестирования, а её результат возвращается в Hub
новыми находками.

| Переменная | Назначение | По умолчанию |
|---|---|---|
| `FEATURE_PENTAGI_INTEGRATION` | Общий переключатель | `false` |
| `PENTAGI_BASE_URL` | Адрес внешней системы. В промышленной среде обязан быть `https` | `""` |
| `PENTAGI_API_TOKEN` | Токен доступа | `""` |
| `PENTAGI_PROVIDER` | Языковая модель, используемая внешней системой | `""` |
| `PENTAGI_STATUSES` | Состояния находок, которые берутся в работу | `risk_accepted,wont_fix` |
| `PENTAGI_SUBMIT_INTERVAL` | Период постановки новых заданий | `1h` |
| `PENTAGI_POLL_INTERVAL` | Период опроса выполняющихся заданий | `5m` |
| `PENTAGI_MAX_CONCURRENT_FLOWS` | Предел одновременных заданий | `3` |
| `PENTAGI_PER_TICK_SUBMIT_CAP` | Предел новых заданий за один такт | `5` |
| `PENTAGI_COOLDOWN` | Окно, в течение которого одна и та же цель не берётся повторно | `168h` |
| `PENTAGI_DRY_RUN` | Готовить задания, но не отправлять | `false` |
| `PENTAGI_EXTRA_ROE` | Дополнительные правила проведения работ, через `\|` | `""` |
| `PENTAGI_HTTP_TIMEOUT` | Тайм-аут обращений | `30s` |
| `PENTAGI_TLS_INSECURE` | Отключить проверку сертификата. В промышленной среде запрещено — старт прервётся | `false` |
| `PENTAGI_LLM_EXTRACT` | Преобразовывать отчёт в структурированные находки языковой моделью | `true` |
| `PENTAGI_INGEST_WORKERS` | Параллелизм приёма результатов | значение из кода |

!!! warning "Это активное воздействие"

    Возможность запускает автоматизированное тестирование на проникновение
    против ваших же систем. Включайте только с согласованными правилами
    проведения работ и заведомо верным перечнем целей.

## Устаревшие переменные

Читаются только для того, чтобы предупредить оператора записью в журнале.
Расписание очистки задаётся в коде и **этими переменными не управляется**.

| Переменная | Прежнее назначение | Компонент |
|---|---|---|
| `CLEANUP_SCHEDULE` | Расписание очистки отчётов — игнорируется | worker |
| `REFRESH_CLEANUP_SCHEDULE` | Расписание очистки токенов — игнорируется | worker |
| `MATTERMOST_NOTIFICATION_WORKERS` | Очередь уведомлений Mattermost — удалена в 0.33 вместе с каналом в ядре | worker |
| `MAXRU_NOTIFICATION_WORKERS` | То же для MAX | worker |
| `MATTERMOST_ALLOW_LOCAL_DIAL` | SSRF-гард канала Mattermost. Канал ведёт плагин, переменную не читает никто; при старте об этом сообщается | оба |
| `FALLBACK_JIRA_URL`, `FEATURE_JIRA_REVERSE_SYNC`, `JIRA_REVERSE_SYNC_INTERVAL_MINUTES`, `JIRA_REVERSE_SYNC_BATCH_SIZE`, `JIRA_REVERSE_SYNC_WORKERS`, `JIRA_SYNC_WORKERS`, `FEATURE_JIRA_ENGINE_ROUTING`, `FEATURE_JIRA_WEBHOOK` | Встроенная интеграция с Jira — удалена в 0.33, задачи ведут плагины | оба |
| `JIRA_ALLOW_HTTP`, `JIRA_ALLOW_LOCAL_DIAL`, `JIRA_BASE_URL_ALLOWLIST` | Общий SSRF-рычаг. Заменён переменными подсистем (`VCS_*`, `RESCAN_*`, `IAC_SOURCE_*`); при остатке в окружении Hub предупреждает | оба |

## Переменные, без которых сервис не стартует

| Переменная | При каком условии обязательна |
| --- | --- |
| `JWT_SECRET` | Всегда, кроме `APP_ENV=development` |
| `DB_PASSWORD` | Всегда, кроме `APP_ENV=development` |
| `KEYCLOAK_CLIENT_SECRET` | При `AUTH_MODE=SSO` и провайдере `keycloak` вне `development`. Вне `development` значение по умолчанию `change-me` **также** отвергается — нужен собственный секрет |
| `OIDC_<ИМЯ>_CLIENT_ID` и `OIDC_<ИМЯ>_CLIENT_SECRET` | Для каждого провайдера из `SSO_PROVIDERS`, кроме `keycloak` |
| `DUAL_VERIFY_CALLBACK_BASE_URL` | При `FEATURE_DUAL_VERIFY=true` |
| `LOCAL_ADMIN_PASSWORD` | Формально нет, фактически обязательна при `AUTH_MODE=LOCAL` — без неё на чистой базе некому войти |

Неизвестное значение `APP_ENV` или `AUTH_MODE` также прерывает запуск — это
сделано намеренно, чтобы опечатка не ослабляла защиту молча.

### Обязательный `https` в промышленной среде

При `APP_ENV=production` запуск прерывается, если любой из этих адресов задан
и использует `http`:

`KEYCLOAK_URL`, `KEYCLOAK_PUBLIC_URL`, `KEYCLOAK_JWKS_URL`,
`KEYCLOAK_TOKEN_URL`, `KC_JWKS_URL`, `KC_ISSUER`, `DOMAINSCOPE_VERIFY_URL`,
`LLM_BASE_URL`, `PENTAGI_BASE_URL`, а также любой адрес провайдера из
`SSO_PROVIDERS`.

По этим каналам передаются секреты, поэтому исключений нет. Проверка адресов
Keycloak не выполняется при `AUTH_MODE=LOCAL` — там он не используется вовсе.

> В чарте по умолчанию задаётся лишь часть переменных: группы перепроверки,
> ручного пересканирования, маршрутизации Jira, `KC_*`, ограничения частоты и
> другие работают на значениях из кода, пока оператор не пробросит их явно
> через `extraEnv`.
