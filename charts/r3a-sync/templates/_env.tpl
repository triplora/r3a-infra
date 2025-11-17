{{- define "r3a-sync.envFrom" -}}
envFrom:
  - secretRef:
      name: {{ .Values.secretRefs.db }}
  - secretRef:
      name: {{ .Values.secretRefs.binance }}
  - configMapRef:
      name: {{ .Values.configMapRefs.sync }}
{{- end -}}
