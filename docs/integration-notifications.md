# Уведомления

Hub шлёт уведомления при появлении / переоткрытии / повышении severity findings. Поддерживаются два канала: **Mattermost** (incoming webhook) и **Telegram** (bot API). Конфигурация per-project — в UI Hub, без перезапуска.

## Архитектура

```
   Event (new finding / renewed / severity_increased)
        │
        ▼
   Dispatcher worker
        │
        ├─ Читает notification rules проекта (UI Hub)
        ├─ Фильтрует по min_severity, event_types, tags
        ├─ Для каждого канала кладёт job в свою очередь
        │
        ▼
   ┌─────────────────────┐    ┌─────────────────────┐
   │ Telegram worker     │    │ Mattermost worker   │
   │ TELEGRAM_NOTIFI...  │    │ MATTERMOST_NOTIFI.. │
   └──────────┬──────────┘    └──────────┬──────────┘
              │ HTTPS                    │ HTTPS
              ▼                          ▼
        Telegram Bot API           Mattermost incoming webhook
```

## Env vars

| Переменная                        | Default                 | Описание                                               |
| --------------------------------- | ----------------------- | ------------------------------------------------------ |
| `DISPATCHER_WORKERS`              | `10`                    | Параллелизм dispatcher (разводит события по каналам)   |
| `TELEGRAM_NOTIFICATION_WORKERS`   | `5`                     | Воркеры отправки в Telegram                            |
| `MATTERMOST_NOTIFICATION_WORKERS` | `10`                    | Воркеры отправки в Mattermost                          |
| `NOTIFICATIONS_DRY_RUN`           | `false`                 | Если `true` — логирует, но не шлёт. Полезно для тестов |
| `FRONTEND_BASE_URL`               | `http://localhost:3000` | Префикс для deep-links в сообщениях                    |

## Event types

Уведомления летят при следующих событиях:

| Событие              | Когда                                                           |
| -------------------- | --------------------------------------------------------------- |
| `new`                | Создан новый finding (после первой загрузки SARIF)              |
| `renewed`            | Finding с `fixed` статусом снова появился в отчёте              |
| `severity_increased` | Severity изменилась в большую сторону (например, MEDIUM → HIGH) |

Подписка на event type настраивается в UI Hub: Project → Notifications → New rule.

## Telegram

### 1. Создать бота

Через [@BotFather](https://t.me/BotFather):

```
/newbot
Имя: SecurityHub Bot
Username: securityhub_company_bot
```

BotFather выдаст токен вида `7123456789:AAH...` — это `bot_token`.

### 2. Получить chat_id

**Личное сообщение боту:** напишите боту `/start`, затем:

```bash
curl https://api.telegram.org/bot<TOKEN>/getUpdates | jq '.result[].message.chat'
```

Возьмите `id` (положительное число для личных, отрицательное для групп).

**Канал/группа:** добавьте бота в канал (нужны admin-права в канале); затем тот же запрос — `chat_id` будет начинаться с `-100`.

### 3. Настроить в Hub

UI Hub: Project → Notifications → Add channel → Telegram:

- **Bot token:** `7123456789:AAH...`
- **Chat ID:** `-1001234567890`
- **Min severity:** `INFO` / `LOW` / `MEDIUM` / `HIGH` / `CRITICAL`
- **Event types:** ☑ new ☑ renewed ☑ severity_increased

### 4. Проверка

Создайте тестовый finding в Hub (через любой SARIF upload) с severity ≥ `min_severity` правила — сообщение должно прийти. Сбои отправки видны в логах worker.

## Mattermost

### 1. Создать incoming webhook в Mattermost

Mattermost UI → Channel → Integrations → Incoming Webhooks → Add:

- Channel: куда слать
- Username override: `Security Hub`
- Profile picture override: (опционально, логотип Hub)

После создания — скопировать URL вида `https://mattermost.example.com/hooks/xxxxxxxx`.

### 2. Настроить в Hub

UI Hub: Project → Notifications → Add channel → Mattermost:

- **Webhook URL:** `https://mattermost.example.com/hooks/xxxxxxxx`
- **Min severity:** `MEDIUM`
- **Event types:** выбрать

## Формат сообщений

### Telegram

```
🔴 [HIGH] SQL Injection in /api/v1/users
Product: backend-api
Resource: example.com:443

CWE-89: User input passed unsanitized to SQL query…

🔗 https://hub.example.com/findings/abc-123
```

### Mattermost

```markdown
**🔴 [HIGH] SQL Injection in /api/v1/users**

| Поле     | Значение        |
| -------- | --------------- |
| Product  | backend-api     |
| Resource | example.com:443 |
| Severity | HIGH            |
| CWE      | CWE-89          |

[Open in Hub](https://hub.example.com/findings/abc-123)
```

## Retry policy

При неудачной отправке (timeout / 5xx / Rate limited) Hub ретраит с exponential backoff:

| Попытка | Задержка |
| ------- | -------- |
| 1       | 1 минута |
| 2       | 5 минут  |
| 3       | 15 минут |
| 4       | 1 час    |
| 5       | 6 часов  |

После 5 неудач сообщение помечается как failed. Сбои видны в логах worker.

**Что считается успехом:**

- Telegram: `ok: true` в ответе Bot API
- Mattermost: HTTP 200

**Что НЕ ретраится:**

- 400/403 — конфигурация-баг, дальше отправлять бесполезно
- 401 — бот не имеет доступа

## Dry run

Для тестирования настроек без реальной отправки:

```ini
NOTIFICATIONS_DRY_RUN=true
```

Hub будет логировать в `worker.log`:

```json
{
  "level": "info",
  "msg": "notification dry_run",
  "channel": "telegram",
  "chat_id": "-100123",
  "text": "..."
}
```

После проверки — `NOTIFICATIONS_DRY_RUN=false` + рестарт worker.

## Мониторинг

Состояние и сбои отслеживаются через логи worker'а:

```bash
docker compose logs -f worker | grep -i notif
```

## Типовые проблемы

| Симптом                       | Что проверить                                                                 |
| ----------------------------- | ----------------------------------------------------------------------------- |
| Уведомления не приходят       | Логи worker — есть ли попытка отправки? Если нет — проверьте правила в UI Hub |
| Telegram: `400 Bad Request`   | Chat ID правильный? Для каналов нужен формат `-100...`, бот должен быть admin |
| Telegram: `chat not found`    | Бот не добавлен в канал/группу                                                |
| Mattermost: `400 Bad Request` | Сломанный JSON. Проверьте webhook URL целиком (с `/hooks/`)                   |
| Mattermost: `Webhook deleted` | В Mattermost удалили integration. Создайте новый и обновите в Hub             |
| Все сообщения дублируются     | Проверьте, что worker один (не два процесса)                                  |
