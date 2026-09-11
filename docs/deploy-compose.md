# Развёртывание через Docker Compose

Самый быстрый путь к работающему Hub. Подходит для пилотов, dev-стендов и продакшен-инсталляций без Kubernetes.

> Поставка — готовые Docker-образы из публичного registry. Сборка из исходников не предполагается.

## Предусловия

- Виртуалка/железо по требованиям из [Требования](prerequisites.md)
- Docker Engine 24+ и Docker Compose v2.20+ (`docker compose version`)
- 30+ ГБ свободного диска
- Доступ к публичному Docker registry (или внутреннему зеркалу)

## 1. Получение артефактов поставки

В пакете поставки админу выдаются:

| Файл                 | Назначение                             |
| -------------------- | -------------------------------------- |
| `docker-compose.yml` | Compose-стек со ссылками на образы Hub |
| `.env.example`       | Шаблон конфигурации                    |

Положите файлы в любую рабочую директорию, например `/opt/hub/`:

```bash
sudo mkdir -p /opt/hub
sudo cp docker-compose.yml .env.example /opt/hub/
cd /opt/hub
```

## 2. Конфигурация `.env`

```bash
cp .env.example .env
```

Минимальный набор для запуска (отредактируйте `.env`):

```ini
# === Database ===
DB_PASSWORD=<strong-random-password-32-chars>

# === JWT ===
JWT_SECRET=<openssl rand -hex 32>

# === Frontend / API URLs ===
FRONTEND_URL=https://hub.example.com
REACT_APP_API_URL=https://hub.example.com
ALLOWED_ORIGINS=https://hub.example.com

# === Auth mode ===
AUTH_MODE=LOCAL
LOCAL_ADMIN_PASSWORD=<strong-admin-password>

# === App env ===
APP_ENV=production
```

> **WARNING:** дефолтные значения `JWT_SECRET` и `LOCAL_ADMIN_PASSWORD` из шаблона **не использовать в продакшене** — задайте свои случайные значения.

Полный справочник переменных: [Конфигурация: обзор и соглашения](configuration.md).

## 3. Pull образов и запуск

```bash
docker compose pull
docker compose up -d
# bootstrap создаёт администратора/токен сканера, затем backend перечитывает
# роль admin (casbin reload) — этот шаг обязателен:
docker compose restart backend
```

Версия образов задаётся переменными `HUB_VERSION` (backend, worker, frontend) и `DS_VERSION` (DomainScope) в файле `.env`. По умолчанию — `HUB_VERSION=0.33` и `DS_VERSION=0.32`: это последние опубликованные теги каждого набора образов, и они не совпадают. Компоненты выпускаются независимо, тега `0.33` у `dexionius/domain-scope` не существует, а попытка поставить его даёт `ImagePullBackOff` уже после старта остальных сервисов. Перед сменой версии убедитесь, что нужный тег существует у каждого компонента: см. [Обновления](upgrades.md#выбор-версии).

Стек поднимает (компоненты):

| Сервис        | Назначение                          | Образ (Docker Hub)                        | Порт хоста |
| ------------- | ----------------------------------- | ----------------------------------------- | ---------- |
| `postgres`    | БД Hub (PostgreSQL 15)              | `postgres:15`                             | 5432       |
| `backend`     | REST API                            | `dexionius/sshub-backend:${HUB_VERSION}`  | 8082       |
| `worker`      | Async jobs                          | `dexionius/sshub-worker:${HUB_VERSION}`   | —          |
| `frontend`    | Web UI                              | `dexionius/sshub-frontend:${HUB_VERSION}` | 3000       |
| `bootstrap`   | Одноразовая инициализация (админ/токен) | `python:3.12-slim`                    | —          |
| `ds-postgres` | БД DomainScope (PostgreSQL 16, опц.) | `postgres:16-alpine`                     | —          |
| `domainscope` | Сканер периметра (опц.)             | `dexionius/domain-scope:${DS_VERSION}`    | —          |

> Образы захардкожены под Docker Hub (`dexionius/sshub-*`, `dexionius/domain-scope`). Подстановка собственного registry-префикса (`HUB_IMAGE_REGISTRY`) в текущем `docker-compose.yml` **не поддерживается**: для закрытого контура зеркальте образы под теми же именами в своём registry-зеркале (через pull-through / proxy cache).

## 4. Проверка

После `docker compose up -d` + `docker compose restart backend` подождите ~30 секунд (миграции БД стартуют автоматически, bootstrap создаёт администратора):

```bash
# Backend жив
curl http://localhost:8082/api/v1/version
# Frontend отвечает
curl -I http://localhost:3000
```

Откройте `http://localhost:3000` в браузере. Войдите как `admin@localhost.local` / значение `LOCAL_ADMIN_PASSWORD`.

### Swagger / OpenAPI

Hub отдаёт интерактивную документацию API:

```
https://hub.example.com/swagger/index.html
```

(локально — `http://localhost:8082/swagger/index.html`). Удобно для отладки интеграций и проверки контрактов.

## 5. Обратный прокси и TLS

Compose стек слушает на голых портах. Для production поставьте перед ним nginx/traefik/caddy с TLS.

### Пример nginx

```nginx
server {
    listen 443 ssl http2;
    server_name hub.example.com;

    ssl_certificate     /etc/letsencrypt/live/hub.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/hub.example.com/privkey.pem;

    client_max_body_size 100M;  # SARIF-отчёты бывают большими

    location /api/ {
        proxy_pass http://127.0.0.1:8082;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /swagger/ {
        proxy_pass http://127.0.0.1:8082;
    }

    location /version {
        proxy_pass http://127.0.0.1:8082;
    }

    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_set_header Host $host;
    }
}

server {
    listen 80;
    server_name hub.example.com;
    return 301 https://$host$request_uri;
}
```

## 6. Service-сценарии

### Запуск Keycloak (SSO)

Базовый стек работает в режиме локальной аутентификации (`AUTH_MODE=LOCAL`), Keycloak не требуется. Если нужен SSO — поднимите Keycloak отдельно и переключите `AUTH_MODE`; настройка realm/client и переменных описана в [Вход через SSO и OIDC](integration-sso.md).

## 7. Управление

```bash
# Логи
docker compose logs -f                # все
docker compose logs -f backend

# Перезапуск (например, после изменения env)
docker compose restart backend worker

# Остановка
docker compose down

# Обновление до новой версии (поправьте HUB_VERSION/DS_VERSION в .env)
docker compose pull
docker compose up -d
docker compose restart backend

# Версия
curl http://localhost:8082/version
```

## 8. Persistence

| Что                       | Где                              |
| ------------------------- | -------------------------------- |
| БД Hub                    | docker volume `postgres_data`    |
| БД DomainScope (опц.)     | docker volume `ds_postgres_data` |
| Токен сканера (bootstrap) | docker volume `scanner_shared`   |

Backup БД:

```bash
docker compose exec postgres pg_dump -U securityhub securityhub | gzip > backup-$(date +%Y%m%d).sql.gz
```

Restore:

```bash
gunzip -c backup-20260601.sql.gz | docker compose exec -T postgres psql -U securityhub securityhub
```

## 9. Обновление

```bash
cd /opt/hub
docker compose pull
docker compose up -d
docker compose restart backend
```

Миграции БД применяются автоматически при старте backend. Подробнее: [Обновления](upgrades.md).

## Типовые проблемы

| Симптом                 | Что проверить                                                                     |
| ----------------------- | --------------------------------------------------------------------------------- |
| Backend в crash-loop    | `docker compose logs backend` — обычно отсутствует `JWT_SECRET` или БД недоступна |
| Frontend 502            | Backend не стартует или `REACT_APP_API_URL` указан неверно                        |
| SARIF upload 413        | Увеличьте `client_max_body_size` в nginx                                          |
| Миграции не применяются | Проверьте `DB_*` env vars; ошибки в backend-логах                                 |
| `docker pull denied`    | Не залогинены в registry. `docker login <registry>`                               |

Полный troubleshooting: [Диагностика](troubleshooting.md).


## Что дальше

Hub запущен. Как довести его до состояния, в котором появляются находки, —
[Первые шаги после установки](first-steps.md).
