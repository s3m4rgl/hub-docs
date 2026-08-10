# Security Hub

**Security Hub** — платформа управления уязвимостями со встроенными сканерами
(DomainScope, OpenVAS, OWASP ZAP) поверх Kubernetes/k3s.

Этот репозиторий — единая точка для развёртывания и эксплуатации:

- 📖 **Документация** — руководство администратора (развёртывание, настройка,
  интеграции, эксплуатация). Опубликована как сайт:
  **https://dexion.github.io/hub-docs/**
- ⎈ **Helm-чарты** — готовые чарты всех компонентов в [`charts/`](charts/).
- 🚀 **Установщик** — [`install.sh`](install.sh) + [быстрый старт](QUICKSTART.md):
  от голой VM до рабочего Hub за ~10 минут.

## Быстрый старт

### Локально через Docker Compose (ознакомление)

```bash
git clone https://github.com/dexion/hub-docs.git
cd hub-docs
cp .env.example .env            # при желании поправьте пароли, домены, порты
docker compose up -d            # Hub + DomainScope + одноразовый bootstrap
docker compose restart backend  # backend применит роль администратора
```

Откройте http://localhost:3000 — вход `admin@localhost.local` / значение
`LOCAL_ADMIN_PASSWORD` из `.env`. Аутентификация локальная (логин/пароль),
Keycloak не требуется.

**Состав стека:**
| Контейнер | Назначение |
|-----------|-----------|
| `sshub-postgres` | PostgreSQL для Hub (backend + worker) |
| `sshub-backend` | Go API (AUTH_MODE=LOCAL, порт 8082) |
| `sshub-worker` | Фоновые задачи Hub |
| `sshub-frontend` | React SPA (порт 3000) |
| `sshub-bootstrap` | Одноразовый init: admin, проект, SA, токен сканера |
| `ds-postgres` | PostgreSQL для DomainScope (отдельный инстанс) |
| `ds-scanner` | DomainScope — сканирует `DOMAINSCOPE_TARGETS`, шлёт находки в Hub |

Чтобы запустить только Hub (без DomainScope), закомментируйте сервисы
`ds-postgres` и `domainscope` в `docker-compose.yml`.

### На k3s через Helm (полноценный стенд)

```bash
./install.sh        # интерактивная установка на k3s
```

Подробно — [QUICKSTART.md](QUICKSTART.md) (пути Evaluation / Production, требования,
WireGuard для сканирования периметра «снаружи»).

## Состав

| Каталог | Назначение |
|---------|-----------|
| [`docs/`](docs/) | Исходники документации (MkDocs Material), публикуются на GitHub Pages |
| [`charts/`](charts/) | Helm-чарты: `security-scan-hub`, `domainscope`, `openvas`, `owasp-zap`, `netbox`, `hub-platform` (umbrella), `sshub-atlassian-secrets-scanner` |
| [`scripts/`](scripts/) | Вспомогательные скрипты (WireGuard setup и пр.) |
| [`install.sh`](install.sh) | Интерактивный установщик на k3s |

## Образы

Все компоненты поставляются готовыми образами `dexionius/*` (Docker Hub) с тегом
`:latest` и версионными тегами (напр. `:0.30`). Версию можно зафиксировать в
values чарта (`image.tag: "0.30"`).

## Лицензия и поддержка

По вопросам развёртывания и коммерческой поддержки — см. контакты в документации.
