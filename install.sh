#!/usr/bin/env bash
# install.sh — голая Linux-машина → полностью развёрнутый Security Hub одной командой.
#
# Что делает (идемпотентно — можно перезапускать сколько угодно):
#   1. Ставит k3s (если ещё не стоит) с --disable traefik|без него — зависит от --ingress.
#   2. Ставит helm (если ещё нет).
#   3. Ставит ingress controller (traefik идёт с k3s; nginx — через helm если --ingress nginx).
#   4. Ставит cert-manager.
#   5. helm install hub charts/hub-platform с выбранными TLS / domain / WG.
#
# Использование:
#   sudo ./install.sh                                        # все дефолты
#   sudo ./install.sh --domain mycorp.io --tls letsencrypt --le-email me@x.io
#   sudo ./install.sh --ingress nginx --tls selfsigned
#   sudo ./install.sh --wg-values ./wg-values.yaml           # WG egress
#   sudo ./install.sh --domain hub.poc.local \                # POC-стенд
#        --values charts/hub-platform/values-poc.yaml
#   sudo ./install.sh --dns "10.0.0.53 10.0.0.54"            # свой DNS (внутр. инфра)
#   sudo ./install.sh --no-dns-fix                           # не трогать CoreDNS
#
# Флаги DNS:
#   --dns "<ip> [ip...]"  DNS-резолверы для CoreDNS (по умолчанию 1.1.1.1 8.8.8.8).
#                         Задайте свои внутренние резолверы, если сканируете
#                         ВНУТРЕННЮЮ инфраструктуру (split-horizon, корпоративные
#                         зоны), а не только публичный периметр.
#   --no-dns-fix          Не патчить CoreDNS (если DNS в кластере уже настроен).
#
# Через env-vars (как альтернатива флагам):
#   DOMAIN, TLS_MODE, LE_EMAIL, INGRESS_CLASS, RELEASE, NAMESPACE, WG_VALUES,
#   DNS_UPSTREAMS, DNS_FIX

set -euo pipefail

# Дефолты
DOMAIN="${DOMAIN:-hub.example.com}"
TLS_MODE="${TLS_MODE:-selfsigned}"            # selfsigned | letsencrypt | existing | disabled
LE_EMAIL="${LE_EMAIL:-admin@example.com}"
INGRESS_CLASS="${INGRESS_CLASS:-traefik}"     # traefik | nginx
RELEASE="${RELEASE:-hub}"
NAMESPACE="${NAMESPACE:-hub}"
WG_VALUES="${WG_VALUES:-}"
SKIP_K3S="${SKIP_K3S:-0}"
SKIP_CERT_MANAGER="${SKIP_CERT_MANAGER:-0}"
# Доп. values-файлы (повторяемый флаг -f/--values). Применяются ПЕРЕД --set,
# поэтому операторские --set (domain/tls/ingress) имеют приоритет над файлом.
# Пример (POC): --values charts/hub-platform/values-poc.yaml
EXTRA_VALUES=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --domain)        DOMAIN="$2"; shift 2 ;;
    --tls)           TLS_MODE="$2"; shift 2 ;;
    --le-email)      LE_EMAIL="$2"; shift 2 ;;
    --ingress)       INGRESS_CLASS="$2"; shift 2 ;;
    --release)       RELEASE="$2"; shift 2 ;;
    --namespace|-n)  NAMESPACE="$2"; shift 2 ;;
    --values|-f)     EXTRA_VALUES+=("$2"); shift 2 ;;
    --wg-values)     WG_VALUES="$2"; shift 2 ;;
    --dns)           DNS_UPSTREAMS="$2"; shift 2 ;;
    --no-dns-fix)    DNS_FIX=0; shift ;;
    --skip-k3s)      SKIP_K3S=1; shift ;;
    --skip-cert-manager) SKIP_CERT_MANAGER=1; shift ;;
    -h|--help)
      sed -n '2,/^$/p' "$0"; exit 0 ;;
    *)
      echo "Неизвестный аргумент: $1" >&2; exit 1 ;;
  esac
done

if [[ "${EUID}" -ne 0 ]]; then
  echo "Запустите от root (скрипт пишет в /etc/rancher и /usr/local/bin)." >&2
  exit 1
fi

log() { printf "\n\033[1;32m==> %s\033[0m\n" "$*"; }
warn() { printf "\033[1;33m!! %s\033[0m\n" "$*"; }

# Не даём зарегистрировать LE-аккаунт на дефолтный email (заглушка)
if [[ "$TLS_MODE" == "letsencrypt" && "$LE_EMAIL" == "admin@example.com" ]]; then
  echo "FATAL: --tls letsencrypt требует --le-email <реальный-адрес>." >&2
  echo "       admin@example.com — placeholder, привяжет LE-аккаунт к чужому ящику." >&2
  exit 1
fi

# -----------------------------------------------------------------------------
# 1. k3s
# -----------------------------------------------------------------------------
if [[ "$SKIP_K3S" -eq 0 ]]; then
  if ! command -v k3s >/dev/null; then
    log "Устанавливаю k3s (ingress=${INGRESS_CLASS})..."
    K3S_DISABLE=""
    if [[ "$INGRESS_CLASS" == "nginx" ]]; then
      K3S_DISABLE="--disable traefik"
    fi
    curl -sfL https://get.k3s.io | sh -s - $K3S_DISABLE --write-kubeconfig-mode 644
  else
    log "k3s уже установлен — пропускаю инсталлер."
  fi
fi

export KUBECONFIG="${KUBECONFIG:-/etc/rancher/k3s/k3s.yaml}"

# Ждём готовность k3s API
log "Жду k3s API..."
for i in {1..60}; do
  if kubectl get nodes >/dev/null 2>&1; then break; fi
  sleep 2
done
kubectl get nodes

# -----------------------------------------------------------------------------
# 1.5. DNS-фикс для CoreDNS (k3s + systemd-resolved)
# -----------------------------------------------------------------------------
# Типовой баг: нода использует systemd-resolved, /etc/resolv.conf указывает на
# stub 127.0.0.53. CoreDNS по умолчанию форвардит «. /etc/resolv.conf» → на этот
# stub, недостижимый из подов → поды НЕ резолвят внешние домены (сканеры не
# находят цели, образы из публичных реестров могут не тянуться). Чиним: форвардим
# CoreDNS на надёжный публичный DNS. Идемпотентно. Отключить: DNS_FIX=0.
#
# ВАЖНО: форвардим на ПУБЛИЧНЫЙ DNS (1.1.1.1 8.8.8.8), а НЕ на upstream ноды.
# Upstream ноды часто бывает captive/wildcard-резолвером (DNS NAT-гипервизора,
# corporate-резолвер с поиском по своему домену): он отдаёт мусорные A-записи на
# несуществующие имена (*.localdomain → случайный IP) и может ломать резолв
# публичных целей сканера. Сканер по природе резолвит ВНЕШНИЕ домены, поэтому
# публичный DNS — правильный дефолт. Если нужен внутренний DNS (split-horizon,
# air-gapped) — задайте свой: DNS_UPSTREAMS="10.0.0.53 10.0.0.54".
DNS_FIX="${DNS_FIX:-1}"
DNS_UPSTREAMS="${DNS_UPSTREAMS:-1.1.1.1 8.8.8.8}"
if [[ "$DNS_FIX" -eq 1 ]]; then
  if grep -q '127.0.0.53' /etc/resolv.conf 2>/dev/null; then
    UPSTREAMS="$DNS_UPSTREAMS"
    CURRENT=$(kubectl -n kube-system get cm coredns -o jsonpath='{.data.Corefile}' 2>/dev/null || true)
    if echo "$CURRENT" | grep -q 'forward . /etc/resolv.conf'; then
      log "Чиню CoreDNS: forward → ${UPSTREAMS}(stub 127.0.0.53 недостижим из подов)..."
      # Чистый shell без python: берём ConfigMap как YAML, меняем forward-строку,
      # применяем через replace (k3s создаёт CM не через apply, поэтому apply
      # ругается на отсутствие last-applied-configuration — replace такого не
      # требует). forward-директива в Corefile уникальна.
      kubectl -n kube-system get cm coredns -o yaml \
        | sed "s#forward \. /etc/resolv.conf#forward . ${UPSTREAMS}#" \
        | kubectl -n kube-system replace -f - >/dev/null
      kubectl -n kube-system rollout restart deploy/coredns >/dev/null 2>&1 || true
      # Дожидаемся перезапуска CoreDNS ДО установки приложения. Иначе сканер
      # стартует, пока CoreDNS ещё перезагружается, первый discovery-цикл не
      # резолвит домены (0 целей) и повторяет попытку только через
      # TIME_LOOP_DISCOVERY (по умолчанию 6 ч) — пользователь видит «нет находок».
      kubectl -n kube-system rollout status deploy/coredns --timeout=90s >/dev/null 2>&1 || true
    fi
  fi
fi

# -----------------------------------------------------------------------------
# 2. helm
# -----------------------------------------------------------------------------
if ! command -v helm >/dev/null; then
  log "Устанавливаю helm..."
  curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
fi
helm version --short

# -----------------------------------------------------------------------------
# 3. Ingress controller (nginx — только если выбран; traefik уже идёт с k3s)
# -----------------------------------------------------------------------------
if [[ "$INGRESS_CLASS" == "nginx" ]]; then
  log "Устанавливаю ingress-nginx..."
  helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx >/dev/null 2>&1 || true
  helm repo update >/dev/null
  helm upgrade --install ingress-nginx ingress-nginx/ingress-nginx \
    --namespace ingress-nginx --create-namespace \
    --set controller.service.type=NodePort \
    --set controller.service.nodePorts.http=80 \
    --set controller.service.nodePorts.https=443
fi

# -----------------------------------------------------------------------------
# 4. cert-manager
# -----------------------------------------------------------------------------
if [[ "$SKIP_CERT_MANAGER" -eq 0 && "$TLS_MODE" != "disabled" && "$TLS_MODE" != "existing" ]]; then
  log "Устанавливаю cert-manager..."
  helm repo add jetstack https://charts.jetstack.io >/dev/null 2>&1 || true
  helm repo update >/dev/null
  helm upgrade --install cert-manager jetstack/cert-manager \
    --namespace cert-manager --create-namespace \
    --set installCRDs=true \
    --wait --timeout=5m
fi

# -----------------------------------------------------------------------------
# 5. hub-platform
# -----------------------------------------------------------------------------
log "Собираю зависимости umbrella-чарта..."
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
helm dependency update "${SCRIPT_DIR}/charts/hub-platform"

log "Устанавливаю hub-platform (release=${RELEASE}, ns=${NAMESPACE})..."
HELM_ARGS=(
  upgrade --install "${RELEASE}" "${SCRIPT_DIR}/charts/hub-platform"
  --namespace "${NAMESPACE}" --create-namespace
  # post-install hook seed-admin ждёт, пока backend домигрирует БД. На медленном
  # старте (эмуляция amd64 на arm, холодный pull образов) дефолтные 5 мин helm
  # не хватает → "post-install hooks failed". Даём запас. Переопределить:
  # HELM_TIMEOUT=30m ./install.sh
  --timeout "${HELM_TIMEOUT:-15m}"
  --set "global.domain=${DOMAIN}"
  --set "domain=${DOMAIN}"
  --set "ingress.className=${INGRESS_CLASS}"
  --set "tls.mode=${TLS_MODE}"
  --set "tls.letsencryptEmail=${LE_EMAIL}"
  --set "hub.ingress.className=${INGRESS_CLASS}"
  --set "openvas.ingress.className=${INGRESS_CLASS}"
  --set "zap.ingress.className=${INGRESS_CLASS}"
  --set "hub.tls.mode=${TLS_MODE}"
  --set "openvas.tls.mode=${TLS_MODE}"
  --set "zap.tls.mode=${TLS_MODE}"
)

# Доп. values-файлы (-f/--values). helm: --set всегда приоритетнее -f, поэтому
# операторские --set выше (domain/tls/ingress) переопределяют значения из файла.
for _vf in "${EXTRA_VALUES[@]:-}"; do
  [[ -n "$_vf" ]] || continue
  [[ -f "$_vf" ]] || { echo "values-файл не найден: $_vf" >&2; exit 1; }
  log "Подключаю values-файл: ${_vf}"
  HELM_ARGS+=(-f "$_vf")
done

if [[ -n "$WG_VALUES" && -f "$WG_VALUES" ]]; then
  log "Подключаю WireGuard egress из ${WG_VALUES}..."
  HELM_ARGS+=(
    -f "$WG_VALUES"
    --set "wireguard.enabled=true"
    --set "domainscope.wireguard.enabled=true"
    --set "openvas.wireguard.enabled=true"
    --set "zap.wireguard.enabled=true"
  )
fi

helm "${HELM_ARGS[@]}"

# -----------------------------------------------------------------------------
# Готово — печатаем дружественный summary с креденшалами
# -----------------------------------------------------------------------------
log "Готово. Состояние подов:"
kubectl -n "${NAMESPACE}" get pods -l "app.kubernetes.io/instance=${RELEASE}" -o wide || true

# Достаём сгенерированные секреты (если они уже есть в кластере)
HUB_ADMIN_PWD=$(kubectl -n "${NAMESPACE}" get secret "${RELEASE}-hub-secrets" -o jsonpath='{.data.localAdminPassword}' 2>/dev/null | base64 -d 2>/dev/null || echo "<not-yet-generated>")
HUB_DB_PWD=$(kubectl -n "${NAMESPACE}" get secret "${RELEASE}-hub-secrets" -o jsonpath='{.data.dbPassword}' 2>/dev/null | base64 -d 2>/dev/null || echo "<not-yet>")
OPENVAS_PWD=$(kubectl -n "${NAMESPACE}" get secret "${RELEASE}-openvas-secrets" -o jsonpath='{.data.adminPassword}' 2>/dev/null | base64 -d 2>/dev/null || echo "<not-yet>")
ZAP_KEY=$(kubectl -n "${NAMESPACE}" get secret "${RELEASE}-zap-secrets" -o jsonpath='{.data.apiKey}' 2>/dev/null | base64 -d 2>/dev/null || echo "<not-yet>")
SA_TOKEN=$(kubectl -n "${NAMESPACE}" get secret "${RELEASE}-hub-secrets" -o jsonpath='{.data.defaultSAKeyPlain}' 2>/dev/null | base64 -d 2>/dev/null || echo "<not-yet>")

SCHEME="http"
[ "$TLS_MODE" != "disabled" ] && SCHEME="https"

# ANSI цвета (используем $'...' чтобы escape-коды интерпретировались тут же,
# а не оставались литералами в heredoc-выводе).
B=$'\033[1m'; G=$'\033[1;32m'; Y=$'\033[1;33m'; R=$'\033[1;31m'; C=$'\033[1;36m'; N=$'\033[0m'

# OpenVAS может быть отключён (например, в values-poc openvas.enabled=false).
# Печатаем OpenVAS-секции summary ТОЛЬКО если openvas реально развёрнут —
# иначе пользователь видит ссылку на несуществующий UI и пароль <not-yet>.
OPENVAS_SECTION=""; OPENVAS_FEED_SECTION=""
if kubectl -n "${NAMESPACE}" get secret "${RELEASE}-openvas-secrets" >/dev/null 2>&1; then
  OPENVAS_SECTION=$(printf '%s▶ OpenVAS UI%s     →  %s%s://openvas.%s/%s\n   Логин:   %sadmin%s\n   Пароль:  %s%s%s\n' \
    "$G" "$N" "$C" "$SCHEME" "$DOMAIN" "$N" "$B" "$N" "$B" "$OPENVAS_PWD" "$N")
  OPENVAS_FEED_SECTION=$(printf '%s⏳  OpenVAS feed init%s занимает ~10–30 минут (~5 GB). До завершения\n    OpenVAS-сканы не найдут уязвимостей. Прогресс:\n      kubectl -n %s get pod -l app.kubernetes.io/component=openvas\n' \
    "$Y" "$N" "$NAMESPACE")
fi

cat <<EOF

╔═══════════════════════════════════════════════════════════════════════╗
║                     Security Hub готов к работе                       ║
╚═══════════════════════════════════════════════════════════════════════╝

${G}▶ Hub Web UI${N}     →  ${C}${SCHEME}://${DOMAIN}/${N}
   Логин:   ${B}admin@localhost.local${N}
   Пароль:  ${B}${HUB_ADMIN_PWD}${N}

${OPENVAS_SECTION}
${G}▶ Service Tokens${N}
   Hub default SA token:   ${B}${SA_TOKEN}${N}
   ZAP API key:            ${B}${ZAP_KEY}${N}
   Hub Postgres password:  ${B}${HUB_DB_PWD}${N}

${R}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${N}
${R}⚠  ВНИМАНИЕ${N}: пароли и токены сгенерированы случайно при первой
   установке и сохранены в ${B}${RELEASE}-*-secrets${N} (k8s Secrets).
   Смените пароль admin@localhost.local в Hub UI ${B}СРАЗУ${N}.
${R}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${N}

${OPENVAS_FEED_SECTION}
${Y}⏳  Default project${N}: автосоздан проект «${B}$(kubectl -n "${NAMESPACE}" get secret "${RELEASE}-hub-secrets" -o jsonpath='{.data.defaultProjectId}' 2>/dev/null | base64 -d 2>/dev/null || echo Default)${N}»
    с начальным scope, который можно поменять в hub UI или через helm:
      helm upgrade ${RELEASE} <chart> --reuse-values --set global.defaultProject.scope=foo.com,bar.com

${G}Полезные команды${N}
  kubectl -n ${NAMESPACE} get pods                       # состояние всех компонентов
  kubectl -n ${NAMESPACE} logs deploy/${RELEASE}-backend  # логи бэкенда
  kubectl -n ${NAMESPACE} logs deploy/${RELEASE}-domainscope-domainscope -c domainscope

EOF
