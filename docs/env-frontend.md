# Переменные окружения: frontend

Клиентские переменные имеют префикс `REACT_APP_`. Они запекаются плейсхолдерами в JS-бандл на этапе сборки и подменяются на реальные значения **на старте контейнера** скриптом `entrypoint.sh` (через `sed` по `static/js/*.js`). В Helm задаются через `frontend.frontend.env.*`.

| Переменная | Назначение | Значения | По умолчанию | Обязательна |
|---|---|---|---|---|
| `REACT_APP_API_URL` | Базовый URL backend API. Используется и для API-вызовов, и для запроса `/api/v1/auth/config` (определение LOCAL/SSO) | URL `http(s)://host[:port]` | `http://localhost:8082` [code] / `https://hub.example.com` [chart] | Да (в проде) |
| `REACT_APP_KEYCLOAK_URL` | URL Keycloak для OIDC-логина (SSO) | URL | `""` (chart); `http://localhost:8083` (.env.example) | Только при SSO |
| `REACT_APP_KEYCLOAK_REALM` | Realm Keycloak | строка | `""` (chart); `securityhub` (.env.example) | Только при SSO |
| `REACT_APP_KEYCLOAK_CLIENT_ID` | client_id Keycloak | строка | `""` (chart); `securityhub` (.env.example) | Только при SSO |
| `REACT_APP_NETBOX_BASE_URL` | Если задан — IP в карточке finding'а становятся ссылками на поиск в NetBox (`${URL}/search/?q=${ip}`) | URL или пусто | `""` | Нет |
| `REACT_APP_APP_ENV` | Окружение. `development` показывает dev-баннер и кнопку dev-логина; `production` их скрывает | `development` \| `production` | `production` (entrypoint fallback); `development` (.env.example) | Нет |
| `REACT_APP_AUTH_MODE` | Заявленный режим аутентификации. **Фактически не влияет** на фронт (см. ниже) | `LOCAL` \| `SSO` | `LOCAL` [chart] | Нет (no-op) |

## Важно: схема URL и выбор LOCAL/SSO

Реальный режим логина (форма логин/пароль против кнопки «Sign in with Keycloak») определяет **backend** через `GET /api/v1/auth/config`, а не `REACT_APP_AUTH_MODE`. Значение `REACT_APP_AUTH_MODE` из чарта в бандл не подставляется и фронтом не читается — оставлено для совместимости.

Из этого следует контракт, который легко нарушить:

- `REACT_APP_API_URL` **должен совпадать по схеме (http/https) с тем, как реально открывается Hub**. Если страница открыта по `http://`, а `REACT_APP_API_URL` указывает на `https://` (или наоборот), запрос `/api/v1/auth/config` падает (mixed-content / CORS) → фронт уходит в `catch` → **fallback на экран SSO** вместо локального логина.
- При TLS-режиме `disabled` (Hub по HTTP) задавайте `REACT_APP_API_URL: http://<domain>`. При `selfsigned`/`letsencrypt` — `https://<domain>`.

> Чарт-дефолты (`hub.example.com`) — плейсхолдеры, обязательны к переопределению в проде.
