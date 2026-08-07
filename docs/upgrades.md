# Обновления

## Формат версий

Hub использует единую схему для всех компонентов:

```
X.Y.BUILD+COMMIT
```

Пример: `0.9.20260602093200+a1b2c3d`

| Часть    | Что                                                  |
| -------- | ---------------------------------------------------- |
| `X.Y`    | Major.Minor — общий для всех компонентов             |
| `BUILD`  | UTC timestamp `YYYYMMDDHHMMSS` (когда собрали)       |
| `COMMIT` | Короткий git-hash (для аудита со стороны поставщика) |

DomainScope версионируется независимо.

## Где смотреть текущую версию

```bash
# UI Hub — footer показывает версии frontend + backend; warning при рассинхроне X.Y

# Backend HTTP
curl https://hub.example.com/version
curl https://hub.example.com/api/v1/version
```

Ответ `/version`:

```json
{
  "component": "backend",
  "version": "0.9.20260602093200+a1b2c3d",
  "commit": "a1b2c3d",
  "built_at": "2026-05-24T00:00:00Z"
}
```

Поле `component` — имя компонента (`backend`, `worker`, …), `built_at` — ISO-таймстамп сборки.

## Выбор версии

Образы публикуются с явными тегами вида `X.Y`, а также с тегом `latest`.
**Указывайте явный тег** и в `docker-compose.yml`, и в значениях чарта.
Причины две:

- `latest` не позволяет понять, что именно развёрнуто, и не даёт откатиться
  на предыдущее состояние;
- в Kubernetes под с `latest` не перечитает образ без явного перезапуска и
  политики `imagePullPolicy: Always` — легко получить смесь версий между
  репликами.

!!! warning "Проверьте, что тег есть у всех компонентов"

    Теги публикуются независимо, и **не для каждой версии существует полный
    набор образов**. Прежде чем менять версию, убедитесь, что нужный тег
    доступен для всех компонентов, которые вы разворачиваете: backend,
    worker, frontend, сканер конфигураций, DomainScope, образ песочницы.

    Проверить перечень опубликованных тегов можно так:

    ```bash
    for img in sshub-backend sshub-worker sshub-frontend \
               sshub-iac-scanner domain-scope sshub-sandbox-tools; do
      echo "== $img"
      curl -s "https://hub.docker.com/v2/repositories/dexionius/$img/tags?page_size=20" \
        | grep -o '"name":"[^"]*"'
    done
    ```

    Разворачивайте все компоненты **одной** версией. Интерфейс сравнивает свою
    версию `X.Y` с версией backend и показывает предупреждение при
    расхождении — это признак того, что обновились не все компоненты.

## Перед обновлением — всегда

1. **Резервная копия базы** — см. [Эксплуатация](operations.md).
2. **Проверить наличие тега** у всех компонентов, как описано выше.
3. **Прочитать описание изменений** к новой версии.
4. **Проверить переменные окружения** — новая версия может требовать новых.
5. **Продумать откат**: на какой тег возвращаться. Учтите, что миграции базы
   вперёд применяются автоматически, а обратно — нет.

## Docker Compose

```bash
cd /opt/hub
docker compose pull
docker compose up -d

# Проверка
curl https://hub.example.com/version
```

Backend стартует, прокатывает миграции, потом обслуживает.

## Kubernetes (Helm)

Задайте новый тег в значениях чарта и примените их:

```bash
helm upgrade hub ./charts/hub-platform -n hub -f values.yaml
```

Поды пересоздаются последовательной заменой. Backend при старте применяет
миграции под блокировкой: первая реплика мигрирует, остальные ждут — поэтому
обновление с миграцией занимает больше времени, чем обычная замена реплик.

Если вы всё же используете `latest`, смена тега не произойдёт сама: под не
перечитает образ без `imagePullPolicy: Always` и явного перезапуска.

```bash
kubectl -n hub rollout restart deploy/hub-backend
kubectl -n hub rollout restart deploy/hub-worker
kubectl -n hub rollout restart deploy/hub-frontend
```

## Миграции БД

Hub использует встроенную систему миграций — backend накатывает изменения схемы автоматически при старте.

### Когда применяются

- При старте backend
- Применяется только то, чего нет в `goose_db_version`

### Что важно знать

- **Прямые миграции** — backend стартует, обновляет схему, потом начинает обслуживать
- **Обратной совместимости миграций нет** — нельзя откатить схему на старую версию без рестора БД
- **Длительные миграции** — release notes от поставщика отмечают ETA для тяжёлых миграций
- **Блокирующие** — backend не отвечает на запросы пока миграция идёт

### Если миграция упала

```bash
# Compose
docker compose logs backend | grep -i goose

# K8s
kubectl -n hub logs deploy/hub-backend | grep -i goose

# Состояние
docker compose exec postgres psql -U securityhub securityhub -c \
  "SELECT * FROM goose_db_version ORDER BY version_id DESC LIMIT 5;"
```

Если миграция упала — обычно goose откатывает транзакцию. Перезапустите backend. Если повторно падает — соберите логи и обратитесь к поставщику. **Не правьте схему руками.**

## Rollback

### Compose

```bash
# Остановить
docker compose down

# Восстановить БД из бэкапа (если миграции уже прокатились)
gunzip -c /backup/hub-pre-upgrade.sql.gz | docker compose exec -T postgres psql -U securityhub securityhub

# Откатиться на предыдущий образ (попросите у поставщика конкретный тэг)
# В .env: HUB_IMAGE_TAG=0.9.PREVIOUS
docker compose up -d
```

### Kubernetes

```bash
# Helm revision history
helm history hub -n hub

# Откат на предыдущую ревизию
helm rollback hub <revision> -n hub

# Если БД продвинулась — restore + redeploy
kubectl -n hub scale deploy --all --replicas=0
# restore from PV snapshot / pgdump
helm rollback hub <revision> -n hub
kubectl -n hub scale deploy --all --replicas=2
```

## DomainScope обновление

DomainScope обновляется независимо от Hub:

```bash
cd /opt/domainscope
docker compose pull
docker compose up -d
```

Совместимость API между Hub и DomainScope: оба сервиса используют публичные REST эндпоинты Hub (`/api/v1/products/<id>/reports` и `/api/v1/projects/<id>/scope/proposals`). При major-bump поставщик отмечает в release notes изменения контракта, если они есть.

## Frontend и backend совместимость

Hub-frontend завязан на minor-версию backend. В footer UI отображается:

```
v0.9.20260602+a1b (frontend)  /  v0.9.20260601+x9y (backend)
```

При расхождении minor — warning в UI. При major — приложение может вести себя некорректно.

В compose/k8s они обновляются вместе (один тэг `:latest`).

## Расписание обновлений

| Окружение           | Частота                                |
| ------------------- | -------------------------------------- |
| Staging / dev       | каждый минор                           |
| Pilot prod          | каждый минор +1 неделя после release   |
| Production stable   | каждый второй минор, или security-only |
| Closed environments | quarterly review + security patches    |

Hot-fix (security CVE) — катите ASAP в любом окружении.

## Major-upgrade (X → X+1)

Major-upgrades содержат breaking changes. Перед накаткой:

1. **Прочитайте migration guide** от поставщика
2. **Тестируйте на staging** — полный цикл upload SARIF, Jira sync, notifications
3. **Запланируйте maintenance window** (минимум 1 час)
4. **Подготовьте rollback-план** (БД snapshot)
5. **Уведомите пользователей** — за 24 часа

Major-upgrade обычно требует:

- Обновить env vars (новые / переименованные)
- Перенастроить интеграции (если поменялся формат конфига)
- Сначала остановить worker, потом обновить backend, потом запустить worker

## Связанные документы

- [Эксплуатация](operations.md) — backup перед обновлением
- [Диагностика](troubleshooting.md) — если что-то пошло не так
