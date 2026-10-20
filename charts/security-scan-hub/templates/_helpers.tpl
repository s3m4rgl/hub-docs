{{/*
Expand the name of the chart.
*/}}
{{- define "chart.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "chart.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "chart.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "chart.labels" -}}
helm.sh/chart: {{ include "chart.chart" . }}
{{ include "chart.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "chart.selectorLabels" -}}
app.kubernetes.io/name: {{ include "chart.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Create the name of the service account to use
*/}}
{{- define "chart.serviceAccountName" -}}
{{- $default := (include "chart.fullname" .) }}
{{- with .Values.serviceAccount }}
{{- if .create }}
{{- default $default .name }}
{{- else }}
{{- default "default" .name }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Resolve the name of the Secret holding sensitive env values.
- When secrets.existingSecretName is set (umbrella mode), point at it.
- Otherwise the chart owns <fullname>-secrets.
*/}}
{{- define "chart.secretsName" -}}
{{- if (and .Values.secrets .Values.secrets.existingSecretName) -}}
{{- tpl .Values.secrets.existingSecretName . -}}
{{- else -}}
{{- printf "%s-secrets" (include "chart.fullname" .) -}}
{{- end -}}
{{- end -}}

{{/*
Whether this chart should create its own Secret resource.
False when umbrella supplies an existing Secret (secrets.existingSecretName) or
when explicitly disabled via secrets.create=false.
*/}}
{{- define "chart.shouldCreateSecret" -}}
{{- $create := true -}}
{{- if .Values.secrets -}}
  {{- if hasKey .Values.secrets "create" -}}
    {{- $create = .Values.secrets.create -}}
  {{- end -}}
  {{- if .Values.secrets.existingSecretName -}}
    {{- $create = false -}}
  {{- end -}}
{{- end -}}
{{- if $create -}}true{{- end -}}
{{- end -}}

{{/*
Three-tier secret resolver: operator override > existing in-cluster value > random.
Usage: {{ include "chart.resolveSecret" (dict "ctx" . "key" "dbPassword" "length" 24) }}
*/}}
{{- define "chart.resolveSecret" -}}
{{- $ctx := .ctx -}}
{{- $key := .key -}}
{{- $length := default 24 .length -}}
{{- $override := "" -}}
{{- if and $ctx.Values.secrets (hasKey $ctx.Values.secrets $key) -}}
{{- $override = index $ctx.Values.secrets $key -}}
{{- end -}}
{{- $name := include "chart.secretsName" $ctx -}}
{{- $existing := lookup "v1" "Secret" $ctx.Release.Namespace $name -}}
{{- if $override -}}
{{- $override -}}
{{- else if and $existing $existing.data (index $existing.data $key) -}}
{{- index $existing.data $key | b64dec -}}
{{- else -}}
{{- randAlphaNum (int $length) -}}
{{- end -}}
{{- end -}}

{{/*
Ingress annotations: class-aware (traefik|nginx) + cert-manager issuer based on tls.mode.
*/}}
{{- define "chart.ingressAnnotations" -}}
{{- $class := default "traefik" .Values.ingress.className -}}
{{- $tls := default (dict) .Values.tls -}}
{{- $mode := default "selfsigned" $tls.mode -}}
{{- if eq $class "nginx" }}
nginx.ingress.kubernetes.io/proxy-body-size: {{ default "100m" .Values.ingress.proxyBodySize | quote }}
nginx.ingress.kubernetes.io/proxy-read-timeout: {{ default "300" .Values.ingress.proxyReadTimeout | quote }}
{{- end }}
{{- if eq $class "traefik" }}
traefik.ingress.kubernetes.io/router.entrypoints: {{ default "web,websecure" .Values.ingress.traefikEntrypoints | quote }}
{{- end }}
{{- if eq $mode "letsencrypt" }}
cert-manager.io/cluster-issuer: {{ default "letsencrypt-prod" $tls.issuer | quote }}
{{- end }}
{{- if eq $mode "selfsigned" }}
cert-manager.io/cluster-issuer: {{ default "selfsigned-cluster-issuer" $tls.issuer | quote }}
{{- end }}
{{- with .Values.ingress.extraAnnotations }}
{{ toYaml . }}
{{- end }}
{{- end }}

{{/*
True string when ingress should declare TLS (mode != disabled and ingress enabled).
*/}}
{{- define "chart.tlsEnabled" -}}
{{- $tls := default (dict) .Values.tls -}}
{{- $mode := default "selfsigned" $tls.mode -}}
{{- if and .Values.ingress.enabled (ne $mode "disabled") -}}true{{- end -}}
{{- end -}}

{{/*
TLS Secret name to reference from the ingress.
- mode=existing: user-provided
- otherwise: <fullname>-tls (cert-manager populates)
*/}}
{{- define "chart.tlsSecretName" -}}
{{- $tls := default (dict) .Values.tls -}}
{{- $mode := default "selfsigned" $tls.mode -}}
{{- if eq $mode "existing" -}}
{{ required "tls.existingSecretName is required when tls.mode=existing" $tls.existingSecretName }}
{{- else -}}
{{ include "chart.fullname" . }}-tls
{{- end -}}
{{- end -}}

{{/*
Подключение к PostgreSQL Hub — единый источник для backend, worker, Secret
(databaseUrl/iacScannerDsn) и seed-admin Job.

Адрес — backend.backend.env.dbHost; пусто → встроенная база <fullname>-postgres.
С внешним адресом порт, имя базы и пользователь берутся у backend; со встроенной
— из postgres.env и 5432, как и раньше.

postgres.enabled=false без dbHost — ошибка рендера: иначе backend и worker
молча смотрели бы на несуществующий сервис <fullname>-postgres.
*/}}
{{- define "chart.dbHost" -}}
{{- $h := .Values.backend.backend.env.dbHost -}}
{{- if $h -}}
{{- $h -}}
{{- else if .Values.postgres.enabled -}}
{{- printf "%s-postgres" (include "chart.fullname" .) -}}
{{- else -}}
{{- fail "postgres.enabled=false: задайте backend.backend.env.dbHost (в hub-platform — hub.backend.backend.env.dbHost) — адрес внешнего PostgreSQL" -}}
{{- end -}}
{{- end -}}

{{- define "chart.dbPort" -}}
{{- if .Values.backend.backend.env.dbHost -}}{{- default "5432" .Values.backend.backend.env.dbPort -}}{{- else -}}5432{{- end -}}
{{- end -}}

{{- define "chart.dbName" -}}
{{- if .Values.backend.backend.env.dbHost -}}{{- .Values.backend.backend.env.dbName -}}{{- else -}}{{- .Values.postgres.env.postgresDb -}}{{- end -}}
{{- end -}}

{{- define "chart.dbUser" -}}
{{- if .Values.backend.backend.env.dbHost -}}{{- .Values.backend.backend.env.dbUser -}}{{- else -}}{{- .Values.postgres.env.postgresUser -}}{{- end -}}
{{- end -}}

{{/*
=== AI-триаж (LLM) ===

Единый источник настроек LLM для backend, worker, Secret, checksum-аннотаций и
NOTES. Раньше LLM задавался дважды (backend.backend.env.llm* и
worker.worker.env.llm*), и заполненный только у backend блок давал задачи
llm_analysis, которые никто не забирает.

Порядок разрешения каждого параметра:
  1. llm.<ключ>, если он отличается от значения по умолчанию чарта;
  2. устаревший worker.worker.env.llm<Ключ>, затем backend.backend.env.llm<Ключ>,
     если пользователь задал их явно (в values.yaml по умолчанию их больше нет);
  3. значение по умолчанию.
AI-триаж включён, если llm.enabled=true или явно задан устаревший llmBaseUrl.

Результат — JSON, использовать так:
  {{- $llm := include "chart.llm" . | fromJson -}}
Ошибки конфигурации при включённом AI-триаже прерывают рендер (fail).
*/}}
{{- define "chart.llm.defaults" -}}
{{- dict "baseUrl" "" "model" "glm-4-plus" "dryRun" "false" "falsePositiveThreshold" "0.9" "requestTimeoutSeconds" "180" "workers" "3" "promptsDir" "" | toJson -}}
{{- end -}}

{{/*
Значение ключа llmApiKey для Secret чарта: llm.apiKey, затем совместимый алиас
secrets.llmApiKey, затем значение, уже лежащее в Secret в кластере (иначе ключ,
положенный в Secret вручную, затирался бы при каждом helm upgrade). Случайное
значение НЕ генерируется: пустой ключ означает «не задан».
*/}}
{{- define "chart.llmApiKeyValue" -}}
{{- $v := toString (default "" (.Values.llm | default dict).apiKey) -}}
{{- if not $v -}}
{{- $v = toString (default "" (.Values.secrets | default dict).llmApiKey) -}}
{{- end -}}
{{- if $v -}}
{{- $v -}}
{{- else -}}
{{- $existing := lookup "v1" "Secret" .Release.Namespace (include "chart.secretsName" .) -}}
{{- if and $existing $existing.data (index $existing.data "llmApiKey") -}}
{{- index $existing.data "llmApiKey" | b64dec -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{- define "chart.llm" -}}
{{- $ctx := . -}}
{{- $new := default (dict) .Values.llm -}}
{{- $be := default (dict) .Values.backend.backend.env -}}
{{- $we := default (dict) .Values.worker.worker.env -}}
{{- $defaults := include "chart.llm.defaults" . | fromJson -}}
{{- $legacyNames := dict "baseUrl" "llmBaseUrl" "model" "llmModel" "dryRun" "llmDryRun" "falsePositiveThreshold" "llmFalsePositiveThreshold" "requestTimeoutSeconds" "llmRequestTimeoutSeconds" "workers" "llmWorkers" -}}
{{- $out := dict -}}
{{- $legacyUsed := list -}}
{{- $warnings := list -}}
{{- range $key := list "baseUrl" "model" "dryRun" "falsePositiveThreshold" "requestTimeoutSeconds" "workers" "promptsDir" -}}
  {{- $def := index $defaults $key -}}
  {{- $val := $def -}}
  {{- $newSet := false -}}
  {{- if and (hasKey $new $key) (not (kindIs "invalid" (index $new $key))) -}}
    {{- $val = toString (index $new $key) -}}
    {{- $newSet = ne $val $def -}}
  {{- end -}}
  {{- $old := "" -}}
  {{- $oldFrom := "" -}}
  {{- $oldName := index $legacyNames $key | default "" -}}
  {{- if $oldName -}}
    {{- $sources := list (list "worker.worker.env" $we) -}}
    {{- if ne $key "workers" -}}
      {{- $sources = append $sources (list "backend.backend.env" $be) -}}
    {{- end -}}
    {{- range $src := $sources -}}
      {{- $env := index $src 1 -}}
      {{- if and (hasKey $env $oldName) (not (kindIs "invalid" (index $env $oldName))) (ne (toString (index $env $oldName)) "") -}}
        {{- $path := printf "%s.%s" (index $src 0) $oldName -}}
        {{- $legacyUsed = append $legacyUsed $path -}}
        {{- if not $oldFrom -}}
          {{- $old = toString (index $env $oldName) -}}
          {{- $oldFrom = $path -}}
        {{- else if ne $old (toString (index $env $oldName)) -}}
          {{- $warnings = append $warnings (printf "%s и %s различаются, взято значение %s" $oldFrom $path $oldFrom) -}}
        {{- end -}}
      {{- end -}}
    {{- end -}}
  {{- end -}}
  {{- if and $oldFrom $newSet (ne $old $val) -}}
    {{- $warnings = append $warnings (printf "llm.%s=%q и устаревший %s=%q различаются, действует llm.%s" $key $val $oldFrom $old $key) -}}
  {{- else if and $oldFrom (not $newSet) -}}
    {{- $val = $old -}}
  {{- end -}}
  {{- $_ := set $out $key $val -}}
{{- end -}}
{{- if and (hasKey $be "llmWorkers") (ne (toString (index $be "llmWorkers")) "") (ne (toString (index $be "llmWorkers")) "0") -}}
  {{- $warnings = append $warnings (printf "backend.backend.env.llmWorkers=%v игнорируется: backend всегда получает LLM_WORKERS=0, задачи выполняет worker (llm.workers)" (index $be "llmWorkers")) -}}
{{- end -}}
{{- if and (hasKey $be "llmWorkers") (not (has "backend.backend.env.llmWorkers" $legacyUsed)) -}}
  {{- $legacyUsed = append $legacyUsed "backend.backend.env.llmWorkers" -}}
{{- end -}}
{{- $enabled := or (eq (toString (default false $new.enabled)) "true") (ne (index $out "baseUrl") "") -}}
{{- $_ := set $out "enabled" $enabled -}}
{{/*
Включён только старыми ключами, а dryRun нигде не задан: сохраняем прежнее
значение по умолчанию чарта (llmDryRun: "true"), чтобы upgrade без правки
values не начал менять находки.
*/}}
{{- $newEnabled := eq (toString (default false $new.enabled)) "true" -}}
{{- $dryRunLegacySet := or (and (hasKey $we "llmDryRun") (ne (toString (index $we "llmDryRun")) "")) (and (hasKey $be "llmDryRun") (ne (toString (index $be "llmDryRun")) "")) -}}
{{- $dryRunNewSet := and (hasKey $new "dryRun") (ne (toString (index $new "dryRun")) "false") -}}
{{- if and $enabled (not $newEnabled) (not $dryRunLegacySet) (not $dryRunNewSet) -}}
  {{- $_ := set $out "dryRun" "true" -}}
  {{- $warnings = append $warnings "AI-триаж включён устаревшим llmBaseUrl, llmDryRun не задан: оставлен прежний dryRun=true (вердикты только в журнал). Перейдите на блок llm: и задайте llm.dryRun явно" -}}
{{- end -}}
{{- $_ := set $out "dryRun" (eq (index $out "dryRun") "true") -}}
{{- $_ := set $out "workers" (int (index $out "workers")) -}}
{{- $_ := set $out "legacyKeys" (uniq $legacyUsed) -}}

{{/* Источник ключа API */}}
{{- $inlineKey := toString (default "" $new.apiKey) -}}
{{- $inlineFrom := "llm.apiKey" -}}
{{- if not $inlineKey -}}
  {{- $inlineKey = toString (default "" (.Values.secrets | default dict).llmApiKey) -}}
  {{- $inlineFrom = "secrets.llmApiKey" -}}
{{- end -}}
{{- $existingSecret := tpl (toString (default "" $new.existingSecret)) . -}}
{{- $hasKey := true -}}
{{- if $existingSecret -}}
  {{- $_ := set $out "apiKeySecretName" $existingSecret -}}
  {{- $_ := set $out "apiKeySecretKey" (toString (default "llm-api-key" $new.existingSecretKey)) -}}
  {{- $_ := set $out "apiKeySource" (printf "Secret %s, ключ %s (llm.existingSecret)" $existingSecret (index $out "apiKeySecretKey")) -}}
  {{- if $inlineKey -}}
    {{- $warnings = append $warnings (printf "%s игнорируется: задан llm.existingSecret" $inlineFrom) -}}
  {{- end -}}
{{- else if include "chart.shouldCreateSecret" . -}}
  {{- $_ := set $out "apiKeySecretName" (include "chart.secretsName" .) -}}
  {{- $_ := set $out "apiKeySecretKey" "llmApiKey" -}}
  {{- $value := include "chart.llmApiKeyValue" . -}}
  {{- $hasKey = ne $value "" -}}
  {{- $_ := set $out "apiKeySha" ($value | sha256sum) -}}
  {{- if $inlineKey -}}
    {{- $_ := set $out "apiKeySource" (printf "Secret чарта %s, ключ llmApiKey (из %s)" (index $out "apiKeySecretName") $inlineFrom) -}}
  {{- else -}}
    {{- $_ := set $out "apiKeySource" (printf "Secret чарта %s, ключ llmApiKey (значение, уже сохранённое в кластере)" (index $out "apiKeySecretName")) -}}
  {{- end -}}
{{- else -}}
  {{- $_ := set $out "apiKeySecretName" (include "chart.secretsName" .) -}}
  {{- $_ := set $out "apiKeySecretKey" "llmApiKey" -}}
  {{- $_ := set $out "apiKeySource" (printf "внешний Secret %s, ключ llmApiKey (secrets.existingSecretName)" (index $out "apiKeySecretName")) -}}
  {{- if and $enabled $inlineKey -}}
    {{- fail (printf "llm: %s задан, но чарт не создаёт Secret (secrets.existingSecretName или secrets.create=false). Положите ключ в Secret %s под ключом llmApiKey (в hub-platform — secrets.hubLlmApiKey) либо укажите llm.existingSecret" $inlineFrom (index $out "apiKeySecretName")) -}}
  {{- end -}}
{{- end -}}
{{- $_ := set $out "warnings" $warnings -}}

{{/* Валидация */}}
{{- if $enabled -}}
  {{- $url := index $out "baseUrl" -}}
  {{- if not $url -}}
    {{- fail "llm.enabled=true, но llm.baseUrl пуст: укажите адрес OpenAI-совместимого API (https://...)" -}}
  {{- end -}}
  {{- if not (or (hasPrefix "https://" $url) (hasPrefix "http://" $url)) -}}
    {{- fail (printf "llm.baseUrl=%q: нужен полный адрес со схемой https://" $url) -}}
  {{- end -}}
  {{- if not $hasKey -}}
    {{- fail (printf "llm.enabled=true, но ключ API не задан: укажите llm.apiKey (попадёт в Secret %s) или llm.existingSecret с именем готового Secret" (index $out "apiKeySecretName")) -}}
  {{- end -}}
  {{- if lt (int (index $out "workers")) 1 -}}
    {{- fail (printf "llm.workers=%v: нужно не меньше 1, иначе задачи AI-триажа ставятся в очередь, но их никто не выполняет" (index $out "workers")) -}}
  {{- end -}}
  {{- if hasPrefix "http://" $url -}}
    {{- range $comp := list (list "backend" $be) (list "worker" $we) -}}
      {{- $appEnv := toString (default "production" (index (index $comp 1) "appEnv")) -}}
      {{- if not (has $appEnv (list "development" "test")) -}}
        {{- fail (printf "llm.baseUrl=%q использует http://, а у %s appEnv=%s: в этом окружении Hub требует https:// (ключ API передаётся в каждом запросе) и не запустится" $url (index $comp 0) $appEnv) -}}
      {{- end -}}
    {{- end -}}
  {{- end -}}
{{- end -}}
{{- $out | toJson -}}
{{- end -}}

{{/*
Переменные LLM_* для контейнера. Usage:
  {{- include "chart.llmEnv" (dict "ctx" . "role" "backend") | nindent 8 }}
Backend всегда получает LLM_WORKERS=0: он только ставит задачи, выполняет их
worker. При выключенном AI-триаже остальные LLM_* не рендерятся совсем.
*/}}
{{- define "chart.llmEnv" -}}
{{- $llm := include "chart.llm" .ctx | fromJson -}}
{{- if eq .role "backend" }}
- name: LLM_WORKERS
  value: "0"
{{- end }}
{{- if $llm.enabled }}
- name: LLM_BASE_URL
  value: {{ $llm.baseUrl | quote }}
- name: LLM_API_KEY
  valueFrom:
    secretKeyRef:
      name: {{ $llm.apiKeySecretName | quote }}
      key: {{ $llm.apiKeySecretKey | quote }}
{{- with $llm.model }}
- name: LLM_MODEL
  value: {{ . | quote }}
{{- end }}
- name: LLM_DRY_RUN
  value: {{ $llm.dryRun | toString | quote }}
{{- with $llm.falsePositiveThreshold }}
- name: LLM_FALSE_POSITIVE_THRESHOLD
  value: {{ . | quote }}
{{- end }}
{{- with $llm.requestTimeoutSeconds }}
- name: LLM_REQUEST_TIMEOUT_SECONDS
  value: {{ . | quote }}
{{- end }}
{{- with $llm.promptsDir }}
- name: LLM_PROMPTS_DIR
  value: {{ . | quote }}
{{- end }}
{{- if eq .role "worker" }}
- name: LLM_WORKERS
  value: {{ $llm.workers | int | toString | quote }}
{{- end }}
{{- end }}
{{- end -}}

{{/*
checksum/llm: меняется при смене итоговых настроек LLM, имени Secret с ключом
или значения ключа в Secret чарта — поды backend и worker перезапускаются сами.
*/}}
{{- define "chart.llmChecksum" -}}
{{- $llm := include "chart.llm" . | fromJson -}}
{{- omit $llm "warnings" "legacyKeys" "apiKeySource" | toJson | sha256sum -}}
{{- end -}}
