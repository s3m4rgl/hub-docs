# sshub-atlassian-secrets-scanner

Cron-сканер секретов в Jira/Confluence на базе [kingfisher](https://github.com/zyantific/kingfisher).
Образ: [`dexionius/sshub-atlassian-secrets-scanner`](https://hub.docker.com/r/dexionius/sshub-atlassian-secrets-scanner).

Чарт **standalone** — не входит в umbrella `hub-platform`. Cross-wire с
хабом идёт через четыре env-переменные (`HUB_URL`, `HUB_TOKEN`,
`HUB_JIRA_PROJECT`, `HUB_CONFLUENCE_PROJECT`) и не требует umbrella-сложности.
Ставится в свой namespace со своим жизненным циклом.

GitLab-сканирование намеренно **не включено** — оно остаётся на
легаси-bare-metal cron'е (см. `secret-scan-scripts/DEPLOY.md`).

## ⚠ Sensitivity warning

Сканер пишет SARIF-файлы, в которых **сами найденные секреты лежат в
plain-text** — это нужно, чтобы uploader смог отправить их в Hub с
оригинальным сниппетом. Файлы живут на `results`-PVC до
`config.cleanupMaxAgeDays` (по умолчанию 7 дней). Любой, у кого есть доступ
на чтение PVC (cluster-admin, snapshot, backup, exec в pod с тем же SA), —
получает «коллекцию» секретов клиента/сотрудников.

Что встроено в чарт:

- `runAsNonRoot: true` (uid 10001), `readOnlyRootFilesystem: true`,
  `capabilities.drop: [ALL]`, seccomp `RuntimeDefault`.
- Отдельный ServiceAccount с `automountServiceAccountToken: false` — pod
  не может звать k8s API.
- `helm.sh/resource-policy: keep` на Secret и PVC — но это о сохранности
  при `helm uninstall`, не про шифрование.

Что должны добавить вы (вне чарта):

- StorageClass с шифрованием at-rest (k3s `local-path` хранит plain-text
  на диске ноды). Для production — LUKS/CSI с шифрованием.
- Жёсткий RBAC на `secret get` и `pod exec` в namespace.
- Для high-sensitivity tenant'ов — агрессивный cleanup
  (`config.cleanupMaxAgeDays: "1"`).

## TL;DR — standalone установка

```bash
helm install scanner ./charts/sshub-atlassian-secrets-scanner \
  --namespace security-scans --create-namespace \
  --set secrets.hubToken="$HUB_TOKEN" \
  --set secrets.jiraToken="$KF_JIRA_TOKEN" \
  --set secrets.confluenceToken="$KF_CONFLUENCE_TOKEN" \
  --set config.hubUrl=https://hub.example.com \
  --set config.hubJiraProjectId=<UUID> \
  --set config.hubConfluenceProjectId=<UUID> \
  --set config.jiraUrl=https://jira.example.com \
  --set config.confluenceUrl=https://confluence.example.com
```

После установки `kubectl get -n security-scans cronjob,pvc,secret,sa` —
должны появиться: 4 CronJob (`jira`, `confluence`, `upload`, `cleanup`),
1 PVC (`results`), 1 Secret, 1 ServiceAccount.

`templates/NOTES.txt` после установки печатает текущие расписания, окно
сканирования и команды для smoke-теста через `kubectl create job --from=cronjob`.

## Что рендерится

```
1× ServiceAccount   <release>-sshub-atlassian-secrets-scanner
1× Secret           <release>-sshub-atlassian-secrets-scanner-secrets
1× PVC              <release>-sshub-atlassian-secrets-scanner-results  (RWO, по умолчанию 5Gi local-path)
4× CronJob          <release>-sshub-atlassian-secrets-scanner-{jira,confluence,upload,cleanup}
```

Второй PVC (для логов) рендерится только при `pvc.logs.enabled: true`
(обычно когда `config.logDestination` = `file` или `both`). Для
`stdout`-режима (по умолчанию) логи захватывает Kubernetes — отдельного
тома не нужно.

`concurrencyPolicy: Forbid` хардкодится на каждом CronJob — два запуска
одного типа не могут затоптать друг другу `.state.json`.

## Reference по values

**Источник правды — [`values.yaml`](values.yaml)**: там детальные
комментарии по каждому ключу. Здесь только обзор больших блоков:

| Блок                                                  | Что внутри                                                                                          |
| ----------------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| `image.*`                                             | Repository, tag (по умолчанию `0.1.0` — НЕ `latest`), pullPolicy, pullSecrets                       |
| `secrets.*`                                           | `create`, `existingSecretName`, три PAT-а (`hubToken`, `jiraToken`, `confluenceToken`)              |
| `config.*`                                            | URL'ы Hub/Jira/Confluence, UUID продуктов в Hub, окно сканирования, retention, log destination      |
| `cronjobs.{jira,confluence,upload,cleanup}.*`         | Schedule, suspend, resources, history limits, `activeDeadlineSeconds`                               |
| `pvc.{results,logs}.*`                                | Размер, StorageClass, accessModes                                                                   |
| `podSecurityContext`, `containerSecurityContext`      | Hardening (см. выше)                                                                                |
| `serviceAccount.*`                                    | Создание SA, имя override, аннотации                                                                |
| `nodeSelector`, `tolerations`, `affinity`, `extraEnv` | Прокидываются во все 4 CronJob                                                                      |

## Resolution секретов (3 уровня)

Helper [`chart.resolveToken`](templates/_helpers.tpl) на каждый из трёх
PAT-ов:

1. **Operator override** (`.Values.secrets.<key>`) — побеждает всегда.
2. **Существующий in-cluster Secret** — `lookup` по имени, `b64dec`. Этим
   токены переживают `helm upgrade`, даже если значение пропадает из
   values (например, после ручной `kubectl edit secret`).
3. **Пустая строка** — `required` в `secret.yaml` валит template с
   понятным сообщением `secrets.hubToken is required (Hub service-account API key)`.

Random fallback не подходит — это внешние API-токены, случайная строка
не пройдёт аутентификацию.

## Замечания про `helm template` / `--dry-run`

`lookup` возвращает `nil` вне живого кластера. На практике это значит:

- `helm template` без `--set secrets.*` падает на `required`-guard, даже
  если Secret уже есть в кластере. Для preview подавайте dummy-значения.
- При обычном `helm upgrade` против живого кластера — `lookup` работает
  и сохраняет токены между апгрейдами без повторной передачи.
- В GitOps-пути (ArgoCD + AVP) `<path:kv/data/scans/prod#…>`-плейсхолдеры
  резолвятся плагином **до** `lookup`, поэтому `required` всегда видит
  настоящие значения на sync'е.

Доп. защита: `secret.yaml` падает быстро, если в строках остался
`<path:`-префикс. Это значит, что AVP не отработал, и без guard'а в
`Secret.stringData` записалась бы plain-text путёвка к Vault. Сообщение:

```
secrets.hubToken contains an unresolved AVP placeholder
"<path:kv/data/scans/prod#hubToken>". Install argocd-vault-plugin or
use values.yaml with literal tokens.
```

## GitOps-путь (ArgoCD + Vault AVP)

В чарте лежит [`values-gitops.yaml`](values-gitops.yaml) с
`<path:kv/data/scans/prod#…>`-плейсхолдерами. Прежде чем AppSet синканёт,
заполните Vault:

```
kv/scans/prod
  hubToken               <hub SA API key>
  jiraToken              <Jira PAT>
  confluenceToken        <Confluence PAT>
  hubUrl                 https://hub.example.com
  hubJiraProjectId       <UUID>
  hubConfluenceProjectId <UUID>
  jiraUrl                https://jira.example.com
  confluenceUrl          https://confluence.example.com
```

Полная инструкция по AVP — [`bootstrap/README.md`](../../bootstrap/README.md).
ApplicationSet — [`appsets/sshub-atlassian-secrets-scanner.yaml`](../../appsets/sshub-atlassian-secrets-scanner.yaml).
Per-env override — [`environments/prod/sshub-atlassian-secrets-scanner.yaml`](../../environments/prod/sshub-atlassian-secrets-scanner.yaml).

## Smoke-test после установки

Самый безопасный ручной триггер — `upload`: он не зовёт Jira/Confluence,
только пушит в Hub то, что уже накопилось. Auth/network-проблемы видно
сразу.

```bash
kubectl -n <ns> create job --from=cronjob/<release>-sshub-atlassian-secrets-scanner-upload manual-upload-1
kubectl -n <ns> logs -f job/manual-upload-1
```

Для скана можно так же триггернуть `jira`/`confluence`. Окно скана
определяется `config.scanFromDaysAgo` / `config.scanToDaysAgo` —
по умолчанию `[3..1]` дня назад от сегодня (UTC).
