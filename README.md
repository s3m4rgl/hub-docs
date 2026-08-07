# Security Hub

**Security Hub** — платформа управления уязвимостями: принимает результаты
работы сканеров, сводит их в единый список находок, убирает дубликаты, ведёт
каждую находку по жизненному циклу, следит за сроками устранения и передаёт
работу в трекер задач и каналы оповещения.

Этот репозиторий — единая точка для развёртывания и эксплуатации:

- **Документация** — опубликована как сайт:
  **https://s3m4rgl.github.io/hub-docs/**
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
./install.sh
```

Подробнее — [QUICKSTART.md](QUICKSTART.md).

## Состав репозитория

| Каталог | Назначение |
| --- | --- |
| [`docs/`](docs/) | Исходники документации (MkDocs Material), публикуются на GitHub Pages |
| [`charts/`](charts/) | Helm-чарты: `security-scan-hub`, `domainscope`, `openvas`, `owasp-zap`, `netbox`, `hub-platform` (объединяющий), `sshub-atlassian-secrets-scanner` |
| [`scripts/`](scripts/) | Вспомогательные скрипты |
| [`install.sh`](install.sh) | Интерактивный установщик на k3s |

## Образы

Компоненты поставляются образами `dexionius/*` на Docker Hub. **Указывайте
явный тег версии**, а не `latest`, и проверяйте, что нужный тег существует у
всех компонентов, которые вы разворачиваете, — теги публикуются независимо, и
полный набор есть не для каждой версии.

Текущее значение по умолчанию в чартах и `docker-compose.yml` — `0.30`.
Как проверить доступные теги и что учесть при обновлении:
[Обновления](https://s3m4rgl.github.io/hub-docs/upgrades/).

## Сборка документации локально

```bash
python3 -m venv .venv
.venv/bin/pip install "mkdocs-material~=9.7.0"
.venv/bin/mkdocs serve
```

Версия темы зафиксирована намеренно: плавающая версия однажды уже молча
ломала отрисовку схем.
