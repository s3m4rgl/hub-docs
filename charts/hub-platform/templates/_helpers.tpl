{{- define "hp.fullname" -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Subchart fullname helpers — derive what each subchart's chart.fullname will produce.
Critical because subcharts use chart.fullname for Service names, secrets, etc, and
the umbrella's templates need to reference those exact names.

Subchart's chart.fullname rule (from each chart's _helpers.tpl):
  if Release.Name contains chartName -> Release.Name
  else -> "<Release.Name>-<chartName>"

With aliased dependencies, the subchart's chart.Name becomes the alias name.
We hardcode aliases to: hub, domainscope, openvas, zap.
*/}}
{{- define "hp.hubFullname" -}}
{{- $name := "hub" -}}
{{- if contains $name .Release.Name -}}{{ .Release.Name | trunc 63 | trimSuffix "-" }}{{- else -}}{{ printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}{{- end -}}
{{- end -}}

{{- define "hp.domainscopeFullname" -}}
{{- $name := "domainscope" -}}
{{- if contains $name .Release.Name -}}{{ .Release.Name | trunc 63 | trimSuffix "-" }}{{- else -}}{{ printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}{{- end -}}
{{- end -}}

{{- define "hp.openvasFullname" -}}
{{- $name := "openvas" -}}
{{- if contains $name .Release.Name -}}{{ .Release.Name | trunc 63 | trimSuffix "-" }}{{- else -}}{{ printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}{{- end -}}
{{- end -}}

{{- define "hp.zapFullname" -}}
{{- $name := "zap" -}}
{{- if contains $name .Release.Name -}}{{ .Release.Name | trunc 63 | trimSuffix "-" }}{{- else -}}{{ printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}{{- end -}}
{{- end -}}

{{- define "hp.labels" -}}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/part-of: hub-platform
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
{{- end -}}

{{/*
Resolve a master-secret value: operator override > existing in-cluster > random.
Args: ctx, secretName, key, length
*/}}
{{- define "hp.resolve" -}}
{{- $ctx := .ctx -}}
{{- $name := .secretName -}}
{{- $key := .key -}}
{{- $length := default 32 .length -}}
{{- $override := default "" (index $ctx.Values.secrets $key) -}}
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
То же что hp.resolve, но генерирует UUID v4 (вместо randAlphaNum).
Преимущество: UUID для каждого install уникален, но через lookup
сохраняется между helm upgrade'ами — то есть default project/product
не меняют ID после каждого upgrade.
Args: ctx, secretName, key, override (optional)
*/}}
{{- define "hp.resolveUuid" -}}
{{- $ctx := .ctx -}}
{{- $name := .secretName -}}
{{- $key := .key -}}
{{- $override := default "" .override -}}
{{- $existing := lookup "v1" "Secret" $ctx.Release.Namespace $name -}}
{{- if $override -}}
{{- $override -}}
{{- else if and $existing $existing.data (index $existing.data $key) -}}
{{- index $existing.data $key | b64dec -}}
{{- else -}}
{{- uuidv4 -}}
{{- end -}}
{{- end -}}
