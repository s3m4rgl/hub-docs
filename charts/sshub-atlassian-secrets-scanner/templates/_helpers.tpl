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

{{- define "chart.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "chart.labels" -}}
helm.sh/chart: {{ include "chart.chart" . }}
{{ include "chart.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: sshub-atlassian-secrets-scanner
{{- end }}

{{- define "chart.selectorLabels" -}}
app.kubernetes.io/name: {{ include "chart.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Resolve ServiceAccount name. Honours operator override, otherwise derives.
*/}}
{{- define "chart.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (include "chart.fullname" .) .Values.serviceAccount.name -}}
{{- else -}}
{{- default "default" .Values.serviceAccount.name -}}
{{- end -}}
{{- end -}}

{{/*
Resolve the Secret name. Operator can pin an externally-managed Secret via
secrets.existingSecretName (umbrella / ESO / AVP). Otherwise the chart owns
<fullname>-secrets.
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
False when external Secret is supplied or secrets.create=false.
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
Three-tier resolver for external PATs (Hub/Jira/Confluence tokens):
  1. operator override (.Values.secrets.<key>) wins
  2. existing in-cluster Secret value (preserves operator's stored token across upgrades)
  3. empty string (Secret renders empty; deployments fail with a clear error)

We intentionally do NOT random-generate — these are external API tokens, a
random string would not authenticate against anything.
*/}}
{{- define "chart.resolveToken" -}}
{{- $ctx := .ctx -}}
{{- $key := .key -}}
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
{{- "" -}}
{{- end -}}
{{- end -}}

{{/*
Common envFrom for all four CronJob containers — pulls non-sensitive config
from .Values.config and looks tokens up by key in <chart-secrets>.
*/}}
{{- define "chart.commonEnv" -}}
- name: HUB_URL
  value: {{ required "config.hubUrl is required (https://hub.example.com)" .Values.config.hubUrl | quote }}
- name: HUB_JIRA_PROJECT
  value: {{ .Values.config.hubJiraProjectId | quote }}
- name: HUB_CONFLUENCE_PROJECT
  value: {{ .Values.config.hubConfluenceProjectId | quote }}
- name: KF_JIRA_URL
  value: {{ .Values.config.jiraUrl | quote }}
- name: KF_CONFLUENCE_URL
  value: {{ .Values.config.confluenceUrl | quote }}
- name: LOG_DESTINATION
  value: {{ .Values.config.logDestination | default "stdout" | quote }}
- name: SCAN_FROM_DAYS_AGO
  value: {{ .Values.config.scanFromDaysAgo | quote }}
- name: SCAN_TO_DAYS_AGO
  value: {{ .Values.config.scanToDaysAgo | quote }}
- name: CLEANUP_MAX_AGE_DAYS
  value: {{ .Values.config.cleanupMaxAgeDays | quote }}
- name: HUB_TOKEN
  valueFrom:
    secretKeyRef:
      name: {{ include "chart.secretsName" . }}
      key: hubToken
- name: KF_JIRA_TOKEN
  valueFrom:
    secretKeyRef:
      name: {{ include "chart.secretsName" . }}
      key: jiraToken
- name: KF_CONFLUENCE_TOKEN
  valueFrom:
    secretKeyRef:
      name: {{ include "chart.secretsName" . }}
      key: confluenceToken
{{- with .Values.extraEnv }}
{{- range $k, $v := . }}
- name: {{ $k }}
  value: {{ $v | quote }}
{{- end }}
{{- end }}
{{- end -}}

{{/*
Volume + mount lists. /tmp is always emptyDir (writable on read-only rootfs).
/app/results PVC is shared across cronjobs. /app/logs PVC is opt-in.
*/}}
{{- define "chart.volumes" -}}
- name: results
  persistentVolumeClaim:
    claimName: {{ include "chart.fullname" . }}-results
- name: tmp
  emptyDir:
    sizeLimit: 100Mi
{{- if .Values.pvc.logs.enabled }}
- name: logs
  persistentVolumeClaim:
    claimName: {{ include "chart.fullname" . }}-logs
{{- end }}
{{- end -}}

{{- define "chart.volumeMounts" -}}
- name: results
  mountPath: /app/results
- name: tmp
  mountPath: /tmp
{{- if .Values.pvc.logs.enabled }}
- name: logs
  mountPath: /app/logs
{{- end }}
{{- end -}}

{{/*
Render a CronJob.

Args (dict):
  ctx       — full chart context (.)
  mode      — entrypoint arg: jira | confluence | upload | cleanup
  cfg       — .Values.cronjobs.<mode> sub-tree
  jobName   — short suffix used in metadata.name
*/}}
{{- define "chart.cronjob" -}}
{{- $ctx := .ctx -}}
{{- $mode := .mode -}}
{{- $cfg := .cfg -}}
{{- $jobName := .jobName -}}
{{- if $cfg.enabled }}
apiVersion: batch/v1
kind: CronJob
metadata:
  name: {{ include "chart.fullname" $ctx }}-{{ $jobName }}
  labels:
    {{- include "chart.labels" $ctx | nindent 4 }}
    app.kubernetes.io/component: {{ $jobName }}
spec:
  schedule: {{ $cfg.schedule | quote }}
  suspend: {{ $cfg.suspend | default false }}
  concurrencyPolicy: Forbid
  successfulJobsHistoryLimit: {{ $cfg.successfulJobsHistoryLimit | default 1 }}
  failedJobsHistoryLimit: {{ $cfg.failedJobsHistoryLimit | default 3 }}
  {{- with $ctx.Values.config.timeZone }}
  timeZone: {{ . | quote }}
  {{- end }}
  jobTemplate:
    spec:
      activeDeadlineSeconds: {{ $cfg.activeDeadlineSeconds }}
      backoffLimit: {{ $cfg.backoffLimit | default 0 }}
      template:
        metadata:
          labels:
            {{- include "chart.selectorLabels" $ctx | nindent 12 }}
            app.kubernetes.io/component: {{ $jobName }}
        spec:
          restartPolicy: Never
          serviceAccountName: {{ include "chart.serviceAccountName" $ctx }}
          automountServiceAccountToken: false
          securityContext:
            {{- toYaml $ctx.Values.podSecurityContext | nindent 12 }}
          {{- with $ctx.Values.image.pullSecrets }}
          imagePullSecrets:
            {{- toYaml . | nindent 12 }}
          {{- end }}
          {{- with $ctx.Values.nodeSelector }}
          nodeSelector:
            {{- toYaml . | nindent 12 }}
          {{- end }}
          {{- with $ctx.Values.tolerations }}
          tolerations:
            {{- toYaml . | nindent 12 }}
          {{- end }}
          {{- with $ctx.Values.affinity }}
          affinity:
            {{- toYaml . | nindent 12 }}
          {{- end }}
          containers:
            - name: scanner
              image: "{{ $ctx.Values.image.repository }}:{{ $ctx.Values.image.tag }}"
              imagePullPolicy: {{ $ctx.Values.image.pullPolicy }}
              args: [{{ $mode | quote }}]
              securityContext:
                {{- toYaml $ctx.Values.containerSecurityContext | nindent 16 }}
              env:
                {{- include "chart.commonEnv" $ctx | nindent 16 }}
              volumeMounts:
                {{- include "chart.volumeMounts" $ctx | nindent 16 }}
              resources:
                {{- toYaml $cfg.resources | nindent 16 }}
          volumes:
            {{- include "chart.volumes" $ctx | nindent 12 }}
{{- end }}
{{- end -}}
