#!/usr/bin/env bash
# Проверка блока llm: чарта security-scan-hub на фикстурах.
#
# Каждая фикстура в charts/security-scan-hub/tests/llm/ — файл values, в
# комментариях которого записаны ожидания:
#   # expect: <backend|worker> <ENV>=<значение>   значение переменной в контейнере;
#                                               "-" — переменной нет,
#                                               secret:<имя>/<ключ> — secretKeyRef
#                                               без optional
#   # expect-secret: llmApiKey=<значение>       stringData Secret чарта
#   # expect-notes: <подстрока>                 есть в NOTES
#   # expect-no-notes: <подстрока>              нет в NOTES
#   # expect-error: <подстрока>                 рендер обязан упасть с этим текстом
#
# Кроме фикстур: helm lint, совпадение checksum/llm у backend и worker, смена
# checksum при смене настроек, рендер umbrella-чарта hub-platform.
#
# Требуется: helm 3.x/4.x, yq v4 (mikefarah). Кластер не нужен.
#
#   bash scripts/check-chart-llm.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CHART="$ROOT/charts/security-scan-hub"
FIXTURES="$CHART/tests/llm"
RELEASE=hub
NS=hub

for bin in helm yq; do
  command -v "$bin" >/dev/null || { echo "нужен $bin" >&2; exit 2; }
done

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

fails=0
pass() { printf '  ok   %s\n' "$1"; }
fail() { printf '  FAIL %s\n' "$1"; fails=$((fails + 1)); }

render() { # $1 — values-файл; дальше — доп. аргументы helm
  local values="$1"; shift
  helm template "$RELEASE" "$CHART" -n "$NS" -f "$values" "$@"
}

notes() { # NOTES без кластера: install --dry-run=client
  local values="$1"; shift
  helm install "$RELEASE" "$CHART" -n "$NS" --dry-run=client -f "$values" "$@" \
    | sed -n '/^NOTES:/,$p'
}

env_of() { # $1 — манифесты, $2 — компонент, $3 — имя переменной
  yq -r "select(.kind == \"Deployment\" and .metadata.labels.\"app.kubernetes.io/component\" == \"$2\")
    | .spec.template.spec.containers[0].env[]
    | select(.name == \"$3\")
    | (if has(\"value\") then .value
       else \"secret:\" + .valueFrom.secretKeyRef.name + \"/\" + .valueFrom.secretKeyRef.key
         + (if .valueFrom.secretKeyRef.optional == true then \"?optional\" else \"\" end)
       end)" \
    "$1" | head -n1
}

checksum_of() { # $1 — манифесты, $2 — компонент
  yq -r "select(.kind == \"Deployment\" and .metadata.labels.\"app.kubernetes.io/component\" == \"$2\")
    | .spec.template.metadata.annotations.\"checksum/llm\"" "$1"
}

echo "== helm lint"
if helm lint "$CHART" >"$TMP/lint.log" 2>&1; then pass "helm lint"; else cat "$TMP/lint.log"; fail "helm lint"; fi
for f in "$FIXTURES"/ok-*.yaml; do
  if helm lint "$CHART" -f "$f" >"$TMP/lint.log" 2>&1; then
    pass "helm lint -f $(basename "$f")"
  else
    cat "$TMP/lint.log"; fail "helm lint -f $(basename "$f")"
  fi
done

echo "== фикстуры"
for f in "$FIXTURES"/*.yaml; do
  name="$(basename "$f")"
  echo "-- $name"
  out="$TMP/$name.out"

  expected_error="$(sed -n 's/^# expect-error: //p' "$f")"
  if [[ -n "$expected_error" ]]; then
    if render "$f" >"$out" 2>&1; then
      fail "$name: рендер прошёл, ожидалась ошибка «${expected_error}»"
    elif grep -qF -- "$expected_error" "$out"; then
      pass "ошибка: $expected_error"
    else
      fail "$name: другая ошибка: $(tail -n1 "$out")"
    fi
    continue
  fi

  if ! render "$f" >"$out" 2>"$TMP/err"; then
    cat "$TMP/err"; fail "$name: рендер упал"; continue
  fi

  while read -r component assignment; do
    [[ -z "${component:-}" ]] && continue
    var="${assignment%%=*}"
    want="${assignment#*=}"
    got="$(env_of "$out" "$component" "$var")"
    [[ -z "$got" ]] && got="-"
    if [[ "$got" == "$want" ]]; then
      pass "$component $var=$want"
    else
      fail "$name: $component $var: ожидалось «${want}», получено «${got}»"
    fi
  done < <(sed -n 's/^# expect: //p' "$f")

  while IFS= read -r line; do
    [[ -z "$line" ]] && continue
    key="${line%%=*}"; want="${line#*=}"
    got="$(yq -r "select(.kind == \"Secret\" and .metadata.name == \"$RELEASE-security-scan-hub-secrets\") | .stringData.$key" "$out")"
    if [[ "$got" == "$want" ]]; then pass "Secret $key=«${want}»"; else fail "$name: Secret $key: ожидалось «${want}», получено «${got}»"; fi
  done < <(sed -n 's/^# expect-secret: //p' "$f")

  if grep -q '^# expect-\(no-\)\?notes: ' "$f"; then
    notes "$f" >"$TMP/notes" 2>&1 || { cat "$TMP/notes"; fail "$name: NOTES не отрендерились"; continue; }
    while IFS= read -r want; do
      if grep -qF -- "$want" "$TMP/notes"; then pass "NOTES: $want"; else fail "$name: в NOTES нет «${want}»"; fi
    done < <(sed -n 's/^# expect-notes: //p' "$f")
    while IFS= read -r unwanted; do
      if grep -qF -- "$unwanted" "$TMP/notes"; then fail "$name: в NOTES лишнее «${unwanted}»"; else pass "NOTES без: $unwanted"; fi
    done < <(sed -n 's/^# expect-no-notes: //p' "$f")
  fi

  b="$(checksum_of "$out" backend)"; w="$(checksum_of "$out" worker)"
  if [[ -n "$b" && "$b" != "null" && "$b" == "$w" ]]; then pass "checksum/llm у backend и worker совпадает"; else fail "$name: checksum/llm: backend=$b worker=$w"; fi
done

echo "== checksum/llm меняется вместе с настройками"
base="$FIXTURES/ok-apikey.yaml"
c1="$(render "$base" | checksum_of /dev/stdin worker)"
c2="$(render "$base" --set llm.model=other | checksum_of /dev/stdin worker)"
c3="$(render "$base" --set llm.apiKey=sk-other | checksum_of /dev/stdin worker)"
c4="$(render "$base" | checksum_of /dev/stdin worker)"
[[ "$c1" == "$c4" ]] && pass "стабилен между рендерами" || fail "checksum нестабилен: $c1 / $c4"
[[ "$c1" != "$c2" ]] && pass "смена модели меняет checksum" || fail "смена модели не меняет checksum"
[[ "$c1" != "$c3" ]] && pass "смена ключа меняет checksum" || fail "смена ключа не меняет checksum"

echo "== umbrella hub-platform"
UMBRELLA="$ROOT/charts/hub-platform"
if helm dependency build "$UMBRELLA" >"$TMP/dep.log" 2>&1; then
  if helm template "$RELEASE" "$UMBRELLA" -n "$NS" >"$TMP/umbrella" 2>"$TMP/err"; then
    pass "рендер по умолчанию"
    got="$(env_of "$TMP/umbrella" worker LLM_BASE_URL)"
    [[ -z "$got" ]] && pass "по умолчанию AI-триаж выключен" || fail "umbrella: LLM_BASE_URL=$got"
  else
    cat "$TMP/err"; fail "umbrella: рендер по умолчанию упал"
  fi
  if helm template "$RELEASE" "$UMBRELLA" -n "$NS" \
      --set hub.llm.enabled=true --set hub.llm.baseUrl=https://llm.example.com/v1 >"$TMP/umbrella" 2>"$TMP/err"; then
    got="$(env_of "$TMP/umbrella" worker LLM_API_KEY)"
    [[ "$got" == "secret:$RELEASE-hub-secrets/llmApiKey" ]] && pass "hub.llm.enabled: ключ из $RELEASE-hub-secrets" || fail "umbrella: LLM_API_KEY=$got"
  else
    cat "$TMP/err"; fail "umbrella: рендер с hub.llm.enabled упал"
  fi
  if helm template "$RELEASE" "$UMBRELLA" -n "$NS" -f "$UMBRELLA/values-poc.yaml" >/dev/null 2>"$TMP/err"; then
    pass "рендер values-poc.yaml"
  else
    cat "$TMP/err"; fail "umbrella: values-poc.yaml"
  fi
else
  cat "$TMP/dep.log"; fail "helm dependency build hub-platform"
fi

echo
if (( fails > 0 )); then echo "провалено проверок: $fails"; exit 1; fi
echo "все проверки пройдены"
