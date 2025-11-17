{{- define "r3a-sync.name" -}}
{{- .Chart.Name -}}
{{- end -}}

{{- define "r3a-sync.fullname" -}}
{{- .Chart.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "r3a-sync.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (include "r3a-sync.fullname" .) .Values.serviceAccount.name -}}
{{- else -}}
{{- default (include "r3a-sync.fullname" .) .Values.serviceAccount.name -}}
{{- end -}}
{{- end -}}
