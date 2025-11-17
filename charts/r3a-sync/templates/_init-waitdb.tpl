{{/* Renderiza o initContainer que aguarda o Postgres responder */}}
{{- define "r3a-sync.initWaitDb" -}}
- name: wait-db
  image: {{ default "postgres:16-alpine" .Values.waitDb.image | quote }}
  imagePullPolicy: IfNotPresent
  command: ["sh","-lc"]
  args:
    - >
      set -e;
      echo "[INIT] aguardando Postgres...";
      DB_URL_PG="${DB_URL/postgresql+psycopg2:/postgresql:}";
      while ! pg_isready -d "$DB_URL_PG" >/dev/null 2>&1; do
        echo "[INIT][wait] DB indisponível; retry em 3s...";
        sleep 3;
      done;
      echo "[INIT] DB respondeu ao pg_isready.";
      psql "${DB_URL_PG}?sslmode=disable" -c "select 1;" >/dev/null;
      echo "[INIT] DB OK.";
  env:
    {{- /* Para o init, reaproveitamos o mesmo bloco de vars (sincronize runner.syncIntervals antes de chamar) */}}
    {{- include "r3a-sync.envVarsOnly" . | nindent 4 }}
{{- end }}
