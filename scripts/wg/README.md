# WireGuard egress для сканеров hub-platform

Когда сетевые сканеры hub-platform (DomainScope, OpenVAS, OWASP ZAP) ходят
в публичный интернет, обычно нужно чтобы их трафик уходил через **выделенный
egress-IP**, а не через IP k3s-ноды. Зачем:

1. Стабильный scan-source IP — клиент может его захайтлистить.
2. Реальный адрес вашего кластера не светится в логах целей.
3. Переезд / пересоздание ноды не меняет egress IP.

В этой папке лежат три скрипта, которые поднимают WG egress в правильном
порядке и решают проблему взаимной зависимости «клиенту нужен публичный
ключ сервера, серверу нужны публичные ключи клиентов».

## Топология

```
  ┌────────────────────────┐
  │  Kubernetes-кластер    │
  │                        │
  │  domainscope ─┐        │
  │  openvas     ─┼─wg0─┐  │
  │  zap         ─┘     │  │
  └─────────────────────│──┘
                        │ UDP/51820
                        ▼
                ┌─────────────────┐
                │   WG-VPS        │
                │  (10.200.0.1)   │
                │  NAT/MASQUERADE │
                │       │         │
                │       ▼         │
                │   public IP     │
                └─────────────────┘
                        │
                        ▼
                  цели сканирования
```

Каждый scanner-pod получает свой `/32` в `10.200.0.0/24`:

- `domainscope: 10.200.0.2`
- `openvas: 10.200.0.3`
- `zap: 10.200.0.4`

## Что нужно

**WG-нода** (отдельная VPS, не та же что k3s):

- Публичный IPv4-адрес (или NAT с проброшенным UDP/51820 наружу).
- Linux-ядро ≥ 5.6 ИЛИ установленный `wireguard-dkms` для старых ядер.
- Root-доступ.

**Операторская машина** (откуда раскатываете — может быть Hub-нода или ноут):

- `wireguard-tools` (`brew install wireguard-tools` на macOS,
  `apt install wireguard-tools` на Debian/Ubuntu, аналог в RHEL).
- `helm` и `kubectl`, настроенные на ваш кластер.

## Порядок действий

WG имеет взаимную зависимость: серверу нужны публичные ключи клиентов в
конфиге, а клиентам нужен публичный ключ сервера. Разрешается за три фазы.

### Фаза 1 — поднять сервер

На WG-ноде:

```bash
sudo bash scripts/wg/1-setup-server.sh
# Опциональные ENV-перекрытия (если 51820 занят / WG-сеть конфликтует с вашей):
#   WG_PORT=51820 WG_NETWORK=10.200.0.0/24 sudo bash scripts/wg/1-setup-server.sh
```

Скрипт:

- Ставит `wireguard-tools`.
- Генерит keypair сервера (`/etc/wireguard/server.priv`, `server.pub`).
- Пишет `/etc/wireguard/wg0.conf` с NAT/MASQUERADE для WG-сети.
- Включает `net.ipv4.ip_forward=1`.
- Запускает `wg-quick@wg0` через systemd.

В конце печатает **публичный ключ сервера** и **endpoint** (host:port) — скопируйте
обе строки, нужны на следующей фазе.

### Фаза 2 — сгенерировать клиентские ключи (на операторской машине)

```bash
bash scripts/wg/2-generate-clients.sh \
  --server-pubkey 'СЮДА_ПУБЛИЧНЫЙ_КЛЮЧ_СЕРВЕРА' \
  --server-endpoint '1.2.3.4:51820'
```

В текущей директории появится:

- `wg-clients/` — три приватных + публичных ключа (по одному на peer).
- `wg-values.yaml` — готовый Helm-блок для `--wg-values` или `-f`.
- `wg-server-peers.txt` — `[Peer]`-блоки для регистрации на сервере.

⚠️ К `wg-clients/*.priv` относитесь как к SSH-ключам. Потеряете — НЕ
восстановите.

### Фаза 3 — зарегистрировать peer'ы на сервере

Скопируйте `wg-server-peers.txt` на WG-ноду (например через `scp`), затем там:

```bash
sudo bash scripts/wg/3-register-peers.sh /path/to/wg-server-peers.txt
```

Скрипт:

- Делает бэкап `/etc/wireguard/wg0.conf` в `wg0.conf.bak.<timestamp>`.
- Дописывает каждый `[Peer]`-блок (дубликаты по PublicKey пропускает).
- Live-reload через `wg syncconf` — без флапа активного туннеля.

### Фаза 4 — установить или обновить hub-platform с включённым WG

На Hub-ноде / операторской машине:

```bash
helm install hub charts/hub-platform \
  -f wg-values.yaml \
  --set wireguard.enabled=true \
  --set domainscope.wireguard.enabled=true \
  --set openvas.wireguard.enabled=true \
  --set zap.wireguard.enabled=true \
  --create-namespace --namespace hub
```

Или через `install.sh` (он сам проставит все 4 флага):

```bash
sudo ./install.sh --domain ... --tls letsencrypt --le-email ... \
    --wg-values ./wg-values.yaml
```

Umbrella-чарт создаст три отдельных Secret'а
(`hub-domainscope-wireguard`, `hub-openvas-wireguard`, `hub-zap-wireguard`),
по одному на peer. В каждом scanner-pod'е init-контейнер `wg-setup` читает
свой Secret и поднимает `wg0` ДО того как стартанёт основной scanner-контейнер.

## Проверка туннеля

```bash
# Pods поднялись чисто:
kubectl get pods -n hub --selector=app.kubernetes.io/instance=hub

# Внутри scanner pod'а смотрим egress IP — должен быть = WG-сервера, не ноды:
kubectl exec -n hub deploy/hub-domainscope-domainscope -c domainscope -- \
    sh -c 'wget -qO- https://icanhazip.com'
kubectl exec -n hub hub-zap-0 -- \
    sh -c 'curl -s https://icanhazip.com'
kubectl exec -n hub deploy/hub-openvas -c gmp-bridge -- \
    sh -c 'curl -s https://icanhazip.com'

# На WG-сервере: 3 активных peer'а, у всех свежий handshake
sudo wg show wg0
```

Все три pod'а должны вернуть public IP WG-сервера. Если возвращают что-то
другое — туннель не работает (см. troubleshooting ниже).

## Добавить четвёртый сканер

Отредактируйте `scripts/wg/2-generate-clients.sh`:

```bash
PEERS=("domainscope:10.200.0.2" "openvas:10.200.0.3" "zap:10.200.0.4" "newone:10.200.0.5")
```

Перезапустите фазы 2 + 3 + `helm upgrade --wg-values ./wg-values.yaml`.

## Удалить peer

На WG-сервере удалите `[Peer]`-блок из `/etc/wireguard/wg0.conf` и
перезагрузи через:

```bash
sudo wg syncconf wg0 <(wg-quick strip wg0)
```

На операторской машине: в `wg-values.yaml` поставьте
`wireguard.peers.<name>.privateKey: ""` и сделайте `helm upgrade`.

## Диагностика проблем

**Scanner pod застрял в `Init:0/1` или `Init:CrashLoopBackOff`:**

- `kubectl logs -n hub <pod> -c wg-setup` — обычно peer не зарегистрирован
  на сервере. Перезапустите фазу 3.
- Видишь `RTNETLINK answers: File exists` — это бывает при предыдущих
  версиях чарта. Сейчас init-контейнер идемпотентный (`ip link del wg0` +
  `ip route replace`); если всё равно встречаете — обновите чарт до последней
  версии.

**`wg show` на сервере показывает peer но `latest handshake` пустой:**

- Endpoint сервера достижим из кластера? `kubectl exec ... -- nc -uvz <host> 51820`.
  Часто UDP/51820 закрыт на cloud-фаерволле (security group).
- `WG_NETWORK` пересекается с CIDR кластера (k3s по дефолту 10.42.0.0/16
  для pod'ов и 10.43.0.0/16 для service'ов)? Поменяйте `WG_NETWORK` в
  `1-setup-server.sh` (например на `10.220.0.0/24`).

**Egress IP из pod'а не совпадает с IP WG-сервера:**

- Проверьте что init-контейнер `wg-setup` отработал:
  `kubectl describe pod <pod> | grep -A20 wg-setup` — должен быть
  `State: Terminated, Reason: Completed, Exit Code: 0`.
- Если цель в RFC1918 (`10.0.0.0/8`, `172.16/12`, `192.168/16`) — она
  по дизайну идёт через дефолтный gateway, не через WG. Это специально
  чтобы не сломать внутрикластерные коннекты.

**На WG-сервере handshake идёт но трафик не выходит наружу:**

- Проверьте `iptables -t nat -L POSTROUTING` — должен быть MASQUERADE для
  WG-сети. `1-setup-server.sh` его прописывает; если ставил вручную,
  убедитесь что не пропустили.
- `sysctl net.ipv4.ip_forward` должен быть `1`.
