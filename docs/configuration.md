# Конфигурация: обзор и соглашения

Security Hub и сопутствующие сервисы настраиваются через **переменные окружения**. Их можно задавать:

- в `.env` (для Docker Compose);
- в `values.yaml` Helm-чарта (для Kubernetes/k3s);
- напрямую в окружении процесса (bare-metal).

Полный справочник переменных разбит по компонентам:

- **[Hub (backend + worker)](env-hub.md)** — аутентификация, БД, LLM/sandbox, уведомления, Jira, dual-verify, rescan, лимиты.
- **[Frontend](env-frontend.md)** — `REACT_APP_*`, runtime-инъекция, контракт схемы http/https.
- **[DomainScope](env-domainscope.md)** — scope, сканеры (nmap/nuclei/openvas/tlsx/zap), SARIF, Hub Scope API, NetBox, security.
- **[Сканеры: IaC, OpenVAS, OWASP ZAP](env-scanners.md)** — iac-scanner, чарты OpenVAS и ZAP, WireGuard egress.

## Соглашения справочника

- **Обязательная** — компонент не запустится / упадёт (fatal) без неё.
- **Рекомендуемая** — дефолт работает, но в production стоит задать явно.
- **Опциональная** — фича включается только при наличии переменной.
- Колонка «По умолчанию»: `[code]` — литерал в исходниках, `[chart]` — значение Helm-чарта. При расхождении указаны оба.

## Безопасность значений по умолчанию

> Дефолтные секреты (`JWT_SECRET=change-this-secret-key`, `DB_PASSWORD=securityhub123`, пароли из `.env.example` и `values-poc.yaml`) **небезопасны для production**. Всегда генерируйте собственные случайные значения и храните их в секрет-менеджере (Vault / External Secrets / SealedSecrets), а не в git.

## production-гейты

При `APP_ENV=production` (Hub) и `DOMAINSCOPE_ENV=production` (DomainScope) включаются дополнительные проверки:

- секрет-несущие URL (Keycloak, Jira, SARIF эндпоинт, Hub Scope API, NetBox, Metabase, dual-verify) обязаны использовать `https://` — иначе старт падает (если не выставлен явный `*_INSECURE` / `*_ALLOW_HTTP`);
- обязательные секреты (`JWT_SECRET`, `DB_PASSWORD`, `KEYCLOAK_CLIENT_SECRET` при SSO) должны быть заданы, иначе fatal.

## API-документация

В каждом развёрнутом инстансе Hub доступна интерактивная Swagger UI:

```
https://<your-hub-domain>/swagger/index.html
```

## Применение изменений

После любого изменения переменных окружения:

- **Compose**: `docker compose restart backend worker`
- **Kubernetes**: `helm upgrade …` — поды пересоздадутся
- **bare-metal**: `sudo systemctl restart hub-backend hub-worker`


Полный перечень внешних эндпоинтов и правил обращения к API —
[REST API](api.md).
