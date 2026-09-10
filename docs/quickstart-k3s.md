# Быстрый старт на k3s

Репозиторий с документацией включает **готовые Helm-чарты** всех компонентов и
**интерактивный установщик** — от голой Linux-VM до рабочего Security Hub.

## Что в репозитории

| Путь | Назначение |
|------|-----------|
| [`charts/`](https://github.com/s3m4rgl/hub-docs/tree/main/charts) | Helm-чарты: `security-scan-hub`, `domainscope`, `openvas`, `owasp-zap`, `netbox`, `hub-platform` (umbrella), `sshub-atlassian-secrets-scanner` |
| [`charts/hub-platform/values-poc.yaml`](https://github.com/s3m4rgl/hub-docs/blob/main/charts/hub-platform/values-poc.yaml) | Готовый overlay для **ознакомительного стенда**: захардкоженные секреты, scope `example.com`, TLS off, OpenVAS off |
| [`install.sh`](https://github.com/s3m4rgl/hub-docs/blob/main/install.sh) | Установщик на k3s (Traefik ingress, cert-manager, авто-фикс DNS, случайные пароли в Secrets) |

## Предварительные требования

- Linux-нода (Ubuntu 22.04/24.04, Debian 12 — проверено), root/sudo.
- 4 vCPU / 8 ГБ RAM / 40+ ГБ диска для полного стека (Hub + сканеры).
- Исходящий доступ в интернет (для образов и сканирования целей).

### ⚠ ARM-нода (Apple Silicon, Ampere, Raspberry Pi и т.п.)

Образы `dexionius/*` собираются под **linux/amd64**. На arm64-ноде они исполняются
через эмуляцию QEMU — нужно один раз поставить `binfmt`:

```bash
sudo apt-get update && sudo apt-get install -y qemu-user-static binfmt-support
sudo update-binfmts --enable qemu-x86_64
```

Проверка (должно вывести `enabled` и флаг `F`):

```bash
cat /proc/sys/fs/binfmt_misc/qemu-x86_64
```

Под эмуляцией сканер должен использовать nmap **connect-скан** (без raw-сокетов) —
это уже задано в `values-poc.yaml` (`domainscope.domainscope.env.scanType: connect`).

### Опционально: зеркало Docker Hub (медленный/ограниченный канал)

Если Docker Hub тянется медленно, пропишите pull-through зеркало для k3s
**до** установки (или перезапустите k3s после):

```bash
sudo mkdir -p /etc/rancher/k3s
sudo tee /etc/rancher/k3s/registries.yaml >/dev/null <<'EOF'
mirrors:
  docker.io:
    endpoint:
      - "https://<ваше-зеркало>"
EOF
```

## Установка ознакомительного стенда (Evaluation)

```bash
git clone https://github.com/s3m4rgl/hub-docs.git
cd hub-docs
sudo ./install.sh \
  --domain hub.poc.local \
  --tls disabled \
  --values charts/hub-platform/values-poc.yaml
```

Что делает установщик:

1. Ставит k3s (если ещё нет) + Traefik ingress.
2. Чинит CoreDNS, если нода на systemd-resolved (иначе поды не резолвят домены).
3. Ставит helm (если нет). При `--tls disabled` cert-manager не нужен.
4. `helm install hub charts/hub-platform` с overlay `values-poc.yaml`.

> Первый старт DomainScope занимает несколько минут: init-контейнер скачивает
> ~13000 nuclei-шаблонов (под эмуляцией на ARM — дольше). Пока статус
> `Init:0/1` — это нормально.

### DNS для сканирования

По умолчанию установщик настраивает CoreDNS на **публичный DNS** (`1.1.1.1 8.8.8.8`) —
это правильно для сканирования внешнего периметра. CoreDNS k3s по умолчанию
форвардит на stub `127.0.0.53` systemd-resolved, недостижимый из подов, поэтому
без этого шага сканер не резолвит цели.

Если на пилоте нужно сканировать **внутреннюю инфраструктуру** (внутренние зоны,
split-horizon DNS) — укажите свои резолверы:

```bash
sudo ./install.sh --domain hub.poc.local --tls disabled \
  --dns "10.0.0.53 10.0.0.54" \
  --values charts/hub-platform/values-poc.yaml
```

`--no-dns-fix` — не трогать CoreDNS (если DNS в кластере уже настроен правильно).

> `values-poc.yaml` намеренно содержит **захардкоженные** секреты и scope
> `example.com` — это только для ознакомления. Для production используйте
> собственные секреты (Vault / SealedSecrets) и не задавайте блок `secrets:`
> явно — umbrella сгенерирует случайные значения. См.
> [Kubernetes / Helm](deploy-kubernetes.md).

## Доступ к UI

`hub.poc.local` — не публичный домен, пропишите его в `/etc/hosts` машины,
с которой открываете браузер, указав IP ноды:

```bash
echo "<NODE_IP> hub.poc.local" | sudo tee -a /etc/hosts
```

Откройте `http://hub.poc.local/`:

- логин: `admin@localhost.local`
- пароль: значение `secrets.hubLocalAdminPassword` из `values-poc.yaml`
  (по умолчанию `PocAdmin_DO_NOT_USE_IN_PROD_2026`).

## Проверка: скан example.com

DomainScope автоматически забирает scope (`example.com`) из Hub Scope API,
сканирует и шлёт находки обратно. Прогресс:

```bash
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
kubectl -n hub get pods                       # все поды должны стать Running
kubectl -n hub logs -f deploy/hub-domainscope-domainscope -c domainscope
```

В логе появятся `scanning ip` и `open port`, затем `sarif report uploaded`.
Найденные открытые порты example.com появятся в Hub UI в продукте `example.com`
(раздел Findings). Скан под эмуляцией идёт медленнее — первые находки могут
занять несколько минут (discovery + connect-скан).

## Полный путь (Production)

Production-путь (реальный домен, TLS через Let's Encrypt, egress сканеров через
WireGuard на отдельной VPS, собственные секреты) — см.
[Kubernetes / Helm](deploy-kubernetes.md) и
[QUICKSTART.md](https://github.com/s3m4rgl/hub-docs/blob/main/QUICKSTART.md).

## Фиксация версии

Образы `dexionius/*` публикуются с версионными тегами. Чтобы запинить версию
задайте в значениях чарта явный тег вместо `latest`:

```yaml
image:
  tag: "0.33"
```


## Что дальше

Стенд поднят. Чтобы в нём появились находки — [Первые шаги после установки](first-steps.md).
