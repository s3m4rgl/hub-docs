# Переменные окружения: frontend

Клиентские переменные имеют префикс `REACT_APP_`. Они запекаются плейсхолдерами в JS-бандл на этапе сборки и подменяются на реальные значения **на старте контейнера** скриптом `entrypoint.sh` (через `sed` по `static/js/*.js`). В Helm задаются через `frontend.frontend.env.*`.

| Переменная | Назначение | Значения | По умолчанию | Обязательна |
|---|---|---|---|---|
| `REACT_APP_API_URL` | Базовый URL backend API. Используется и для API-вызовов, и для запроса `/api/v1/auth/config` (определение LOCAL/SSO) | URL `http(s)://host[:port]` | `http://localhost:8082` [code] / `https://hub.example.com` [chart] | Да (в проде) |
| `REACT_APP_NETBOX_BASE_URL` | Если задан — IP в карточке находка'а становятся ссылками на поиск в NetBox (`${URL}/search/?q=${ip}`) | URL или пусто | `""` | Нет |
| `REACT_APP_APP_ENV` | Окружение. `development` показывает dev-баннер и кнопку dev-логина; `production` их скрывает | `development` \| `production` | `production` (entrypoint fallback); `development` (.env.example) | Нет |

## Настроек провайдера входа у интерфейса нет

`REACT_APP_AUTH_MODE`, `REACT_APP_KEYCLOAK_URL`, `REACT_APP_KEYCLOAK_REALM` и
`REACT_APP_KEYCLOAK_CLIENT_ID` **бандлом не читаются** — в 0.33 их нет в коде
интерфейса вовсе, а из чартов поставки убраны и сами переменные. Настройка
выглядела рабочей, не будучи ею: администратор мог выставить realm и не
получить ничего.

Режим входа — форма логина против кнопок провайдеров — и адреса самих
провайдеров интерфейс получает от backend через `GET /api/v1/auth/config`.
Поэтому знать адрес IdP, realm и `client_id` ему не нужно: они задаются у
backend (`KEYCLOAK_*`, `OIDC_<ИМЯ>_*`) — см. [переменные Hub](env-hub.md).

## Важно: схема URL

Из этого следует контракт, который легко нарушить:

- `REACT_APP_API_URL` **должен совпадать по схеме (http/https) с тем, как реально открывается Hub**. Если страница открыта по `http://`, а `REACT_APP_API_URL` указывает на `https://` (или наоборот), запрос `/api/v1/auth/config` падает (mixed-content / CORS) → фронт уходит в `catch` → **fallback на экран SSO** вместо локального логина.
- При TLS-режиме `disabled` (Hub по HTTP) задавайте `REACT_APP_API_URL: http://<domain>`. При `selfsigned`/`letsencrypt` — `https://<domain>`.

> Чарт-дефолты (`hub.example.com`) — плейсхолдеры, обязательны к переопределению в проде.
