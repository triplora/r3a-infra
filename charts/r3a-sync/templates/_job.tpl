{{/* Common PodSpec for r3a-sync jobs */}}
{{- define "r3a-sync.commonPodSpec" -}}
template:
  spec:
    {{- if .Values.nodeSelector }}
    nodeSelector:
      {{- toYaml .Values.nodeSelector | nindent 6 }}
    {{- end }}
    {{- if .Values.tolerations }}
    tolerations:
      {{- toYaml .Values.tolerations | nindent 6 }}
    {{- end }}

          imagePullSecrets:
            {{- range (.Values.imagePullSecrets | default (list)) }}
            - name: {{ .name }}
            {{- end }}


    restartPolicy: Never

    # Espera o DB responder antes de iniciar o container principal
    {{- if .Values.waitDb.enabled }}
    initContainers:
      - name: wait-db
        image: {{ .Values.waitDb.image | default "postgres:16-alpine" | quote }}
        {{- if .Values.waitDb.resources }}
        resources:
          {{- toYaml .Values.waitDb.resources | nindent 10 }}
        {{- end }}
        command: ["sh","-lc"]
        args:
          - |
            echo "[INIT] aguardando Postgres..."
            # Preferência 1: usar variável DB_URL já fornecida via env
            if [ -n "$DB_URL" ]; then
              until psql "$DB_URL" -c "select 1" >/dev/null 2>&1; do
                echo "DB indisponível; tentando em 3s..."
                sleep 3
              done
              echo "DB OK via DB_URL."
            else
              # Preferência 2: checar TCP direto (fallback)
              HOST="{{ .Values.db.host | default "postgres.r3a.svc.cluster.local" }}"
              PORT="{{ .Values.db.port | default "5432" }}"
              until nc -z "$HOST" "$PORT"; do
                echo "Aguardando $HOST:$PORT..."
                sleep 3
              done
              echo "TCP $HOST:$PORT OK."
            fi
        env:
          {{- /* Reaproveita o mesmo bloco de env do container; isso injeta DB_URL etc. */}}
          {{- include "r3a-sync.envBlock" . | nindent 10 }}
    {{- end }}

    containers:
      - name: runner
        image: "{{ .Values.image.repository }}:{{ .Values.image.tag }}"
        imagePullPolicy: {{ .Values.image.pullPolicy | default "IfNotPresent" }}
        env:
          {{- include "r3a-sync.envBlock" . | nindent 10 }}
        command: ["/bin/sh","-lc"]
        args:
          - |
            echo "[RUN] sync_ohlcv_job_v3.py"
            python infra/runner/runner_scripts/sync_ohlcv_job_v3.py && \
            echo "[RUN] health_check_pair_scanner.py" && \
            python infra/runner/runner_scripts/health_check_pair_scanner.py --quick
{{- end -}}
