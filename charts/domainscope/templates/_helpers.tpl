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

{{/*
Resolve the WireGuard egress Secret name (used by sidecar/init).
- secrets.wireguardSecretName overrides if set (umbrella mode);
- otherwise <fullname>-wireguard.
*/}}
{{- define "chart.wireguardSecretName" -}}
{{- if (and .Values.wireguard .Values.wireguard.existingSecretName) -}}
{{- tpl .Values.wireguard.existingSecretName . -}}
{{- else -}}
{{- printf "%s-wireguard" (include "chart.fullname" .) -}}
{{- end -}}
{{- end -}}
