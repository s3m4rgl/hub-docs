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

{{- define "chart.secretsName" -}}
{{- if (and .Values.secrets .Values.secrets.existingSecretName) -}}
{{- tpl .Values.secrets.existingSecretName . -}}
{{- else -}}
{{- printf "%s-secrets" (include "chart.fullname" .) -}}
{{- end -}}
{{- end -}}

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

{{- define "chart.ingressAnnotations" -}}
{{- $class := default "traefik" .Values.ingress.className -}}
{{- $tls := default (dict) .Values.tls -}}
{{- $mode := default "selfsigned" $tls.mode -}}
{{- if eq $class "nginx" }}
nginx.ingress.kubernetes.io/proxy-body-size: {{ default "25m" .Values.ingress.proxyBodySize | quote }}
{{- if .Values.ingress.rewriteTarget }}
nginx.ingress.kubernetes.io/rewrite-target: {{ .Values.ingress.rewriteTarget | quote }}
{{- end }}
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

{{- define "chart.tlsEnabled" -}}
{{- $tls := default (dict) .Values.tls -}}
{{- $mode := default "selfsigned" $tls.mode -}}
{{- if and .Values.ingress.enabled (ne $mode "disabled") -}}true{{- end -}}
{{- end -}}

{{- define "chart.tlsSecretName" -}}
{{- $tls := default (dict) .Values.tls -}}
{{- $mode := default "selfsigned" $tls.mode -}}
{{- if eq $mode "existing" -}}
{{ required "tls.existingSecretName is required when tls.mode=existing" $tls.existingSecretName }}
{{- else -}}
{{ include "chart.fullname" . }}-tls
{{- end -}}
{{- end -}}
