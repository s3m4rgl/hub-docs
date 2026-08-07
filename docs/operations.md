# Эксплуатация

## Backup

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

### Health endpoints

| Сервис      | URL                   | Что                              |
| ----------- | --------------------- | -------------------------------- |
| Hub backend | `GET /version`        | Версия + готовность              |
| Hub backend | `GET /api/v1/version` | То же                            |
| DomainScope | `GET /health`         | Liveness                         |
| DomainScope | `GET /ready`          | Readiness (БД + cycle freshness) |

Используйте эти endpoints в внешнем monitoring (Zabbix, Nagios, Uptime Kuma, blackbox-exporter и т.п.).

### Логи и Grafana

Состояние и сбои отслеживайте через:

- `docker compose logs -f backend worker` — оперативный лог
- Дашборды Grafana (контейнер `grafana` доступен на порту 8084) — visualization из БД

### Что мониторить

| Что | Где смотреть |
|-----|--------------|
| Backend жив | `curl /version` периодически |
| БД доступна | backend-логи без ошибок connection |
| Failed jobs | `docker compose logs worker | grep -i "failed\|error"` |
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

Worker `cleanup_worker` чистит старые reports по расписанию `CLEANUP_SCHEDULE` (default: `0 2 * * *`):

- `completed` reports старше `CLEANUP_RETENTION_COMPLETED_DAYS=7` → удалить файл и запись
- `failed` reports старше `CLEANUP_RETENTION_FAILED_DAYS=30`
- `pending` — не чистятся (`0`)

Конфиг — см. [`configuration.md`](configuration.md) → `CLEANUP_*`.

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
- Hub: следите за релизами, обновляйте раз в 2-4 недели (см. [`upgrades.md`](upgrades.md))

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
5. **Verify**: smoke-tests (login, list findings, upload SARIF)
6. **Resume traffic**: переключайте обратно
7. **Postmortem**: что пошло не так, как избежать впредь

RTO целевой: < 4 часа. RPO: < 24 часа (с ежедневными бэкапами).

## Связанные документы

- [`upgrades.md`](upgrades.md) — обновления и миграции
- [`troubleshooting.md`](troubleshooting.md) — типовые проблемы


Что именно переживает отказ, а что нет, и какие резервные копии обязательны —
[Отказоустойчивость](ha.md). Расчёт мощности и настройки, влияющие на
потребление, — [Расчёт ресурсов](sizing.md).
