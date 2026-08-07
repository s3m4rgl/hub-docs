#!/usr/bin/env bash
# wipe-cluster.sh — полная очистка hub-неймспейса и его данных.
#
# Когда нужно:
#   - Сделать абсолютно чистый прогон установки (как у новой инсталляции).
#   - Сбросить замусоренные тестами поды/секреты/PVC после долгой отладки.
#
# Что делает:
#   1. helm uninstall hub (если установлен).
#   2. Удаляет namespace hub (с финализацией PVC).
#   3. Чистит PV и осиротевшие local-path директории на ноде.
#   4. (опц.) Удаляет cert-manager ClusterIssuer'ы из default.
#
# Использование:
#   sudo ./scripts/wipe-cluster.sh                    # без подтверждения, агрессивная чистка
#   sudo ./scripts/wipe-cluster.sh --keep-cert-manager
#   sudo ./scripts/wipe-cluster.sh --namespace hub --release hub
#
# Требует: kubectl, helm, доступ к /var/lib/rancher/k3s/storage (для local-path GC).

set -euo pipefail

NAMESPACE="${NAMESPACE:-hub}"
RELEASE="${RELEASE:-hub}"
KEEP_CERT_MANAGER="${KEEP_CERT_MANAGER:-0}"
LOCAL_PATH_ROOT="${LOCAL_PATH_ROOT:-/var/lib/rancher/k3s/storage}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --namespace|-n)         NAMESPACE="$2"; shift 2 ;;
    --release)              RELEASE="$2"; shift 2 ;;
    --keep-cert-manager)    KEEP_CERT_MANAGER=1; shift ;;
    --local-path-root)      LOCAL_PATH_ROOT="$2"; shift 2 ;;
    -h|--help)              sed -n '2,/^$/p' "$0"; exit 0 ;;
    *) echo "Неизвестный аргумент: $1" >&2; exit 1 ;;
  esac
done

if [[ "${EUID}" -ne 0 ]]; then
  echo "Запустите от root (нужно чистить /var/lib/rancher/k3s/storage)." >&2
  exit 1
fi

# k3s обычно ставит kubeconfig в /etc/rancher/k3s/k3s.yaml — подтянем
export KUBECONFIG="${KUBECONFIG:-/etc/rancher/k3s/k3s.yaml}"

log()  { printf "\n\033[1;32m==> %s\033[0m\n" "$*"; }
warn() { printf "\033[1;33m!! %s\033[0m\n" "$*"; }

# 1 — helm uninstall
if helm -n "$NAMESPACE" status "$RELEASE" >/dev/null 2>&1; then
  log "helm uninstall $RELEASE"
  helm -n "$NAMESPACE" uninstall "$RELEASE" || true
else
  warn "Релиз $RELEASE/$NAMESPACE не найден — пропускаю helm uninstall"
fi

# 2 — namespace
if kubectl get ns "$NAMESPACE" >/dev/null 2>&1; then
  log "Удаляю namespace $NAMESPACE (включая все PVC, secrets, jobs)"
  kubectl delete ns "$NAMESPACE" --wait=false || true
  # Ждём финализации PVC (max 60s) — иначе local-path не отпустит каталоги.
  for i in $(seq 1 30); do
    if ! kubectl get ns "$NAMESPACE" >/dev/null 2>&1; then
      break
    fi
    sleep 2
  done
  if kubectl get ns "$NAMESPACE" >/dev/null 2>&1; then
    warn "Namespace висит в Terminating — форсирую финалайзеры"
    kubectl get ns "$NAMESPACE" -o json \
      | jq '.spec.finalizers = []' \
      | kubectl replace --raw "/api/v1/namespaces/${NAMESPACE}/finalize" -f - || true
  fi
else
  warn "Namespace $NAMESPACE не существует — пропускаю"
fi

# 3 — Released PV (local-path не всегда GCить их сам)
log "Удаляю Released PV из ${NAMESPACE}"
released=$(kubectl get pv -o jsonpath="{range .items[?(@.spec.claimRef.namespace==\"${NAMESPACE}\")]}{.metadata.name} {end}" 2>/dev/null || true)
if [[ -n "$released" ]]; then
  # shellcheck disable=SC2086
  kubectl delete pv $released --ignore-not-found=true || true
else
  echo "    (нет PV для $NAMESPACE)"
fi

# 4 — local-path осиротевшие директории
# local-path-provisioner не всегда удаляет каталоги синхронно. Чистим вручную.
if [[ -d "$LOCAL_PATH_ROOT" ]]; then
  log "Чищу осиротевшие local-path-каталоги в $LOCAL_PATH_ROOT"
  # Имена PV-каталогов: pvc-<uuid>_<ns>_<pvc-name>
  found=0
  for d in "$LOCAL_PATH_ROOT"/pvc-*"${NAMESPACE}"*; do
    [[ -d "$d" ]] || continue
    found=1
    rm -rf "$d"
    echo "    удалён $d"
  done
  if [[ "$found" -eq 0 ]]; then
    echo "    (пусто, нечего чистить)"
  fi
else
  warn "$LOCAL_PATH_ROOT не существует — пропускаю local-path GC"
fi

# 4 — cert-manager
if [[ "$KEEP_CERT_MANAGER" -ne 1 ]]; then
  log "Удаляю ClusterIssuer'ы (selfsigned-issuer, letsencrypt)"
  kubectl delete clusterissuer selfsigned-issuer letsencrypt --ignore-not-found=true || true
fi

log "Готово. Кластер чист и готов к свежей установке:"
echo "    sudo ./install.sh --domain <your-domain> --tls selfsigned"
