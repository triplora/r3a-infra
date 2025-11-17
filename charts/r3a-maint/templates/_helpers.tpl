{{- define "r3a-maint.name" -}}
{{- .Chart.Name -}}
{{- end -}}

{{- define "r3a-maint.fullname" -}}
{{- .Chart.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "r3a-maint.labels" -}}
app.kubernetes.io/name: {{ include "r3a-maint.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service | default "Helm" }}
app.kubernetes.io/version: {{ .Chart.AppVersion }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
{{- end -}}

{{- define "r3a-maint.selectorLabels" -}}
app.kubernetes.io/name: {{ include "r3a-maint.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "r3a-maint.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (include "r3a-maint.fullname" .) .Values.serviceAccount.name -}}
{{- else -}}
{{- default (include "r3a-maint.fullname" .) .Values.serviceAccount.name -}}
{{- end -}}
{{- end -}}
