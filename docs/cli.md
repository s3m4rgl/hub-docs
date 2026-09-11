# Консольный клиент

`sshub` — терминальный интерфейс к Hub: находки, дашборд, отчёты, инвентарь,
SLA, фоновые задачи, администрирование и гейт для CI.

Появился в 0.33.

## Установка

Клиент — отдельный модуль Go в поставке исходного кода
(`github.com/security-hub/sshub`), собирается одной командой:

```bash
cd cli && go build -o /usr/local/bin/sshub .
sshub version
```

Отдельный модуль — осознанное решение: клиент не тянет зависимости backend
(ORM, очередь задач, песочницу плагинов), поэтому бинарь остаётся небольшим.
Контракт с сервером задаёт спецификация OpenAPI, а не общие Go-типы.

## Аутентификация

Способов два, и они не взаимозаменяемы — у Hub две непересекающиеся группы
маршрутов:

| Способ | Заголовок | Куда пускает |
| --- | --- | --- |
| Ключ сервисного аккаунта | `X-API-Key` | Загрузка отчёта, инвентарь, дашборд, список находок, нарушения SLA |
| Пользовательский токен | `Authorization: Bearer` | Правка находки, экспорт, массовые операции, администрирование |

```bash
export SSHUB_SERVER=https://hub.example.com
export SSHUB_API_KEY=...      # ключ сервисного аккаунта
export SSHUB_TOKEN=...        # пользовательский JWT, при необходимости
```

Значения берутся в порядке: **флаг → переменная окружения → файл
`~/.sshub.json`**. Разовый запуск против другого стенда не требует правки
сохранённой конфигурации, а в CI значение приходит переменной и не светится в
списке процессов.

Токен короткоживущий, поэтому клиент его сам никуда не сохраняет. Ключ в вывод
не печатается никогда.

```bash
sshub config set server https://hub.example.com
sshub config show
sshub auth status        # кто я для сервера
```

Ключ сервисного аккаунта выпускается из интерфейса либо тем же клиентом:

```bash
sshub admin service-accounts create --name ci-gate
sshub admin service-accounts key-create <uuid> --name ci-gate-key --expires-at 2027-01-01
# ключ показывается один раз
```

## Гейт для CI

Команда делает то, ради чего в CI обычно пишут два десятка строк на `curl` и
`jq`: загружает отчёт, **дожидается разбора** и возвращает код, по которому
пайплайн принимает решение.

```bash
sshub gate --product <uuid> --file semgrep.sarif --fail-on HIGH
sshub gate --product <uuid> --file trivy.sarif --fail-on CRITICAL --timeout 10m
```

| Код | Что значит |
| --- | --- |
| `0` | Новых находок выше порога нет |
| `1` | **Гейт не пройден** — есть новые находки выше порога |
| `2` | Инструмент не смог вынести вердикт: Hub недоступен, таймаут, неверные аргументы, разбор отчёта завершился ошибкой |

!!! warning "Не сливайте 1 и 2 в одно условие"

    Первое означает «надо чинить код», второе — «надо чинить обвязку».
    Пайплайн, который трактует их одинаково, рано или поздно получает
    `|| true` и перестаёт проверять что-либо вовсе.

Судится только **новое в этом отчёте**, а не весь накопленный техдолг
продукта: иначе первый же запрос на слияние в старый проект становится
красным навсегда.

## Команды

### Находки

```bash
sshub findings list --severity HIGH --status new --product <uuid> --limit 50
sshub findings list --search "jwt" --json | jq '.data[].title'
sshub findings create --product <uuid> --title "Открытый Redis" --severity HIGH \
  --host 10.0.0.5 --description "Без пароля" --engine custom/manual
sshub findings update <finding-id> --status confirmed
sshub findings export --format csv --product <uuid> --out findings.csv
sshub findings similar <finding-id>
sshub findings bulk-update --id <id1> --id <id2> --status risk_accepted
```

`findings create` — ручной ввод находки без SARIF; такая находка проходит тот
же путь, что и загруженная сканером.

### Дашборд и SLA

```bash
sshub dashboard overview
sshub dashboard trends
sshub dashboard top-findings
sshub dashboard sla-compliance
sshub dashboard scanner-stats
sshub dashboard ai-categories
sshub sla violations
```

### Отчёты

```bash
sshub reports upload --product <uuid> --file report.sarif --engine semgrep
sshub reports export company --from 2026-08-01 --to 2026-08-31
sshub reports export compliance --framework pci_dss --from 2026-08-01 --to 2026-08-31
sshub reports export project --from 2026-08-01 --to 2026-08-31 --projects <uuid>
sshub reports export product --from 2026-08-01 --to 2026-08-31 --out product.json
```

### Инвентарь

```bash
sshub resources projects                 # список проектов
sshub resources products --search api    # список продуктов
sshub resources projects create --name "Периметр"
sshub resources products create --project <uuid> --name "api-gateway" --repo-url https://git.example.com/api
sshub resources products update <uuid> --branch main
sshub resources projects delete <uuid> --yes
```

### Задачи во внешнем трекере

```bash
sshub ticket-providers
sshub ticket <finding-id> --plugin <installed-plugin-uuid> --target <цель>
```

Подробности — в [Учёте задач](integration-jira.md).

### Перепроверка и триаж

```bash
sshub rescan <finding-id> --via scanner   # или --via llm
sshub reanalyze <finding-id>
```

### Фоновые задачи

```bash
sshub jobs list
sshub jobs get <job-id>
sshub jobs retry <job-id>
sshub jobs cancel <job-id>
```

### Администрирование

```bash
sshub admin users list
sshub admin roles list
sshub admin service-accounts list
sshub access-requests list
sshub access-requests list --mine
sshub access-requests create --resource-type project --resource-id <uuid> \
  --role viewer --reason "нужен доступ к отчётам"
```

## Вывод для скриптов

Флаг `--json` отдаёт ответ сервера как есть — для `jq` и автоматизации:

```bash
sshub findings list --severity CRITICAL --json \
  | jq -r '.data[] | [.id, .title] | @tsv'
```

Размер страницы ограничен сервером. Значение выше потолка клиент отвергает
явно, а не подставляет умолчание молча: «показано 20» вместо запрошенных 5000
читалось бы как «столько и есть».

## Ошибки доступа

`401` и `403`, полученные по ключу сервисного аккаунта, объясняются отдельно:
у ключа есть область видимости по продуктам, и отказ обычно означает, что
маршрут требует пользовательского токена либо продукт не входит в область
ключа.

## Связанные документы

- [REST API](api.md) — те же операции напрямую
- [Учёт задач](integration-jira.md)
- [Загрузка отчётов](integration-sarif.md) — форматы и поля загрузки
