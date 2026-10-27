{{- define "eat-agent.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "eat-agent.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name (include "eat-agent.name" .) | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}

{{- define "eat-agent.labels" -}}
app.kubernetes.io/name: {{ include "eat-agent.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "eat-agent.selectorLabels" -}}
app.kubernetes.io/name: {{ include "eat-agent.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "eat-agent.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "eat-agent.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{- define "eat-agent.secretName" -}}
{{- if .Values.secrets.existingSecret }}
{{- .Values.secrets.existingSecret }}
{{- else }}
{{- include "eat-agent.fullname" . }}-secrets
{{- end }}
{{- end }}

{{- define "eat-agent.redisUrl" -}}
{{- if .Values.redis.enabled }}
redis://{{ include "eat-agent.fullname" . }}-redis:{{ .Values.redis.servicePort }}/0
{{- else }}
{{- "" }}
{{- end }}
{{- end }}
