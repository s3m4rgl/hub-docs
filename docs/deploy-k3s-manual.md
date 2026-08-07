# Ручная установка на k3s

Тот же стенд, что и [быстрый старт](quickstart-k3s.md), но **каждый шаг
вручную** — для тех, кто хочет понимать и контролировать, что делает
[`install.sh`](https://github.com/s3m4rgl/hub-docs/blob/main/install.sh).
Команды ниже = ровно то, что выполняет скрипт.

Все шаги — от root (или через `sudo`). Проверено на Ubuntu 22.04/24.04, Debian 12.

## 0. Предварительные требования

### ARM-нода (Apple Silicon, Ampere, Raspberry Pi)

Образы `dexionius/*` собраны под linux/amd64 — на arm64 нужна эмуляция QEMU:

```bash
sudo apt-get update && sudo apt-get install -y qemu-user-static binfmt-support
sudo update-binfmts --enable qemu-x86_64
cat /proc/sys/fs/binfmt_misc/qemu-x86_64   # ждём enabled + флаг F
```

### Опционально: зеркало Docker Hub (медленный канал)

```bash
sudo mkdir -p /etc/rancher/k3s
sudo tee /etc/rancher/k3s/registries.yaml >/dev/null <<'EOF'
mirrors:
  docker.io:
    endpoint:
      - "https://<ваше-зеркало>"
EOF
```

> Файл должен лежать **до** установки k3s (k3s читает его при старте). Если k3s
> уже стоит — после правки `sudo systemctl restart k3s`.

## 1. Установка k3s

```bash
curl -sfL https://get.k3s.io | sh -s - --write-kubeconfig-mode 644
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
kubectl get nodes          # дождитесь STATUS=Ready
```

Traefik ingress идёт в комплекте с k3s — отдельно ставить не нужно.

## 2. Фикс DNS для CoreDNS

Если нода использует systemd-resolved (типично для Ubuntu/Debian),
`/etc/resolv.conf` указывает на stub `127.0.0.53`, недостижимый из подов.
CoreDNS по умолчанию форвардит на него → поды не резолвят домены → **сканер не
найдёт цели**. Проверка:

```bash
grep 127.0.0.53 /etc/resolv.conf && echo "нужен фикс DNS"
```

Перенаправьте CoreDNS на публичный DNS (для сканирования внешнего периметра)
или на свои внутренние резолверы (для внутренней инфры):

```bash
# DNS-резолверы: публичные для внешнего периметра, либо свои внутренние
DNS_UPSTREAMS="1.1.1.1 8.8.8.8"        # для внутренней инфры: "10.0.0.53 10.0.0.54"

# Чистый shell: берём ConfigMap как YAML, меняем forward-строку, применяем обратно.
kubectl -n kube-system get cm coredns -o yaml \
  | sed "s#forward . /etc/resolv.conf#forward . ${DNS_UPSTREAMS}#" \
  | kubectl -n kube-system replace -f -
kubectl -n kube-system rollout restart deploy/coredns
kubectl -n kube-system rollout status deploy/coredns   # дождитесь готовности ДО следующего шага
```

> Дождитесь готовности CoreDNS перед установкой приложения — иначе первый
> discovery-цикл сканера стартует без DNS, не найдёт целей и повторит попытку
> только через `TIME_LOOP_DISCOVERY`.

## 3. Установка helm

```bash
curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
helm version --short
```

## 4. (Опционально) cert-manager — только если нужен TLS

Для ознакомления TLS можно не включать (`tls.mode: disabled`, Hub по HTTP) —
тогда **пропустите этот шаг**. Для `selfsigned`/`letsencrypt`:

```bash
helm repo add jetstack https://charts.jetstack.io && helm repo update
helm upgrade --install cert-manager jetstack/cert-manager \
  --namespace cert-manager --create-namespace \
  --set crds.enabled=true --wait --timeout=8m
```

## 5. Установка hub-platform

```bash
git clone https://github.com/s3m4rgl/hub-docs.git
cd hub-docs

# Собрать зависимости umbrella-чарта (подтянет subchart'ы)
helm dependency update charts/hub-platform

# Установка с overlay ознакомительного стенда (захардкоженные секреты,
# scope example.com, TLS off, OpenVAS off)
helm upgrade --install hub charts/hub-platform \
  --namespace hub --create-namespace \
  --set global.domain=hub.poc.local \
  --set domain=hub.poc.local \
  --set tls.mode=disabled \
  --set hub.tls.mode=disabled \
  --set zap.tls.mode=disabled \
  -f charts/hub-platform/values-poc.yaml
```

> Для production не используйте `values-poc.yaml` (там публичные секреты).
> Соберите свой `values.yaml` без блока `secrets:` (umbrella сгенерирует
> случайные) и с `tls.mode: selfsigned`/`letsencrypt`. См.
> [Kubernetes / Helm](deploy-kubernetes.md) и
> [справочник переменных](env-domainscope.md).

## 6. Доступ к UI

`hub.poc.local` — не публичный домен; пропишите в `/etc/hosts` машины с браузером:

```bash
echo "<NODE_IP> hub.poc.local" | sudo tee -a /etc/hosts
```

Откройте `http://hub.poc.local/` — логин `admin@localhost.local`, пароль =
`secrets.hubLocalAdminPassword` из `values-poc.yaml`.

## 7. Проверка: скан example.com

```bash
kubectl -n hub get pods                       # дождитесь Running (первый старт
                                              # DomainScope тянет ~13000 nuclei-
                                              # шаблонов — статус Init:0/1 это норма)
kubectl -n hub logs -f deploy/hub-domainscope-domainscope -c domainscope
```

В логе появятся `scanning ip` → `open port` → `sarif report uploaded`. Найденные
открытые порты example.com — в Hub UI, продукт `example.com`, раздел Findings.

## Соответствие шагов и install.sh

| Шаг | Флаг install.sh |
|-----|-----------------|
| 1. k3s | автоматически (или `--skip-k3s`) |
| 2. DNS-фикс | автоматически (`--dns "<ip...>"` / `--no-dns-fix`) |
| 3. helm | автоматически |
| 4. cert-manager | по `--tls` (пропускается при `--tls disabled`) |
| 5. hub-platform | `--values`, `--domain`, `--tls` |
