# Security Hub

**Security Hub** — платформа управления уязвимостями: принимает результаты
работы сканеров, сводит их в единый список находок, убирает дубликаты, ведёт
каждую находку по жизненному циклу, следит за сроками устранения и передаёт
работу в трекер задач и каналы оповещения.

Этот репозиторий — единая точка для развёртывания и эксплуатации:

- **Документация** — опубликована как сайт:
  **https://docs.hub.vnd-tech.ru/**
- **Helm-чарты** — готовые чарты всех компонентов в [`charts/`](charts/)
- **Установщик** — [`install.sh`](install.sh) и [быстрый старт](QUICKSTART.md)

## Быстрый старт

### Docker Compose — для ознакомления

```bash
git clone https://github.com/s3m4rgl/hub-docs.git
cd hub-docs
cp .env.example .env            # задайте пароли, домены, порты
docker compose up -d            # Hub + DomainScope + одноразовая инициализация
docker compose restart backend  # backend применит роль администратора
```

Откройте `http://localhost:3000`. Вход — `admin@localhost.local` и значение
`LOCAL_ADMIN_PASSWORD` из `.env`. Аутентификация локальная, внешний провайдер
входа не требуется.

Состав стека:

| Контейнер | Назначение |
| --- | --- |
| `sshub-postgres` | PostgreSQL для Hub |
| `sshub-backend` | API, порт 8082 |
| `sshub-worker` | Фоновые задачи |
| `sshub-frontend` | Веб-интерфейс, порт 3000 |
| `sshub-bootstrap` | Одноразовая инициализация: администратор, проект, сервисная учётная запись |
| `ds-postgres` | PostgreSQL для DomainScope — отдельный экземпляр |
| `ds-scanner` | DomainScope: обследует периметр и отдаёт находки в Hub |

Чтобы запустить только Hub, закомментируйте сервисы `ds-postgres` и
`domainscope` в `docker-compose.yml`.

### k3s через Helm — полноценный стенд

```bash
sudo ./install.sh
```

Подробнее — [QUICKSTART.md](QUICKSTART.md).

## Состав репозитория

| Каталог | Назначение |
| --- | --- |
| [`docs/`](docs/) | Исходники документации (MkDocs Material), публикуются на GitHub Pages |
| [`charts/`](charts/) | Helm-чарты: `security-scan-hub`, `domainscope`, `openvas`, `owasp-zap`, `netbox`, `hub-platform` (объединяющий), `sshub-atlassian-secrets-scanner` |
| [`scripts/`](scripts/) | Вспомогательные скрипты |
| [`bootstrap/`](bootstrap/) | Одноразовая инициализация для Docker Compose |
| [`install.sh`](install.sh) | Установщик на k3s (параметры — флагами, без диалога) |

## Образы

Компоненты поставляются образами `dexionius/*` на Docker Hub. **Указывайте
явный тег версии**, а не `latest`, и проверяйте, что нужный тег существует у
всех компонентов, которые вы разворачиваете, — теги публикуются независимо, и
полный набор есть не для каждой версии.

Текущее значение по умолчанию в чартах: Hub (backend, worker, frontend,
iac-scanner) — `0.33`, DomainScope — `0.34`. В `docker-compose.yml` и
`.env.example` оба тега — `0.33` (`HUB_VERSION`, `DS_VERSION`).
Совпадение версий не гарантировано — компоненты выпускаются независимо, и
полный набор образов есть не для каждой версии.
Как проверить доступные теги и что учесть при обновлении:
[Обновления](https://docs.hub.vnd-tech.ru/upgrades/).

## Сборка документации локально

```bash
python3 -m venv .venv
.venv/bin/pip install "mkdocs-material~=9.7.0"
.venv/bin/mkdocs serve
```

Версия темы зафиксирована намеренно: плавающая версия однажды уже молча
ломала отрисовку схем.
