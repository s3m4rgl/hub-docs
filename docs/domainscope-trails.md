# Происхождение записей периметра

DomainScope сохраняет **происхождение** каждого домена и IP в perimeter — откуда узнали, какой parent, на каком цикле добавили. Это нужно чтобы:

- Понимать, почему DomainScope считает тот или иной актив «нашим»
- Отлаживать false positives (parking, CDN, дочерние компании)
- Принимать решения по scope (нужен ли этот IP в перимметре)

## Работа с trails через UI Hub

В Hub UI для каждого scope-entry (Project → Scope) отображается **источник появления** (provenance):

- **Source** — откуда появилось (домены: config / subfinder / netbox_dns / scope_entry / tls_san; IP: netbox_import / dns_resolve / scope_entry)
- **Parent domain** — непосредственный родитель (для поддомена)
- **Root domain** — корневой seed-домен
- **Discovered at** — когда впервые увидели
- **Last seen at** — когда последний раз подтвердили в скане

Для каждой записи доступны действия:

- **Confirm** — подтвердить добавление в активный perimeter
- **Reject** — пометить tombstone (DomainScope не будет реактивировать автоматически)
- **Block subtree** — заблокировать корень и всё его поддерево разом (для parking-доменов, чужих регистраторов)
- **View history** — посмотреть, в каких циклах сканирования встречалась запись

Большинство задач по управлению trails решается **через эти кнопки в UI**. Прямой доступ в БД не требуется.

## Типовые сценарии

### Сценарий A: DomainScope сканирует «не наш» домен

1. В Hub UI: Project → Scope → найти подозрительный домен (фильтр по source/value)
2. Открыть карточку — посмотреть `Source`, `Root domain`, `Discovered at`
3. Если домен пришёл через `subfinder` от чужого root — `Reject` или `Block subtree`
4. Если домен пришёл через `netbox_dns` — поправьте тег/scope в NetBox; следующий sync уберёт его

### Сценарий B: Свежее обнаружение, нужно одобрить

1. Hub UI: Project → Scope Proposals — список новых предложений от DomainScope
2. Для каждого: подтвердить (Confirm) или отклонить (Reject)
3. Подтверждённые становятся частью активного scope

### Сценарий C: Пропадают домены, которые раньше сканировались

1. Hub UI: Project → Scope → фильтр `Last seen at < 30 дней назад`
2. Проверьте, что домен/IP физически жив (например, `dig <domain>`)
3. Если давно нерабочий — `Reject` (retired). Если временный сбой — оставьте, DomainScope обновит на следующем цикле

### Сценарий D: Приватные IP в SARIF, нужны только публичные

Это решается не через trails, а через фильтр сканера:

```ini
DOMAINSCOPE_SARIF_IP_SCOPE=public   # all / public / private
```

См. [Управление сканерами DomainScope](domainscope-scanners.md).

## Источники provenance

Домены (`domains.source`):

| Source         | Что значит                                            |
| -------------- | ----------------------------------------------------- |
| `config`       | Прописан в `DOMAINSCOPE_DOMAINS` или YAML-конфиге     |
| `subfinder`    | Найден через subfinder (поддомены discovery)          |
| `netbox_dns`   | Импортирован из NetBox-DNS plugin (DNS-зоны)          |
| `scope_entry`  | Получен из Hub через scope sync                       |
| `tls_san`      | Извлечён из SAN сертификата TLS обнаруженного сервера |

IP-адреса (`ip_addresses.source`):

| Source          | Что значит                                  |
| --------------- | ------------------------------------------- |
| `netbox_import` | Импортирован из NetBox IPAM                 |
| `dns_resolve`   | Получен DNS-резолвингом обнаруженного домена |
| `scope_entry`   | Получен из Hub через scope sync             |

Значений `discovery`, `netbox` и `manual` в provenance нет.

## Защита от автоматической реактивации

Если scope-entry помечен в Hub как `Reject`-нутый админом — DomainScope **никогда не вернёт его** обратно автоматически. Это защита от перетирания ручных решений: пометили «это не наш периметр» — значит не наш, даже если discovery снова его увидит.

Чтобы вернуть запись в активные, админу нужно явно нажать `Activate` в UI Hub.

## Связанные документы

- [Управление сканерами DomainScope](domainscope-scanners.md) — управление сканерами и IP_SCOPE фильтр
- [DomainScope и NetBox](domainscope-netbox.md) — sync с NetBox
