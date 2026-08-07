#!/usr/bin/env bash
# 3-register-peers.sh — append [Peer] blocks to the WG server config and reload.
#
# Run this on the WG SERVER. Takes the wg-server-peers.txt produced by
# 2-generate-clients.sh and appends each [Peer] block to /etc/wireguard/wg0.conf
# (after de-duplicating by PublicKey), then live-reloads with `wg syncconf`.
#
# Usage: sudo ./3-register-peers.sh <path-to-wg-server-peers.txt>

set -euo pipefail

PEERS_FILE="${1:-}"
WG_DIR="${WG_DIR:-/etc/wireguard}"
WG_IFACE="${WG_IFACE:-wg0}"
CONF="${WG_DIR}/${WG_IFACE}.conf"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root (sudo)." >&2
  exit 1
fi

if [[ -z "$PEERS_FILE" || ! -f "$PEERS_FILE" ]]; then
  echo "Usage: sudo $0 <path-to-wg-server-peers.txt>" >&2
  exit 1
fi

if [[ ! -f "$CONF" ]]; then
  echo "${CONF} not found. Did you run 1-setup-server.sh first?" >&2
  exit 1
fi

# Backup
cp -p "$CONF" "${CONF}.bak.$(date +%Y%m%d%H%M%S)"

# Strict allowlist for [Peer] block lines — refuse to append PostUp/PreUp/etc that
# would execute as root on next 'wg-quick down/up'. Only PublicKey, AllowedIPs,
# Endpoint, PresharedKey, PersistentKeepalive, comments, and blank lines are kept.
validate_peer_block() {
  while IFS= read -r line; do
    case "$line" in
      ""|"#"*|"["[Pp]"eer]"|\
      "PublicKey"*|"PresharedKey"*|"AllowedIPs"*|\
      "Endpoint"*|"PersistentKeepalive"*) ;;
      *)
        echo "REJECT: unexpected directive in peers file: '$line'" >&2
        return 1 ;;
    esac
  done
  return 0
}

# Extract existing PublicKeys to avoid duplicates
existing="$(awk -F'=' '/^PublicKey/ {gsub(/ /,"",$2); print $2}' "$CONF" || true)"

# Stream the peers file, split on '[Peer]' headers, validate each block, then
# append unique ones via NUL-delimited reads (paragraph-mode awk → bash while).
added=0
skipped=0
rejected=0

while IFS= read -r -d '' block; do
  [[ -z "${block// /}" ]] && continue

  if ! validate_peer_block <<< "$block"; then
    rejected=$((rejected + 1))
    continue
  fi

  pub="$(awk -F'=' '/^PublicKey/ {gsub(/ /,"",$2); print $2; exit}' <<< "$block")"
  if [[ -z "$pub" ]]; then
    echo "  ! peer block missing PublicKey — skipping"
    rejected=$((rejected + 1))
    continue
  fi

  if grep -qF "$pub" <<< "$existing"; then
    echo "  - skip (already registered): ${pub:0:24}..."
    skipped=$((skipped + 1))
  else
    printf '\n%s\n' "$block" >> "$CONF"
    echo "  + added: ${pub:0:24}..."
    added=$((added + 1))
  fi
done < <(awk -v RS='' -v ORS='\0' 'NR > 1 || /^\[Peer\]/' "$PEERS_FILE")

# Live-reload (no interface flap, scanners stay connected)
wg syncconf "$WG_IFACE" <(wg-quick strip "$WG_IFACE")

echo
echo "================================================================"
echo "Done. Added ${added}, skipped ${skipped}, rejected ${rejected}."
echo "Backup: ${CONF}.bak.*"
echo "Active peers:"
wg show "$WG_IFACE" peers
echo "================================================================"
