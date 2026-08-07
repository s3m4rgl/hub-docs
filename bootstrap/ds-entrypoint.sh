#!/bin/sh
# Точка входа DomainScope для docker compose.
#
# Ждёт /shared/scanner.env, сгенерированного bootstrap'ом (содержит
# DOMAINSCOPE_SARIF_PRODUCT_ID, DOMAINSCOPE_SARIF_API_TOKEN,
# DOMAINSCOPE_HUB_PROJECT_IDS), экспортирует их и запускает сканер.
set -e

SHARED_ENV=/shared/scanner.env

until [ -f "$SHARED_ENV" ]; do
  echo "ds-entrypoint: жду $SHARED_ENV от bootstrap..."
  sleep 3
done

# Экспортируем переменные из scanner.env в окружение процесса
set -a
# shellcheck source=/dev/null
. "$SHARED_ENV"
set +a

# Hub Scope API использует тот же SA-токен, что и SARIF upload
export DOMAINSCOPE_HUB_API_TOKEN="$DOMAINSCOPE_SARIF_API_TOKEN"

exec /domain-scope daemon run
