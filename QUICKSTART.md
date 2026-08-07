# Быстрый старт — от голой VM до рабочего Security Hub

Инструкция проводит установку на свежем Linux-сервере. По итогу получим:

- k3s + Traefik ingress + cert-manager
- Hub UI (`https://hub.your-domain.tld`)
- OpenVAS Web UI (`https://openvas.hub.your-domain.tld`)
- DomainScope + ZAP, сшитые с Hub автоматически
- Все пароли сгенерированы случайно и сохранены в Kubernetes Secrets
- (опц.) Все egress сканеров — через WireGuard в отдельную VPS

## Два пути установки

| Путь              | Когда                        | Ноды             | Время                            |
| ----------------- | ---------------------------- | ---------------- | -------------------------------- |
| **A. Evaluation** | Демо, dev, air-gapped        | 1 (Hub)          | ~10 мин + 10–30 мин на feed init |
| **B. Production** | Реальные сканы внешних целей | 2 (Hub + WG-VPS) | ~15 мин + 10–30 мин на feed init |

**Если надо сканировать из "внешнего" адреса свой периметр — идите по пути B сразу.** Включить WG поверх
существующей evaluation-инсталляции тоже можно (`helm upgrade --wg-values …`),
но проще сделать всё с нуля правильно, чем потом мигрировать пароли и PVC.

## Требования

**Hub-нода** (один сервер):

- Linux (Ubuntu 22.04+, Debian 12+, RHEL/Rocky 9+).
- 4 vCPU, 8 GB RAM, 30 GB диска минимум (8 vCPU + 16 GB рекомендуется для OpenVAS).
- Root-доступ.
- Outbound-интернет (k3s, helm, контейнерные образы).

**WG-нода** (только для пути B — отдельная маленькая VPS):

- Любая Linux-VPS с публичным статическим IP.
- 1 vCPU, 512 MB RAM, 5 GB диска — этого с запасом.
- Открыт UDP/51820 в фаерволле/SG.
- Linux-ядро ≥ 5.6 (встроенный WG; в Ubuntu 22.04+ всё ок) ИЛИ установленный
  `wireguard-dkms` (для старых ядер).
- Root-доступ.

**Операторская машина** (откуда раскатывается — может быть Hub-нода или ноут):

- `wireguard-tools` для генерации ключей (`brew install wireguard-tools` /
  `apt install wireguard-tools`).
- Доступ по SSH к обеим нодам.

**DNS:**

- A-запись `hub.your-domain.tld` → IP Hub-ноды. Wildcard
  (`*.hub.your-domain.tld`) удобнее — OpenVAS UI поднимется на поддомене.
- Если публичного домена нет — пропустите DNS, используйте `--tls selfsigned` с
  любым именем и пропишите его в `/etc/hosts`.

---

## Путь A: Evaluation (без WireGuard)

### A.1. Клонировать и запустить установщик

На Hub-ноде:

```bash
git clone <your-fork-of-this-repo>.git hub-k3s-charts
cd hub-k3s-charts
sudo ./install.sh \
    --domain hub.your-domain.tld \
    --tls letsencrypt \
    --le-email admin@your-domain.tld
```

Установщик идемпотентен (можно перезапускать). Что делает (~5 минут):

1. Ставит k3s с Traefik.
2. Ставит helm и cert-manager.
3. `helm dependency update` для umbrella-чарта.
4. `helm upgrade --install hub charts/hub-platform` с TLS / domain.
5. Печатает summary с URL'ами и сгенерированными паролями.

Переходите к разделу [«Дальше»](#дальше) ниже.

---

## Путь B: Production (с WireGuard egress)

Egress всех трёх сканеров (DomainScope, OpenVAS, ZAP) пойдёт через WG-туннель
в отдельную VPS со статическим IP. Преимущества:

- Стабильный scan-source IP — клиент whitelist'ит один адрес.
- Адрес сканеров не совпадает с IP кластера; пересоздание ноды его не меняет.
- Скан-трафик отделён от control-plane-трафика кластера.

Установка идёт в **четыре фазы** — это одноразовая последовательность,
разрешающая взаимную зависимость «серверу нужны публичные ключи клиентов,
клиентам нужен публичный ключ сервера».

### B.1. Поднять WG-сервер

На WG-ноде (отдельной VPS):

```bash
# Скрипт вне репозитория не нужен — клонируем туда же
git clone <your-fork-of-this-repo>.git hub-k3s-charts
cd hub-k3s-charts
sudo bash scripts/wg/1-setup-server.sh
```

Скрипт ставит wireguard-tools, генерит серверный keypair, прописывает
NAT/MASQUERADE и `net.ipv4.ip_forward=1`, поднимает `wg-quick@wg0`. В конце
печатает:

- **Server public key** (например `js/6Wop2EFLzzi89CPTpNeP1nj0ekdQrzQcVJqGWQXo=`)
- **Endpoint** (например `185.147.83.236:51820`)

Запишите обе строки — нужны на следующем шаге.

### B.2. Сгенерировать клиентские ключи

На операторской машине (где есть `wireguard-tools` и доступ к Hub-ноде):

```bash
cd hub-k3s-charts
bash scripts/wg/2-generate-clients.sh \
    --server-pubkey 'js/6Wop2EFLzzi89CPTpNeP1nj0ekdQrzQcVJqGWQXo=' \
    --server-endpoint '185.147.83.236:51820'
```

Скрипт создаст:

- `wg-clients/{domainscope,openvas,zap}.{priv,pub}` — ключи на каждый peer
  (chmod 600). **Не теряйте приваты — они невосстановимы.**
- `wg-values.yaml` — готовый Helm-блок для `--wg-values …`.
- `wg-server-peers.txt` — `[Peer]`-блоки для регистрации на сервере.

### B.3. Зарегистрировать peer'ы на WG-сервере

Скопируйте `wg-server-peers.txt` на WG-ноду:

```bash
scp wg-server-peers.txt wg-vps:/tmp/
ssh wg-vps "sudo bash /home/<user>/hub-k3s-charts/scripts/wg/3-register-peers.sh /tmp/wg-server-peers.txt"
```

Скрипт делает бэкап `wg0.conf`, добавляет три `[Peer]`-блока (пропуская
дубликаты), и live-reload через `wg syncconf` (без флапа туннеля).

### B.4. Установить Hub с WG-туннелем

На Hub-ноде:

```bash
git clone <your-fork-of-this-repo>.git hub-k3s-charts
cd hub-k3s-charts

# Скопируйте wg-values.yaml сюда из операторской машины (если они разные)
scp operator:hub-k3s-charts/wg-values.yaml ./

sudo ./install.sh \
    --domain hub.your-domain.tld \
    --tls letsencrypt \
    --le-email admin@your-domain.tld \
    --wg-values ./wg-values.yaml
```

`install.sh` подхватит wg-values.yaml + проставит все 4 флага
(`wireguard.enabled=true` + `<scanner>.wireguard.enabled=true` для каждого
сабчарта).

При старте каждого scanner-pod'а init-контейнер `wg-setup` поднимает `wg0`
с per-peer privateKey, выставляет split routing (`0.0.0.0/1 + 128.0.0.0/1
dev wg0`, K8s-сети + RFC1918 через дефолтный gateway). Egress в публичный
интернет уходит через WG-туннель.

### B.5. Проверка туннеля

```bash
# На WG-сервере: должно быть 3 активных peer'а с свежим handshake
sudo wg show wg0

# В каждом scanner pod'е egress IP должен быть = WG-сервера, не нодов k3s
kubectl exec -n hub deploy/hub-domainscope-domainscope -c domainscope -- \
    sh -c 'wget -qO- https://icanhazip.com'
kubectl exec -n hub hub-zap-0 -- \
    sh -c 'curl -s https://icanhazip.com'
kubectl exec -n hub deploy/hub-openvas -c gmp-bridge -- \
    sh -c 'curl -s https://icanhazip.com'
```

Все три должны вернуть public IP WG-сервера.

---

## Дальше

(одинаково для пути A и B)

### Подождать инициализацию OpenVAS

OpenVAS на старте копирует ~5 ГБ фидов (VT, Notus, SCAP, CERT) из контейнерных
образов в свои PVC. Это **10–30 минут чистого ожидания**. Hub'ом можно
пользоваться раньше — OpenVAS-сканы просто не найдут уязвимостей пока init
не закончится.

```bash
kubectl -n hub get pod -l app.kubernetes.io/component=openvas
kubectl -n hub describe pod -l app.kubernetes.io/component=openvas | grep -A2 'Init Container'
```

### Первый логин

Откройте `https://hub.your-domain.tld/`.

Hub автосоздаёт админа `admin@localhost.local`. Пароль:

```bash
kubectl -n hub get secret hub-hub-secrets \
    -o jsonpath='{.data.localAdminPassword}' | base64 -d
```

OpenVAS-юзер `admin`:

```bash
kubectl -n hub get secret hub-openvas-secrets \
    -o jsonpath='{.data.adminPassword}' | base64 -d
```

В Hub UI создайте проект, добавьте домены в scope — DomainScope подхватит scope
через `/api/v1/projects/<id>/scope/export` и пойдёт сканировать. Результаты
будут стримиться в Hub через SARIF upload.

## Обновление

```bash
cd hub-k3s-charts
git pull
sudo ./install.sh --domain hub.your-domain.tld --tls letsencrypt --le-email admin@your-domain.tld
# или с --wg-values ./wg-values.yaml для пути B
```

Сгенерированные пароли и UUID'ы сохраняются между upgrade'ами благодаря
`helm.sh/resource-policy: keep` + `lookup` в чарте.

## Удаление

```bash
sudo ./scripts/wipe-cluster.sh         # полная очистка namespace + PVC + PV
# либо только helm-релиз:
helm -n hub uninstall hub
```

`wipe-cluster.sh` снимает release, удаляет namespace со всеми Secret'ами
(включая helm-keep'нутые), чистит Released PV и осиротевшие local-path
каталоги — после него можно ставить с нуля.

## Production checklist

- [ ] `--tls letsencrypt` с реальным email
- [ ] WG egress поднят (путь B) если сканируете третьи стороны
- [ ] Бэкапы PVC: hub-postgres, hub-openvas-vt-data + gvmd-data
- [ ] Поменять пароль `admin@localhost.local` сразу после первого входа
- [ ] (опц.) `--ingress nginx` если нужны его расширенные фичи
- [ ] (опц.) `AUTH_MODE=SSO` + Keycloak, Azure AD (Entra ID) или любой OIDC-провайдер (`SSO_PROVIDERS`, `OIDC_<NAME>_*`) — см. [06-integration-keycloak.md](docs/06-integration-keycloak.md)
- [ ] (опц.) Внешний managed PostgreSQL вместо in-cluster (`hub.postgres.enabled=false` + DSN в secrets)

## Диагностика проблем

**Поды зависли в `Pending`:**

```bash
kubectl -n hub describe pod <pod-name>
```

Обычно PVC не биндится — проверьте `kubectl get sc` и наличие `local-path`.

**Ingress 404 / cert error:**

- `kubectl get clusterissuer` — Issuer должен быть Ready.
- LE не отрабатывает — проверьте DNS A-запись; убедитесь что :80 доступен из
  публичного интернета (HTTP-01 challenge).

**OpenVAS pod в Init: задолго:**

- 10 init-контейнеров выкачивают ~5 ГБ фидов. Это нормально на первый запуск.
- `kubectl logs … -c <init-name>` — проверьте что нет out-of-disk.

**WG: scanner pod в `Init:CrashLoopBackOff`:**

- `kubectl logs <pod> -c wg-setup` — обычно peer не зарегистрирован на сервере
  (фаза B.3) или `WG_NETWORK` пересекается с k3s pod-CIDR (10.42.0.0/16).
  Подробнее — [scripts/wg/README.md#troubleshooting](scripts/wg/README.md#troubleshooting).

**WG: handshake не идёт:**

- На WG-сервере `sudo wg show wg0` показывает peer но `latest handshake` пустой.
- Проверьте что UDP/51820 открыт в фаерволле VPS (cloud SG, ufw, firewalld).
- `kubectl exec … -- nc -uvz <wg-vps-ip> 51820` из любого pod'а.

**Случайный секрет перегенерировался на `helm upgrade`:**

- Не должен. Если случилось — проверьте `helm.sh/resource-policy: keep` на
  master Secret'е (`hub-hub-secrets` etc). `helm template` / `--dry-run` ВСЕГДА
  рендерят свежие значения, потому что `lookup` работает только против живого
  кластера. Реальный `helm install` против существующего кластера подставит
  существующие значения.
