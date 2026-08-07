#!/usr/bin/env bash
# 1-setup-server.sh — bootstrap a WireGuard egress server.
#
# Run this on the BOX you want to use as the egress / NAT gateway for hub
# scanners (DomainScope, OpenVAS, ZAP). The server should have:
#   - A public IPv4 address (or NATed with port forwarded).
#   - Linux kernel >= 5.6 (or wireguard-dkms on older kernels).
#   - Root / sudo access.
#
# Output:
#   - /etc/wireguard/wg0.conf  (server config; only [Interface] block here, no peers)
#   - /etc/wireguard/server.pub  (server public key — copy to operator machine)
#   - /etc/sysctl.d/99-wireguard.conf  (enables IPv4 forwarding)
#
# Next step: run 2-generate-clients.sh on the operator machine.

set -euo pipefail

WG_DIR="${WG_DIR:-/etc/wireguard}"
WG_IFACE="${WG_IFACE:-wg0}"
WG_PORT="${WG_PORT:-51820}"
WG_NETWORK="${WG_NETWORK:-10.200.0.0/24}"
WG_SERVER_IP="${WG_SERVER_IP:-10.200.0.1/24}"
EGRESS_IFACE="${EGRESS_IFACE:-$(ip route show default | awk '/default/ {print $5; exit}')}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root (sudo)." >&2
  exit 1
fi

if ! command -v wg >/dev/null; then
  echo "Installing wireguard-tools..."
  if command -v apt-get >/dev/null; then
    apt-get update -y && apt-get install -y wireguard-tools
  elif command -v dnf >/dev/null; then
    dnf install -y wireguard-tools
  elif command -v yum >/dev/null; then
    yum install -y wireguard-tools
  else
    echo "Unsupported package manager. Install wireguard-tools manually and re-run." >&2
    exit 1
  fi
fi

mkdir -p "$WG_DIR"
chmod 700 "$WG_DIR"
cd "$WG_DIR"

if [[ -f "${WG_IFACE}.conf" ]]; then
  echo "${WG_DIR}/${WG_IFACE}.conf already exists. Refusing to overwrite." >&2
  echo "If you want to re-init, move the existing config aside first." >&2
  exit 1
fi

# Generate server keypair
umask 077
wg genkey | tee server.key | wg pubkey > server.pub

PRIV="$(cat server.key)"

cat > "${WG_IFACE}.conf" <<EOF
[Interface]
Address = ${WG_SERVER_IP}
ListenPort = ${WG_PORT}
PrivateKey = ${PRIV}

# Enable NAT for traffic egressing the WG tunnel
PostUp = iptables -A FORWARD -i %i -j ACCEPT; iptables -A FORWARD -o %i -j ACCEPT; iptables -t nat -A POSTROUTING -s ${WG_NETWORK} -o ${EGRESS_IFACE} -j MASQUERADE
PostDown = iptables -D FORWARD -i %i -j ACCEPT; iptables -D FORWARD -o %i -j ACCEPT; iptables -t nat -D POSTROUTING -s ${WG_NETWORK} -o ${EGRESS_IFACE} -j MASQUERADE

# --- Peers (added later by 3-register-peers.sh) ---
EOF

# Enable IPv4 forwarding (persist)
cat > /etc/sysctl.d/99-wireguard.conf <<EOF
net.ipv4.ip_forward = 1
EOF
sysctl --system >/dev/null

systemctl enable --now "wg-quick@${WG_IFACE}.service"

echo
echo "================================================================"
echo "WireGuard server up on UDP/${WG_PORT}, network ${WG_NETWORK}"
echo
echo "Server public key:"
cat server.pub
echo
echo "Endpoint to give clients (host:port):"
PUB_IP="$(curl -s -4 ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}')"
echo "  ${PUB_IP}:${WG_PORT}"
echo
echo "Next step: run scripts/wg/2-generate-clients.sh on the operator machine"
echo "with these values. Then come back and run 3-register-peers.sh here."
echo "================================================================"
