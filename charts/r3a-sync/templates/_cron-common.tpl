{{- define "r3a-sync.podSpec" -}}
serviceAccountName: {{ include "r3a-sync.serviceAccountName" . }}
restartPolicy: Never
{{- with .Values.nodeSelector }}
nodeSelector:
{{- toYaml . | nindent 2 }}
{{- end }}
{{- with .Values.tolerations }}
tolerations:
{{- toYaml . | nindent 2 }}
{{- end }}
{{- with .Values.affinity }}
affinity:
{{- toYaml . | nindent 2 }}
{{- end }}

{{- if .Values.waitDb.enabled }}
initContainers:
  - name: wait-db
    image: {{ .Values.waitDb.image }}
    imagePullPolicy: IfNotPresent
    {{ include "r3a-sync.envFrom" . | nindent 4 }}
    command: ["sh","-lc"]
    args:
      - |
        set -e
        echo "[INIT] aguardando Postgres..."
        DB_URL_PG="${DB_URL/postgresql+psycopg2:/postgresql:}"
        until pg_isready -d "$DB_URL_PG" >/dev/null 2>&1; do
          echo "[INIT][wait] DB indisponível; retry em 3s..."
          sleep 3
        done
        echo "[INIT] DB OK."
{{- end }}

containers:
  - name: runner
    image: "{{ .Values.image.repository }}:{{ .Values.image.tag }}"
    imagePullPolicy: {{ .Values.image.pullPolicy | default "IfNotPresent" }}
    command: ["/bin/sh","-lc"]
    args:
      - >
        echo "[RUN] sync_ohlcv_job_v3.py" &&
        python infra/runner/runner_scripts/sync_ohlcv_job_v3.py &&
        echo "[RUN] health_check_pair_scanner.py" &&
        python infra/runner/runner_scripts/health_check_pair_scanner.py --quick
    {{ include "r3a-sync.envFrom" . | nindent 4 }}
{{- end -}}
