# Эксплуатация

## Резервное копирование

### Что бэкапить

| Что                              | Где                    | Критичность                        |
| -------------------------------- | ---------------------- | ---------------------------------- |
| PostgreSQL (Hub)                 | volume `postgres_data` | CRITICAL — основная БД             |
| PostgreSQL (DomainScope)         | свой volume            | HIGH — теряем discovery            |
| `./storage/` (артефакты, отчёты) | bind mount             | MEDIUM — можно перезалить          |
| Helm secrets / Vault             | внешнее хранилище      | CRITICAL — без них Hub не стартует |
| Конфиги (`.env`, `values.yaml`)  | git                    | LOW — версионируются               |

### Ежедневный бэкап БД

#### Docker Compose

```bash
# /etc/cron.daily/hub-backup.sh
#!/bin/bash
set -euo pipefail

BACKUP_DIR=/backup/hub
DATE=$(date +%Y%m%d-%H%M)

mkdir -p "$BACKUP_DIR"

# Hub
docker exec sshub-postgres pg_dump -U securityhub securityhub | \
  gzip > "$BACKUP_DIR/hub-$DATE.sql.gz"

# DomainScope (если рядом)
docker exec ds-postgres pg_dump -U domainscope domainscope | \
  gzip > "$BACKUP_DIR/ds-$DATE.sql.gz"

# Storage (отчёты)
tar -czf "$BACKUP_DIR/storage-$DATE.tar.gz" /opt/hub/storage/

# Очистка старых (>30 дней)
find "$BACKUP_DIR" -name "*.gz" -mtime +30 -delete
```

```bash
sudo chmod +x /etc/cron.daily/hub-backup.sh
```

#### Kubernetes

Используйте CronJob с pgbackrest / Velero / k8s-snapshot:

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: hub-postgres-backup
spec:
  schedule: "0 2 * * *"
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: pg-dump
            image: postgres:15
            envFrom:
              - secretRef: { name: hub-postgres-credentials }
            command:
              - /bin/sh
              - -c
              - |
                pg_dump -h hub-postgres -U $POSTGRES_USER $POSTGRES_DB | gzip > /backup/hub-$(date +%F).sql.gz
            volumeMounts:
              - name: backup, mountPath: /backup
          volumes:
            - name: backup
              persistentVolumeClaim: { claimName: backup-pvc }
          restartPolicy: OnFailure
```

### Off-site

Бэкапы только локально на той же VM — не бэкапы. Регулярно перекладывайте:

- S3 (s3cmd, rclone)
- Yandex Object Storage
- Защищённый bastion-host

### Восстановление

```bash
# Создать пустую БД (если ещё нет)
docker exec sshub-postgres psql -U securityhub -c 'CREATE DATABASE securityhub;'

# Залить
gunzip -c hub-backup-20260601.sql.gz | docker exec -i sshub-postgres psql -U securityhub securityhub

# Перезапустить backend (миграции должны быть прокатанные)
docker compose restart backend worker
```

> **Тестируйте восстановление раз в квартал**. Бэкап без отрепетированного restore — не бэкап.

## Мониторинг

### Адреса проверки состояния

| Сервис | Адрес | Что показывает |
| --- | --- | --- |
| Backend Hub | `GET /health` | Живость процесса |
| Backend Hub | `GET /version` | Версия компонента |
| Backend Hub | `GET /api/v1/version` | То же, внутри пространства API |
| DomainScope | `GET /health` | Живость |
| DomainScope | `GET /ready` | Готовность: база доступна, циклы не устарели |
| DomainScope | `GET /healthz` | Живость приёмника команд перепроверки |

Эти адреса подходят для внешнего наблюдения — Zabbix, Uptime Kuma,
blackbox-exporter и любых аналогов.

!!! note "У worker нет собственного адреса проверки"

    Worker не обслуживает HTTP. Его состояние оценивается косвенно — по тому,
    разбирается ли очередь задач (см. ниже), и по журналу процесса. Живой
    процесс с неразбираемой очередью выглядит здоровым для оркестратора, но
    таковым не является.

### Очередь задач — главный показатель

Самый содержательный признак того, что обработка идёт, — состояние очереди:

| Запрос | Что даёт |
| --- | --- |
| `GET /api/v1/jobs/stats` | Сводка по состояниям задач |
| `GET /api/v1/jobs` | Перечень задач с фильтрами |
| `POST /api/v1/jobs/<id>/retry` | Повторить сбойную задачу |

Растущее число задач в ожидании при неизменном числе выполненных означает,
что worker не работает или не справляется. Задачи, исчерпавшие попытки,
остаются в состоянии ошибки — их видно и в интерфейсе, и через этот API.

### Журналы

```bash
docker compose logs -f backend worker
```

Уровень подробности задаётся `LOG_LEVEL` (`debug`, `info`, `warn`, `error`) и
меняется независимо от `APP_ENV` — подробный вывод можно включить в
промышленной среде для диагностики, не меняя формат записей.

### Что наблюдать

| Что | Как проверять |
| --- | --- |
| Backend жив | Периодический запрос `/health` |
| Очередь разбирается | `GET /api/v1/jobs/stats`, сравнение с предыдущим значением |
| База доступна | Журнал backend без ошибок соединения |
| Место на томе отчётов | Переполнение прекращает приём новых отчётов |
| Место на томе базы | Переполнение останавливает запись |
| Сроки устранения | `GET /api/v1/sla/violations` и сводки на дашборде |
| Свободное место на диске | стандартный node_exporter / системный мониторинг |
| Размер БД | `SELECT pg_size_pretty(pg_database_size('securityhub'));` |

## Логирование

### Где логи

- **Compose**: `docker compose logs <service>`, ротация через docker-daemon (`/etc/docker/daemon.json` → `log-opts`)
- **K8s**: stdout pods → cluster logging (Loki, Elastic, etc.)

### Формат

В `APP_ENV=production` — JSON (zap), легко парсится:

```json
{
  "level": "info",
  "ts": "2026-06-02T12:34:56.789Z",
  "msg": "report uploaded",
  "report_id": "rpt-...",
  "engine": "gosec",
  "findings_count": 47,
  "user_id": "user-...",
  "trace_id": "abc..."
}
```

### Полезные grep'ы

```bash
# Все upload-операции
docker compose logs backend | jq -r 'select(.msg=="report uploaded")'

# Ошибки за последний час
docker compose logs --since 1h backend | jq 'select(.level=="error")'

# Кто логинился сегодня
docker compose logs backend | jq -r 'select(.msg=="user login") | "\(.ts) \(.email)"'
```

### Логи DomainScope

```bash
# Compose
docker compose -f docker/docker-compose.yml logs -f domain-scope

# systemd
sudo journalctl -u domain-scope -f

# По циклам
docker compose logs domain-scope | grep "cycle"
```

### Retention

- Docker default: бесконечно (заполнит диск). Настройте:
  ```json
  {
    "log-driver": "json-file",
    "log-opts": { "max-size": "100m", "max-file": "5" }
  }
  ```
- Логи в `./logs/` — ротируйте через `logrotate`
- K8s — `kubelet log-rotation` (включён по умолчанию, проверьте `/etc/kubernetes/`)

## Очистка старых данных

### Reports (storage)

Очистка запускается **ежечасно**. Расписание задано в коде и переменными
окружения не управляется: `CLEANUP_SCHEDULE` — устаревшая переменная, она
только вызывает предупреждение в журнале, если задана.

Что удаляется:

| Что | Переменная | По умолчанию |
| --- | --- | --- |
| Обработанные отчёты | `CLEANUP_RETENTION_COMPLETED_DAYS` | старше 7 суток |
| Отчёты с ошибкой разбора | `CLEANUP_RETENTION_FAILED_DAYS` | старше 30 суток |
| Необработанные отчёты | `CLEANUP_RETENTION_PENDING_DAYS` | `0` — не удаляются |
| Файлы без записи в базе | `CLEANUP_RETENTION_ORPHAN_HOURS` | старше 24 часов |

Удаляются и файл, и запись в базе. Проверить, что именно будет удалено, не
удаляя, можно через `CLEANUP_DRY_RUN=true`.

Конфиг — см. [Конфигурация: обзор и соглашения](configuration.md) → `CLEANUP_*`.

### Refresh tokens

Worker `refresh_token_cleanup` чистит revoked tokens старше `REFRESH_CLEANUP_RETENTION_DAYS=30`.

### Audit log

В Hub нет автоматической очистки audit_logs — растут навсегда. Если БД распухает, добавьте cron:

```sql
DELETE FROM audit_logs WHERE created_at < NOW() - INTERVAL '180 days';
```

(Только после согласования с security/compliance — audit-log может быть обязателен по политике.)

## Безопасность сервера

### Firewall

```bash
# Минимум для production
ufw default deny incoming
ufw allow 22/tcp                    # SSH (или нестандартный порт)
ufw allow 443/tcp                   # HTTPS
ufw allow 80/tcp                    # HTTP → 443
ufw enable
```

Никогда не выставляйте наружу 5432 (PostgreSQL) и 8082 (backend). Только через nginx + auth.

### fail2ban

Добавьте jail для nginx 401/403:

```ini
# /etc/fail2ban/jail.d/nginx-auth.conf
[nginx-auth]
enabled = true
filter = nginx-auth
logpath = /var/log/nginx/access.log
maxretry = 5
findtime = 600
bantime = 3600
```

### Регулярные обновления

- OS: `unattended-upgrades` (Ubuntu/Debian) или `dnf-automatic` (RHEL)
- Docker base-images: пересобирайте раз в месяц с свежим `apk upgrade` / `apt upgrade`
- Hub: следите за релизами, обновляйте раз в 2-4 недели (см. [Обновления](upgrades.md))

## Производительность

### Postgres

Регулярно проверяйте:

```sql
-- Размер таблиц
SELECT relname, pg_size_pretty(pg_total_relation_size(relid))
FROM pg_catalog.pg_statio_user_tables
ORDER BY pg_total_relation_size(relid) DESC LIMIT 10;

-- Bloat
SELECT schemaname,tablename,n_dead_tup,n_live_tup FROM pg_stat_user_tables
WHERE n_dead_tup > 1000 ORDER BY n_dead_tup DESC;

-- Vacuum status
SELECT relname, last_vacuum, last_autovacuum FROM pg_stat_user_tables;
```

Если bloat > 30% — `VACUUM FULL <table>` в окно maintenance.

### Индексы

Hub при миграциях создаёт нужные индексы автоматически. Если кастомные запросы тормозят:

```sql
EXPLAIN ANALYZE SELECT ... FROM findings WHERE ...;
-- посмотрите Seq Scan vs Index Scan
```

## Disaster Recovery план

Минимальный набор шагов:

1. **Identify**: какой компонент упал (backend/DB/worker/etc.)
2. **Stabilize**: переключите на staging если есть; иначе announce maintenance
3. **Restore data**: из последнего бэкапа (см. выше)
4. **Restore service**: redeploy с известно-рабочей версии
5. **Verify**: smoke-tests (login, list находки, upload SARIF)
6. **Resume traffic**: переключайте обратно
7. **Postmortem**: что пошло не так, как избежать впредь

RTO целевой: < 4 часа. RPO: < 24 часа (с ежедневными бэкапами).

## Связанные документы

- [Обновления](upgrades.md) — обновления и миграции
- [Диагностика](troubleshooting.md) — типовые проблемы


Что именно переживает отказ, а что нет, и какие резервные копии обязательны —
[Отказоустойчивость](ha.md). Расчёт мощности и настройки, влияющие на
потребление, — [Расчёт ресурсов](sizing.md).
