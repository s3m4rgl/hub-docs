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
| `Required environment variable JWT_SECRET is not set`  | Переменная не задана / пустая (проверяется при `APP_ENV=production`) | Задать в `.env` или helm values |
| `dial tcp ...:5432: connect: connection refused`        | БД недоступна                 | Проверить postgres-контейнер, `DB_HOST`                |
| `password authentication failed for user "securityhub"` | Неверный `DB_PASSWORD`        | Сверить с тем, что задано в postgres                   |
| `failed to run migrations` / `apply migrations in ...`  | Миграция не применилась       | См. текст ошибки в той же строке; обычно — расхождение версий backend/БД |
| `timed out waiting for migration advisory lock`         | Блокировку миграций держит другая реплика дольше `MIGRATION_LOCK_WAIT_SECONDS` | Дождаться её миграции или поднять `MIGRATION_LOCK_WAIT_SECONDS` |
| `panic: ...`                                            | Баг                           | Reissue в трекер; приложите stacktrace                 |

### Frontend 502 Bad Gateway

| Что                                      | Проверка                                                    |
| ---------------------------------------- | ----------------------------------------------------------- |
| Backend стартанул?                       | `docker compose ps backend` — `Up`?                         |
| Backend отвечает на 8082?                | `curl http://localhost:8082/version`                        |
| Frontend nginx видит backend?            | Проверить переменную `REACT_APP_API_URL` контейнера frontend — её подставляет entrypoint при старте |
| Reverse-proxy (nginx/traefik) корректен? | `nginx -t`, логи `/var/log/nginx/error.log`                 |

### `frontend X.Y-dev` в подвале UI

Образ собран без version build-args (баг билда на стороне поставщика). Попросите перевыпуск образа.

### Миграции не применяются

```bash
docker compose exec postgres psql -U securityhub securityhub -c \
  "SELECT version_id, tstamp FROM goose_db_version ORDER BY tstamp DESC LIMIT 5;"
```

- Если таблицы нет — goose не запустился. Логи backend → искать `goose`
- Если есть, но новые миграции не накатились — проверьте, что backend запущен из нового образа: миграции лежат в образе в `/app/migrations`; если их там нет, в журнале будет `No migration files found in any directory`
- Если зависло — посмотрите `SELECT * FROM pg_stat_activity WHERE state='active'` — возможно, миграция длинная

### Loading forever в UI после логина

| Причина                                         | Fix                                                                               |
| ----------------------------------------------- | --------------------------------------------------------------------------------- |
| Frontend не может загрузить чанки (вылетел 404) | Проверить, что вся статика в `frontend-dist/` доступна (`curl -I`)                |
| API возвращает 401 на `/api/v1/users/me`        | JWT истёк или подпись не проверяется. Сверьте `JWT_SECRET` между репликами backend |
| CORS error                                      | `ALLOWED_ORIGINS` не включает frontend-domain                                     |

## Auth / Keycloak

### "Login failed" после редиректа из Keycloak

| Признак                                             | Причина                                                                          | Fix                                                                  |
| --------------------------------------------------- | -------------------------------------------------------------------------------- | -------------------------------------------------------------------- |
| URL: `/auth/keycloak/callback?error=invalid_client` | `KEYCLOAK_CLIENT_SECRET` неверный                                                | Сверить в Keycloak → Clients → Credentials                           |
| `404` на token exchange                             | `KEYCLOAK_TOKEN_URL` указан неправильно (или auto-discovery вернул internal URL) | Задать `KEYCLOAK_TOKEN_URL` явно (HTTPS!)                            |
| `parse id_token: ... token signature is invalid`    | `KEYCLOAK_JWKS_URL` устарел или указывает не на тот realm                        | Очистить кэш JWKS (рестарт backend); задать `KEYCLOAK_JWKS_URL` явно |
| `audience mismatch`                                 | В `aud` (или `azp`) id_token нет идентификатора клиента `KEYCLOAK_CLIENT_ID`      | Настроить Audience mapper в Keycloak или исправить `KEYCLOAK_CLIENT_ID` |

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

## Учёт задач

С 0.33 задачи ведут плагины-провайдеры; встроенной интеграции Jira нет, а
значит нет и её переменных и очередей.

### Кнопка заведения неактивна

- проект не привязан к провайдеру — привяжите в настройках проекта;
- у провайдера нет ни одной цели заведения;
- плагин **установлен, но не включён**: установка сама по себе его не
  запускает;
- плагин выключен администратором или отозван — отозванный плагин
  провайдером не считается.

Проверить, что видит Hub:

```bash
curl -H "Authorization: Bearer $TOKEN" https://hub.example.com/api/v1/ticket-providers
curl -H "Authorization: Bearer $TOKEN" https://hub.example.com/api/v1/projects/<id>/ticket-targets
```

### Заведение отвечает `401` или `403`

- Jira Cloud: пароль — это **API-токен**, не пароль учётной записи
  (`auth_method: basic`, поля `email` и `api_token`);
- Jira Data Center: истёк персональный токен (`auth_method:
  personal_access_token`);
- у учётной записи нет права создавать задачи в целевом проекте;
- проверить вручную: `curl -u <email>:<token> <jira>/rest/api/2/myself`.

Постоянный отказ такого рода завершает задание с объяснением, а не остаётся в
очереди навсегда.

### Заведение отклоняется из-за `base_url`

В `base_url` дописан путь API. Плагин добавляет `/rest/api/2/issue` сам,
поэтому адрес с `/rest/api` он отклоняет с ошибкой `base_url должен быть БЕЗ
пути API: /rest/api/2/issue дописывает плагин`. Укажите только базовый адрес
Jira.

### Переход по статусу не выполняется

Целевой статус недоступен из того, в котором задача оказалась после создания.
Посмотрите схему процесса в самом трекере: какие переходы разрешены. Hub
передаёт имя статуса, а сопоставление с переходом делает плагин.

### Закрытие задачи не закрывает находку

```bash
docker compose logs backend worker | grep ticket_status_poll
```

Задания провайдеров задач выполняет backend: в worker среды исполнения
плагинов нет, и попавшее туда задание завершается ошибкой
`платформа плагинов не сконфигурирована`, после чего River его повторяет.

| Симптом | Что проверить |
| --- | --- |
| Вебхук не приходит | Трекер не дотягивается до Hub. В закрытом контуре работает только опрос статусов |
| Вебхук приходит, но отвергается | Секрет в адресе не тот — перевыпустите его (`POST /api/v1/projects/<id>/ticket-webhook/rotate`) и обновите настройку в трекере |
| Опрос идёт, статус не терминальный | Терминальность решает плагин по схеме вашей системы, а не список имён в Hub |
| Опрос отчитывается об успехе, но ничего не закрывает | Не заполнены учётные данные в конфигурации плагина **для этого проекта**. С 0.33 это явный отказ провайдера (`no_access`, без повторов); прежде пустой ответ читался ядром как «проверено, закрывать нечего», и сводка показывала `failed=0` |
| В журнале `batch_capped` | Находок больше, чем `TICKET_STATUS_POLL_BATCH_SIZE` за прогон — уменьшите интервал или увеличьте потолок |
| Задача удалена в трекере | Находка намеренно не закрывается: потеря задачи ничего не говорит об уязвимости |

### После обновления на 0.33 перестали работать интеграции

- удалены `FEATURE_JIRA_REVERSE_SYNC`, `JIRA_REVERSE_SYNC_*`,
  `JIRA_SYNC_WORKERS`, `FALLBACK_JIRA_URL`, `FEATURE_JIRA_ENGINE_ROUTING`,
  `FEATURE_JIRA_WEBHOOK` — задачи ведут плагины;
- `JIRA_ALLOW_HTTP` и `JIRA_ALLOW_LOCAL_DIAL` больше не действуют на чужие
  подсистемы: у каждой свои `VCS_*`, `RESCAN_*`, `IAC_SOURCE_*`. Hub пишет об
  этом предупреждение один раз на подсистему;
- настройки из `projects.jira_config` переносятся запросом
  `POST /api/v1/admin/jira-migration/apply` — см.
  [Учёт задач](integration-jira.md#переход-со-встроенной-интеграции-jira).

### Автоматически закрылось лишнее

Сначала проверьте, что все условия действительно были выполнены — без
любого из них закрытие не должно происходить:

1. `FEATURE_AUTO_VERIFY_FIXES=true` — на всей установке;
2. признак `auto_verify_fixes_enabled` — в настройках проекта;
3. режим проверки проекта `auto_verify_mode=point_verify` — в режиме `diff`
   Hub не закрывает ничего;
4. `verify_fixes=true` — в параметрах конкретной загрузки.

Закрытие в режиме `point_verify` происходит только по вердикту «отсутствует»
от точечной проверки DomainScope (`/api/v1/probe`), а не по отсутствию
находки в отчёте.

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

## Уведомления

### Уведомления не приходят

```bash
# Глубина очереди > 0? Worker крутит?

# 2. Логи
docker compose logs backend worker | grep -i notif

# 3. dry-run проверка
# В env: NOTIFICATIONS_DRY_RUN=true → перезапустить backend и worker
# Логи должны показать сообщение, которое было бы отправлено
```

| Симптом | Что проверить |
| --- | --- |
| Ни по одному каналу ничего нет | Плагин канала не установлен: с 0.33 каналов в ядре нет |
| В каталоге плагин есть, установка недоступна | Источнику не разрешено исполнение нативных плагинов |
| В журнале `notification channel plugin disabled — findings not delivered` | Плагин установлен, но выключен администратором |
| В журнале `канал включён, но обязательные поля не заполнены — уведомления не доставляются` | Нет `chat_id`, `recipients` или секрета канала |
| События идут, доставки нет | Критичность ниже порога или канал не подписан на этот тип события |
| Очередь растёт, не уменьшается | Проверьте, что запущены backend и worker (`docker compose ps`): доставку через канальные плагины выполняет только backend |
| Telegram: 400 Bad Request | Формат идентификатора чата: для каналов `-100…`, для групп — отрицательный |
| Telegram: chat not found | Бот не добавлен в чат |
| Mattermost: доставка отклонена | Не заполнен `mattermost_base_url` в настройках установки плагина |
| Mattermost: 400 / 404 | Webhook удалён в Mattermost — пересоздайте |
| Mattermost и MAX молчат после обновления | Настройки не перенесены — см. [Обновление на 0.33](upgrades.md#обновление-на-033) |

## SARIF Upload

### Сканер работает, но находки НЕ появляются в Hub (`404 page not found` при upload)

Симптом в логах DomainScope (или другого сканера):

```
zap sarif upload failed — находки НЕ доставлены в Hub  error="404 — маршрут или продукт не найден ..."
```

Сканер находит уязвимости, но загрузка SARIF возвращает **404**. `page not found` — это
ответ Hub на **несматченный маршрут**, почти всегда это misconfig, а НЕ отсутствие ресурса:

1. **`*_SARIF_API_ENDPOINT` содержит `/api/v1`.** Эндпоинт должен быть **корнем Hub**
   (`https://hub.example.com`), клиент сам дописывает `/api/v1/products/<id>/reports`.
   С хвостом `/api/v1` путь удваивается → 404. *(Клиент DomainScope **НЕ** стрипает
   хвостовой `/api/v1` — он строит URL через `url.JoinPath(baseURL, "/api/v1/products/...")`,
   поэтому эндпоинт обязан быть корнем без `/api/v1`. Любой хвост `/api/v1` в эндпоинте
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

`413` отвечает и сам Hub — если файл больше `MAX_UPLOAD_SIZE_MB` (по
умолчанию 500 МБ) или больше предела разбора формата (SARIF — 50 МиБ, без
явного `format` действует наибольший из пределов); тогда в теле ответа — ключ
`report.file_too_large`, `report.file_too_large_for_format` или
`report.file_too_large_for_parsing`. Если тела Hub в ответе нет, ограничивает
обратный прокси:

```nginx
# nginx
client_max_body_size 200M;
```

```yaml
# K8s ingress
nginx.ingress.kubernetes.io/proxy-body-size: 200m
```

### Из большого отчёта загрузились не все находки

SARIF превысил один из пределов разбора (см. [Загрузка отчётов внешних сканеров](integration-sarif.md)):
не больше 100 runs в отчёте, 100 000 results в одном run и 1 000 000 results
на отчёт. Лишнее отбрасывается с предупреждением в журнале — `sarif: runs truncated`
или `sarif: results truncated`.

- Разбейте отчёт на несколько (несколько runs в разных файлах)
- Уменьшите количество results (фильтр на стороне сканера)

### Findings не дедуплицируются

Между прогонами сканера `rule_id` и местоположение (`location.physicalLocation.artifactLocation.uri`, номера строк и первые 100 символов фрагмента кода) должны быть стабильны. Если сканер генерирует уникальные идентификаторы каждый раз — находки будут размножаться. Правила тождества — в [Жизненном цикле находки](findings.md#дедупликация).

Проверка:

```sql
SELECT rule_id, file_path, COUNT(*)
FROM findings
WHERE product_id = '<uuid>' AND deleted_at IS NULL
GROUP BY rule_id, file_path
HAVING COUNT(*) > 5
ORDER BY COUNT(*) DESC;
```

### Severity всегда LOW или INFO

Сканер не выставляет `properties.severity` / `level` и у правила нет уровня по умолчанию — тогда критичность становится `LOW`; уровень `note` и нераспознанные значения дают `INFO`. Выставьте поле в SARIF на стороне сканера (см. [Загрузка отчётов внешних сканеров](integration-sarif.md)).

### `500 Internal Server Error — Failed to save file` («Не удалось сохранить файл») при upload

В отличие от 404 (misconfig эндпоинт), 500 «Failed to save file» означает, что
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
[ручную установку](deploy-k3s-manual.md), шаг «Настройка DNS».

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
# после готовности backend сообщения «hub scope unavailable» должны прекратиться
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

## Сканеры периметра (OpenVAS, OWASP ZAP)

### ZAP в `CrashLoopBackOff`, в логе «The home path is not writable»

```bash
kubectl -n <ns> logs sts/<release>-zap | head -20
```

```
Available memory: 7932 MB
Using JVM args: -Xmx1983m
The home path is not writable: /home/zap/.ZAP/
```

Причина — права на томе. ZAP работает под uid/gid `1000`, том монтируется в его
домашний каталог, и без `fsGroup` kubelet владельца тома не меняет: у обычного
CSI свежий том приезжает как `root:root 0755`.

Чарт из поставки задаёт `podSecurityContext` с `fsGroup: 1000`. Проверьте, что
он доехал до пода:

```bash
kubectl -n <ns> get sts <release>-zap -o jsonpath='{.spec.template.spec.securityContext}'
# ожидается: {"fsGroup":1000,"runAsGroup":1000,"runAsNonRoot":true,"runAsUser":1000}
```

Если пусто — вы либо на чарте до этой правки, либо переопределили
`podSecurityContext` своими значениями без `fsGroup`, либо контекст вычищает
политика кластера (PodSecurityPolicy, Kyverno, Gatekeeper).

!!! note "На k3s это не воспроизводится"

    `local-path` provisioner создаёт каталог с правами `0777`, поэтому на стенде
    разработки ZAP стартует и без `fsGroup`. Ошибка приходит только от клиентов
    на обычном CSI — и проверка «у нас на k3s работает» её не ловит.

**Уже сломанный том** правами пода не чинится задним числом: `fsGroup` меняет
владельца при монтировании, но уже созданные внутри файлы root'а остаются. Если
том непустой и поломанный, проще удалить PVC и дать чарту создать его заново
(сессии и политики ZAP восстановятся, накопленная история сканов — нет).

### ZAP стартует долго и его убивает liveness

Холодный старт с докачкой дополнений занимает минуты. В чарте для этого есть
`startupProbe` (по умолчанию до 10 минут) — пока она не прошла, liveness не
считается. Если под всё равно перезапускается, поднимите
`startupProbe.failureThreshold` либо выключите докачку целиком:
`checkForUpdates: false` (обязательно для закрытого контура, заодно делает
результаты сканов воспроизводимыми).

### Сканер не выходит наружу через WireGuard

```bash
kubectl -n <ns> logs sts/<release>-zap -c wg-setup
```

| Симптом в логе | Что значит |
| --- | --- |
| `FATAL: не удалось создать интерфейс wireguard` | Модуля `wireguard` нет на ноде. Ядро 5.6+ содержит его штатно; на старых нужен `wireguard-dkms`. Проверка на ноде: `modprobe wireguard && lsmod \| grep wireguard` |
| `FATAL: no default gateway in pod netns` | Сеть пода поднялась не полностью — смотрите CNI |
| `FATAL: не удалось разрезолвить endpoint` | В `wireguard.serverEndpoint` имя, которое не резолвится изнутри кластера |
| Туннель поднят, но цели в приватных сетях недоступны | RFC1918 по умолчанию идут мимо туннеля. Цели, достижимые только со стороны WG-сервера, перечислите в `wireguard.routeViaTunnel` |
| Туннель поднят, но WG-сервер недоступен по внутреннему адресу | Подсеть туннеля должна быть в `wireguard.tunnelCidr` — иначе она попадает под общее правило «`10.0.0.0/8` → шлюз» |

Init-контейнер идемпотентен: при рестарте он пересоздаёт `wg0` и переставляет
маршруты через `ip route replace`, поэтому повторный запуск не ломает
настроенное.

## LLM / Sandbox

### LLM-jobs не выполняются

- Backend имеет `LLM_WORKERS=0`? (должен)
- Worker имеет `LLM_WORKERS > 0`? (должен)
- `LLM_API_KEY` и `LLM_BASE_URL` заданы в worker?
- Проверьте логи worker по записям про очередь `llm_analysis` — глубина > 0, есть failed jobs?

### `429 Too Many Requests`

Превышен rate limit провайдера. Уменьшите `LLM_WORKERS` (например, 3 → 1) или попросите квоту у провайдера.

### Sandbox не запускается

В журнале worker:

```
Sandbox verification failed, returning uncertain verdict
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

| Признак | Fix |
| --- | --- |
| `subfinder failed` с ошибкой | источники subfinder недоступны из сети — проверьте исходящий HTTPS |
| В `subfinder started` значение `enumerating` меньше `domains` | это расписание, а не сбой: каждая зона перечисляется не чаще раза в 24 часа и не больше 25 зон за цикл, остальные берут поддомены из БД (`reused_from_db`) |
| Много строк `ip resolve failed` (уровень debug) | для найденных subfinder имён это норма; если не резолвится всё — проверьте `/etc/resolv.conf` или задайте `SCANNER_DNS_SERVER` |
| `wildcard DNS detected for zone` | у зоны wildcard-запись: поддомены, резолвящиеся только в эти адреса, отбрасываются |
| `seed domain blocked by hub scope` | при подключённом Hub исходная зона не покрыта включением периметра или попала под исключение |
| Цикл идёт, но доменов в БД нет | проверьте, что задан хотя бы один источник: `DOMAINSCOPE_DOMAINS`, включения периметра Hub или зоны NetBox DNS |

### Nuclei не сканирует

| Признак                            | Fix                                                                   |
| ---------------------------------- | --------------------------------------------------------------------- |
| `nuclei templates not found at ...` | `nuclei-templates-init` контейнер должен отработать. Проверьте volume |
| `DOMAINSCOPE_NUCLEI_ENABLED=false` | Поставьте `true` и перезапустите                                      |
| Cycle не стартует                  | Нет целей: они строятся из активных находок портскана с протоколом `http`/`https` |

### OpenVAS не подключается

- `DOMAINSCOPE_OPENVAS_HOST` доступен из DomainScope контейнера? `docker compose exec domain-scope nc -zv $DOMAINSCOPE_OPENVAS_HOST 9390` (порт gsad, `DOMAINSCOPE_OPENVAS_PORT`, по умолчанию 9390)
- Креды правильные? Логин в OpenVAS UI работает?
- Feed init завершился? OpenVAS первые 10-30 минут после старта качает CVE-фиды и не отвечает

### SARIF не приходит в Hub

```bash
docker compose -f /opt/domainscope/docker/docker-compose.yml logs domain-scope | grep -i sarif
```

| Признак                       | Fix                                                                     |
| ----------------------------- | ----------------------------------------------------------------------- |
| `401 Unauthorized`            | `DOMAINSCOPE_SARIF_API_TOKEN` неверный или истёк                        |
| `403 Forbidden`               | У Service Account нет права `upload_report` на продукт или на его проект |
| `connection refused`          | `DOMAINSCOPE_SARIF_API_ENDPOINT` недоступен. Проверьте сетевую связность |
| Cycle вообще не делает upload | `DOMAINSCOPE_SARIF_AUTO_UPLOAD=true`?                                   |

### Scope proposals не появляются

```bash
# Hub side
docker compose exec postgres psql -U securityhub -d securityhub -c \
  "SELECT created_at, status, proposed_action, scanner_name, proposed_value FROM scan_scope_proposals
   WHERE created_at > NOW() - INTERVAL '24 hours' ORDER BY created_at DESC LIMIT 20;"
```

Если пусто — DomainScope не шлёт. Логи:

```bash
docker compose -f /opt/domainscope/docker/docker-compose.yml logs domain-scope | grep proposal
```

При успешной отправке в логе есть строка `subdomain proposals submitted` с числом
предложений, при ошибке — `subdomain proposals: failed to post`.

Штатные причины, по которым предложений нет и это нормально:

- `DOMAINSCOPE_HUB_ENABLED` не выставлен — клиент Hub не создан, в логе нет строки `hub scope api enabled`;
- предлагать нечего — все найденные поддомены уже имеют точную запись включения, а у Hub на каждое значение со своей активной записью предложение не создаётся;
- кандидаты отсечены на стороне сканера: поддомен попадает под **активное** исключение периметра или помечен `ignore-scan` в NetBox (в логе уровня debug — `domain excluded by hub scope`);
- зона ещё не перечислялась: за цикл перечисляется не больше 25 зон и каждая — не чаще раза в сутки, поэтому новая зона в периметре даёт предложения не сразу (`subfinder started` показывает `enumerating` и `reused_from_db`).

!!! warning "Известное ограничение: корневые зоны из TLS-сертификатов при подключённом Hub не предлагаются"
    Новая корневая зона, найденная в сертификате, проверяется сопоставлением
    периметра Hub и, не будучи покрыта включением, отсекается до отправки
    (в логе уровня debug — `san candidate excluded by hub scope`). Отсутствие
    таких предложений — не сбой связки. Исправление отслеживается в
    [DomainScope#4](https://gitlab.com/hub_infosec/DomainScope/-/work_items/4).

Если же в логе есть `403` на `POST .../scope/proposals` — у сервисной учётной записи нет права `upload_report` на проект. Подробнее: [Связка DomainScope и Hub](perimeter-integration.md).

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
SARIF_PROCESSING_WORKERS=8
EMAIL_NOTIFICATION_WORKERS=10
```

## Сбор диагностики для bug report

При issue в трекер прикладывайте:

```bash
# 1. Версии
curl https://hub.example.com/version
# DomainScope — версия в стартовой записи журнала:
docker compose logs domain-scope | grep "domain-scope starting"

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

- [Эксплуатация](operations.md) — backup, мониторинг
- [Обновления](upgrades.md) — rollback при неудачном обновлении


## Если это не неисправность

Часть наблюдаемого поведения — не сбой, а известное свойство: сообщение о
ненайденном на диске файле отчёта при каждой загрузке, отсутствие счётчиков в
ответе на загрузку, схлопывание находок без CVE на одном порту. Прежде чем
искать причину, сверьтесь с [Известными ограничениями](limitations.md).
