# R3A – Sync & Maintenance (K8s/Helm)

Guia consolidado (deploy, operação e troubleshooting) do **pipeline de sincronização de OHLCV** e das **rotinas de manutenção** no cluster Kubernetes. Inclui os ajustes aplicados, comandos prontos, explicações de parâmetros e boas práticas de concorrência/locks.

> Ambiente-alvo: namespace `r3a`, imagens publicadas no **GitHub Container Registry (GHCR)**, contas de serviço e RBAC já existentes para o Runner (`r3a-sync-sa`).

---

## 1) Componentes

### 1.1 Charts Helm
- **`infra/runner/charts/r3a-sync`**
  - CronJobs: `r3a-sync-1m-top`, `r3a-sync-1m`, `r3a-sync-15m`, `r3a-sync-1h`, `r3a-sync-1d`.
  - Helper `_cron-common.tpl` com `podSpec` padronizado (init `wait-db`, container runner) e `envFrom` para Secrets/ConfigMaps.
  - Concurrency e TTL configuráveis via `values`.
- **`infra/runner/charts/r3a-maint`**
  - CronJobs: `r3a-maint` (manutenção/índices), `r3a-maint-janitor` (limpeza pods/jobs zumbis) e `r3a-maint-refresh-lastts` (materializa/atualiza última ts por par/intervalo). Opcional: `r3a-maint-vacuum-hot`.
  - `configmap-maint.yaml`: script Python `maint.py` (DDL concorrente e limitado) com lock no banco.
  - `cronjob-janitor.yaml`: limpeza **via kubectl** (sem dependência de SDK python), respeitando seletores protegidos e janelas mínimas.
  - `rbac-janitor.yaml`: permissões mínimas para listar/deletar pods/jobs no namespace.

### 1.2 Imagem do Runner
- **Imagem base:** `python:3.8-slim` (Debian/apt).
- **Ferramentas instaladas:** `curl`, `ca-certificates`, `bash`, `coreutils`, `grep`, `sed`, `netcat-traditional`, `jq` (opcional), **`kubectl`** (baixado de `dl.k8s.io`).
- **Python deps:** `requirements.runner.txt`.
- Usada por **sync** e **janitor** (garante `kubectl` disponível dentro do Pod).

---

## 2) Variáveis e Secrets necessários

### 2.1 Banco e Binance
- **Secret `r3a-db`**: deve expor `DB_URL` (ex.: `postgresql+psycopg2://user:pass@host:5432/trade`).
- **Secret `r3a-binance`**: `BINANCE_API_KEY`, `BINANCE_API_SECRET` (quando utilizado pelo sync).
- **ConfigMap `r3a-sync-config`** (exemplos):
  - `AUTO_PERIOD=true|false`
  - `SYNC_INTERVALS="1m,15m,1h,4h,1d"`
  - `FALLBACK_START=2020-01-01`

### 2.2 Pull de Imagem (GHCR)
> **Use um PAT (Personal Access Token)**, não a senha da conta.

```bash
docker login ghcr.io -u triplora  # (interativo ou via --password-stdin com PAT)

# Push local -> GHCR
docker build -f infra/runner/Dockerfile.r3a-runner -t ghcr.io/triplora/r3a-runner:2025-11-15a .
docker push ghcr.io/triplora/r3a-runner:2025-11-15a

# Secret no cluster (formato dockerconfigjson)
kubectl -n r3a create secret docker-registry r3a-regcred \
  --docker-server=ghcr.io \
  --docker-username=triplora \
  --docker-password="$GITHUB_PAT" \
  --docker-email="SEU_EMAIL"
```

> Verificação:
>
> ```bash
> kubectl -n r3a get secret r3a-regcred -o jsonpath='{.data.\.dockerconfigjson}' | base64 -d | jq .
> ```

---

## 3) Deploy/Upgrade dos charts

### 3.1 `r3a-sync`

`values.prod.yaml` (trechos relevantes)
```yaml
image:
  repository: r3a-runner
  tag: latest
  pullPolicy: IfNotPresent

serviceAccount:
  create: false
  name: r3a-sync-sa

secretRefs:
  db: r3a-db
  binance: r3a-binance

configMapRefs:
  sync: r3a-sync-config

waitDb:
  enabled: true
  image: postgres:16-alpine

job:
  concurrencyPolicy: Forbid
  successfulJobsHistoryLimit: 1
  failedJobsHistoryLimit: 2
  startingDeadlineSeconds: 300
  backoffLimit: 2
  activeDeadlineSeconds: 900
  ttlSecondsAfterFinished: 1800
  suspend: false

schedules:
  m1Top: "* * * * *"
  m1:   "* * * * *"
  m15:  "*/15 * * * *"
  h1:   "0 * * * *"
  d1:   "0 2 * * *"
```

**Instalação/upgrade:**
```bash
helm upgrade --install r3a-sync infra/runner/charts/r3a-sync -n r3a \
  --set image.repository=r3a-runner \
  --set image.tag=latest \
  --set serviceAccount.create=false \
  --set serviceAccount.name=r3a-sync-sa
```

> **ServiceAccount**: precisa existir previamente (ou ser criado por outro chart). Caso tente criar aqui e em outro release, ocorrerá erro de “invalid ownership metadata… release-name…”.

### 3.2 `r3a-maint`

`values.prod.yaml` (consolidado)
```yaml
image:
  repository: ghcr.io/triplora/r3a-runner
  tag: "2025-11-15a"
  pullPolicy: IfNotPresent

imagePullSecrets:
  - name: r3a-regcred

serviceAccount:
  create: false
  name: r3a-sync-sa

secretRefs:
  db: r3a-db

waitDb:
  enabled: true
  image: postgres:16-alpine

schedule: "15 * * * *"
concurrencyPolicy: Forbid
successfulJobsHistoryLimit: 1
failedJobsHistoryLimit: 2
startingDeadlineSeconds: 300
backoffLimit: 1
activeDeadlineSeconds: 1200
ttlSecondsAfterFinished: 1800
suspend: false

janitor:
  enabled: true
  schedule: "*/5 * * * *"
  concurrencyPolicy: Forbid
  successfulJobsHistoryLimit: 1
  failedJobsHistoryLimit: 2
  startingDeadlineSeconds: 120
  backoffLimit: 0
  activeDeadlineSeconds: 240
  ttlSecondsAfterFinished: 900
  suspend: false
  image: ""              # herda image.repository:tag
  imagePullPolicy: ""
  targetNamespace: r3a
  deleteAfterSeconds: 900
  protectedSelectors:
    - "app.kubernetes.io/name=postgres"
    - "app.kubernetes.io/instance=ingress-nginx"

refreshLastTs:
  enabled: true
  schedule: "1-59/2 * * * *"   # minuto 1,3,5…
  concurrencyPolicy: Forbid
  successfulJobsHistoryLimit: 1
  failedJobsHistoryLimit: 2
  startingDeadlineSeconds: 120
  backoffLimit: 0
  activeDeadlineSeconds: 180
  ttlSecondsAfterFinished: 600
  suspend: false
  lookback: "3 days"

vacuumHot:
  enabled: true
  schedule: "10 * * * *"
  concurrencyPolicy: Forbid
  successfulJobsHistoryLimit: 1
  failedJobsHistoryLimit: 2
  startingDeadlineSeconds: 300
  backoffLimit: 0
  activeDeadlineSeconds: 1200
  ttlSecondsAfterFinished: 1800
  suspend: false
  analyzeOnly: true

env:
  MAINT_MAX_OPS: "300"
```

**Instalação/upgrade:**
```bash
helm upgrade --install r3a-maint infra/runner/charts/r3a-maint -n r3a \
  -f infra/runner/charts/r3a-maint/values.prod.yaml
```

> Se aparecer erro de “invalid ownership metadata” em SA, garanta `serviceAccount.create=false` e que o SA referenciado realmente existe.

---

## 4) Arquivos e trechos-chave (aplicados)

### 4.1 `r3a-sync`: `_cron-common.tpl` (podSpec + init wait-db)
- `serviceAccountName` = `r3a-sync-sa`.
- `initContainers.wait-db`: usa `postgres:16-alpine` e `pg_isready` contra `DB_URL` normalizado para libpq.
- Container `runner`: executa na sequência `sync_ohlcv_job_v3.py` e `health_check_pair_scanner.py --quick`.

### 4.2 `r3a-maint`: `cronjob.yaml` (manutenção principal)
- Usa **imagem do Runner** (garante dependências, caso `maint.py` mude no futuro).
- `initContainers.wait-db` opcional para aguardar Postgres.
- `maint.py` roda com **lock no banco** e **limite de operações**.

**`configmap-maint.yaml` – hotfix aplicado**
- A função SQL tem **2 parâmetros**. Ajustamos o Python para chamar `generate_index_sql(128, 90)` e **limitar no Python** pelo `MAX_OPS`.

```python
cur.execute("SELECT leaf, kind, sql FROM r3a_util.generate_index_sql(%s,%s);", (128, 90))
ops = cur.fetchall()
if MAX_OPS and MAX_OPS > 0:
    ops = ops[:MAX_OPS]
```

> Alternativa (opcional): criar `r3a_util.generate_index_sql_limited(pages,fill,limit)` e manter 3º parâmetro no SQL.

### 4.3 `r3a-maint`: `cronjob-janitor.yaml`
- **Shell puro com kubectl** (sem SDk `kubernetes`).
- Coleta pods **não Running/Succeeded**, calcula idade via `startTime`, aplica heurísticas de erro (`Failed`, `Init:Error`, `CrashLoopBackOff`, `ImagePullBackOff`, `ErrImagePull`, `CreateContainerConfigError`).
- Só deleta se **idade >= deleteAfterSeconds** e **não** casar com `protectedSelectors`.
- Usa `imagePullSecrets` e `serviceAccountName` existentes.

### 4.4 `r3a-maint`: `cronjob-refresh-lastts.yaml`
- Atualiza `r3a_util.last_ts_by_coin_interval` com o último `timestamp` por `coin_id, interval` olhando **lookback**.
- **Evitar concorrência**: além de `concurrencyPolicy: Forbid`, recomenda-se **lock no banco** no começo e no fim (se ainda não estiver no teu arquivo):

```bash
# dentro do args: |
set -e
DB_URL_PG="${DB_URL/postgresql+psycopg2:/postgresql:}"
# 1) tenta lock
psql "$DB_URL_PG" -v ON_ERROR_STOP=1 -c "SELECT r3a_util.acquire_lock('refresh-lastts','global');" | cat
# 2) timeouts defensivos (evita travas longas)
psql "$DB_URL_PG" -v ON_ERROR_STOP=1 -c "SET lock_timeout='3s'; SET statement_timeout='60s';" >/dev/null 2>&1 || true
# 3) SQL principal
cat > /tmp/refresh.sql <<'SQL'
WITH latest AS (
  SELECT coin_id,"interval", max("timestamp") AS mx
  FROM r3a.ohlcv_partitioned
  WHERE "timestamp" >= NOW() - INTERVAL '{{ .Values.refreshLastTs.lookback | default "3 days" }}'
  GROUP BY coin_id, "interval"
)
INSERT INTO r3a_util.last_ts_by_coin_interval (coin_id,"interval",last_ts)
SELECT coin_id,"interval",mx FROM latest
ON CONFLICT (coin_id,"interval")
DO UPDATE SET last_ts = GREATEST(r3a_util.last_ts_by_coin_interval.last_ts, EXCLUDED.last_ts);
SQL
psql "$DB_URL_PG" -v ON_ERROR_STOP=1 -f /tmp/refresh.sql
# 4) libera lock
psql "$DB_URL_PG" -v ON_ERROR_STOP=1 -c "SELECT r3a_util.release_lock('refresh-lastts','global');" | cat
```

> **Sintomas de concorrência** (vários Jobs em paralelo) surgem se o Job anterior ainda estiver rodando quando o próximo agenda. `Forbid` evita início simultâneo, mas se o Job ficar preso, Jobs subsequentes podem acumular (ver TTL, backoff e deadlines).

### 4.5 `r3a-maint`: `cronjob-vacuum-hot.yaml`
- Condicional por `vacuumHot.enabled`.
- `analyzeOnly: true` por padrão (executa `ANALYZE` na partição principal). Pode alternar para `VACUUM (ANALYZE)` se apropriado.

### 4.6 RBAC do Janitor
`rbac-janitor.yaml` concede somente o necessário (`get/list/watch/delete` para `pods` e `get/list/watch/create/delete` para `jobs`) no **namespace do release** e **amarrado** ao SA configurado.

---

## 5) Código Python relevante (runner)

### 5.1 `core/data/binance_downloader.py` (destaques)
- Engine SQLAlchemy com `pool_size=3`, `max_overflow=0`, `pool_pre_ping=True`, `pool_recycle=1800`, `isolation_level="READ COMMITTED"`.
- `standardize_symbol` normaliza símbolos.
- `get_last_timestamp_from_db` e `load_ohlcv_from_db` usam `pandas.read_sql` parametrizado.
- `fetch_ohlcv_binance` usa `get_historical_klines` com `start_str`/`end_str` e normaliza para `Decimal` (strings antes do insert).
- `insert_ohlcv_to_db` faz **UPSERT** por lote e cria **partições coin/mês/interval** sob demanda (`_ensure_partitions_exist`).
- `warn_on_db_gaps` registra `gaps` em `r3a.ohlcv_gap_log` e tenta auto-resync para pequenos buracos.

### 5.2 `infra/runner/runner_scripts/sync_ohlcv_job_v3.py` (concorrência)
- **Lock de processo**: usar **context manager** `advisory_lock` (arquivo `runner_scripts/util_db_lock.py`) para escopo do Job/intervalo.
- **Ajuste necessário (bug fix)**: Se usar `pg_try_advisory_lock` manual, utilize `syncer.engine`, não uma variável inexistente:

```python
# errado: with engine.begin() as conn:  # 'engine' não definido
# certo:
from sqlalchemy import text
with syncer.engine.begin() as conn:
    got = conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": lock_key}).scalar()
    if not got:
        logger.info(f"[LOCK] ocupado {symbol}-{interval}; outro job em andamento.")
        return 0
```

> Dica: mantenha **um lock por (symbol, interval)** e, se rodar vários CronJobs, também um lock global por **intervalo** para evitar colisões entre `1m` e `1m-top`.

---

## 6) Operação (comandos úteis)

### 6.1 Forçar execução de um CronJob agora
```bash
SUF=$(date +%s)
kubectl -n r3a create job --from=cronjob/r3a-sync-1m-top r3a-sync-1m-top-now-$SUF
kubectl -n r3a logs -f job/r3a-sync-1m-top-now-$SUF
```

### 6.2 Conferir SA nos CronJobs
```bash
for cj in r3a-sync-1m-top r3a-sync-1m r3a-sync-15m r3a-sync-1h r3a-sync-1d; do
  echo "== $cj =="
  kubectl -n r3a get cronjob "$cj" -o jsonpath='{.spec.jobTemplate.spec.template.spec.serviceAccountName}'; echo
done
```

### 6.3 Logs e eventos
```bash
kubectl -n r3a get jobs
kubectl -n r3a get pods
kubectl -n r3a logs -f <pod>
kubectl -n r3a describe pod <pod> | sed -n '/Events/,$p'
```

### 6.4 Verificar imagePullSecret no template
```bash
kubectl -n r3a get cj r3a-maint-janitor -o yaml | yq '.spec.jobTemplate.spec.template.spec.imagePullSecrets'
```

---

## 7) Troubleshooting (erros vistos e correções)

### 7.1 `ServiceAccount ... not found`
- Ajuste o chart para **não criar** SA duplicada: `serviceAccount.create=false` e `serviceAccount.name=r3a-sync-sa`.
- Garanta que o SA exista e que RBAC/RoleBinding aponte para ele.

### 7.2 `ImagePullBackOff` / `403 Forbidden` no GHCR
- Use **PAT** no Secret (`r3a-regcred`).
- `values.imagePullSecrets` referenciando o Secret.
- Confirme tag pushada e nome totalmente qualificado: `ghcr.io/triplora/r3a-runner:<tag>`.

### 7.3 `kubectl: not found` dentro do Pod
- Garanta que o **container do janitor** use a imagem do Runner (que instala `kubectl`).
- Se usar outra imagem, instale `kubectl` nela.

### 7.4 `ModuleNotFoundError: kubernetes` (janitor Python)
- Corrigido migrando o janitor para **shell + kubectl**. Se voltar ao Python, adicione `kubernetes` em `requirements.runner.txt`.

### 7.5 Concurrency (Jobs simultâneos)
- `concurrencyPolicy: Forbid` nos CronJobs.
- **Locks no banco** (funções `r3a_util.acquire_lock/release_lock`) nos scripts `maint.py` e `refresh-lastts`.
- Deadlines e TTL:
  - `activeDeadlineSeconds`, `backoffLimit: 0` quando o job é curto.
  - `ttlSecondsAfterFinished` para limpar Jobs finalizados.

### 7.6 `out of shared memory` / `max_locks_per_transaction`
- Acontece em picos (DDL, muitos índices/partições, várias sessões) ou em consultas que tocam **muitas partições**.
- Mitigações:
  - Reduzir operações simultâneas: **locks**, `MAX_OPS` no `maint.py`, espaçar janelas (`schedule`).
  - Aplicar **timeouts** (`statement_timeout`, `lock_timeout`) em jobs psql.
  - **Tuning** do Postgres (se necessário):
    ```sql
    ALTER SYSTEM SET max_locks_per_transaction = 256;  -- ou maior conforme o caso
    SELECT pg_reload_conf();
    -- reinício do serviço pode ser necessário dependendo do parâmetro
    ```

### 7.7 Função `r3a_util.generate_index_sql` (assinatura)
- A função no banco tem **2 parâmetros**. O `maint.py` agora chama com dois e aplica o limite no Python.
- Alternativa: criar `generate_index_sql_limited(pages, fill, limit)` e chamar com 3 parâmetros no SQL.

---

## 8) Boas práticas adicionais
- **Proteção de pods críticos**: mantenha `protectedSelectors` no Janitor para não tocar em Postgres/Ingress.
- **TTL+Janitor**: TTL limpa Jobs, Janitor é fallback para pods travados (CrashLoopBackOff, ImagePullBackOff etc.) após `deleteAfterSeconds`.
- **Pooling SQLAlchemy**: `pool_size` pequeno e `max_overflow=0` para não pressionar o Postgres.
- **`SYNC_INTERVALS`**: escolha consciente por CronJob (ex.: `1m-top` correr só com top pairs; `1m` com geral; janelas diferentes evitam colisões).
- **Observabilidade**: redirecione logs para arquivo + console; padronize prefixos `[RUN]`, `[INIT]`, `[JANITOR]`, `[MAINT]`.

---

## 9) Checagens rápidas (sanity checks)
1) **SA e RBAC**:
```bash
kubectl -n r3a get sa r3a-sync-sa
kubectl -n r3a get role,rolebinding | grep r3a-maint-janitor
```
2) **Secrets**:
```bash
kubectl -n r3a get secret r3a-db r3a-binance r3a-regcred
```
3) **CronJobs apontando para SA + imagePullSecrets**:
```bash
kubectl -n r3a get cj r3a-maint-janitor -o jsonpath='{.spec.jobTemplate.spec.template.spec.serviceAccountName}'
kubectl -n r3a get cj r3a-maint-janitor -o jsonpath='{.spec.jobTemplate.spec.template.spec.imagePullSecrets[*].name}'
```
4) **Pull da imagem**:
```bash
kubectl -n r3a describe pod <pod> | sed -n '/Events/,$p'
```
5) **Locks** (no Postgres):
```sql
SELECT r3a_util.acquire_lock('probe','demo');
SELECT r3a_util.release_lock('probe','demo');
```

---

## 10) Próximos passos sugeridos
- Implementar **lock explícito** no `cronjob-refresh-lastts.yaml` (se ainda não inserido no teu arquivo) – ver §4.4.
- Ajustar `sync_ohlcv_job_v3.py` para usar `syncer.engine` no `pg_try_advisory_lock` e/ou reforçar o uso do `advisory_lock` (context manager) por `interval` e por `(symbol, interval)`.
- Se `out of shared memory` persistir, considerar **reduzir lookback** do refresh (ex.: `1 day`) e **deslocar horário** do `maint` para fora de janelas quentes.

---

### Apêndice A – Funções SQL (locks)
```sql
CREATE OR REPLACE FUNCTION r3a_util.acquire_lock(_scope text, _key text)
RETURNS boolean LANGUAGE sql AS $$
  SELECT pg_try_advisory_lock(
    ('x'||substr(md5(_scope),1,16))::bit(64)::bigint # 0,
    ('x'||substr(md5(_key),  1,16))::bit(64)::bigint # 0
  );
$$;

CREATE OR REPLACE FUNCTION r3a_util.release_lock(_scope text, _key text)
RETURNS void LANGUAGE sql AS $$
  SELECT pg_advisory_unlock(
    ('x'||substr(md5(_scope),1,16))::bit(64)::bigint # 0,
    ('x'||substr(md5(_key),  1,16))::bit(64)::bigint # 0
  );
$$;
```

### Apêndice B – Função SQL (índices)
```sql
CREATE OR REPLACE FUNCTION r3a_util.generate_index_sql(_pages_per_range integer DEFAULT 128, _fillfactor integer DEFAULT 90)
RETURNS TABLE(leaf regclass, kind text, sql text)
LANGUAGE plpgsql AS $$
DECLARE r record; bn text; br text; BEGIN
  FOR r IN SELECT lp.leaf AS rleaf FROM r3a_util.leaf_partitions() lp LOOP
    SELECT btree_name, brin_ts_name INTO bn, br FROM r3a_util.index_names(r.rleaf);
    leaf := r.rleaf; kind := 'btree';
    sql  := format('CREATE INDEX CONCURRENTLY IF NOT EXISTS %I ON %s (coin_id, "interval", "timestamp")', bn, r.rleaf);
    RETURN NEXT;
    leaf := r.rleaf; kind := 'brin_ts';
    sql  := format('CREATE INDEX CONCURRENTLY IF NOT EXISTS %I ON %s USING brin ("timestamp") WITH (pages_per_range = %s)', br, r.rleaf, _pages_per_range);
    RETURN NEXT;
    leaf := r.rleaf; kind := 'fillfactor';
    sql  := format('ALTER TABLE %s SET (fillfactor = %s)', r.rleaf, _fillfactor);
    RETURN NEXT;
  END LOOP; END
$$;
```

> **Wrapper opcional com limite:**
>
> ```sql
> CREATE OR REPLACE FUNCTION r3a_util.generate_index_sql_limited(
>   _pages_per_range integer DEFAULT 128,
>   _fillfactor      integer DEFAULT 90,
>   _max_ops         integer DEFAULT NULL
> ) RETURNS TABLE(leaf regclass, kind text, sql text)
> LANGUAGE sql AS $$
>   SELECT leaf, kind, sql
>   FROM r3a_util.generate_index_sql(_pages_per_range, _fillfactor)
>   ORDER BY 1,2
>   LIMIT COALESCE(_max_ops, 2147483647);
> $$;
> ```

---

**Checklist final de saúde**
- [ ] `helm lint` OK nos dois charts.
- [ ] SA `r3a-sync-sa` presente e referenciado, sem conflitos de ownership.
- [ ] `r3a-regcred` válido (PAT), `imagePullSecrets` referenciados.
- [ ] `concurrencyPolicy: Forbid` + locks aplicados onde necessário.
- [ ] `activeDeadlineSeconds`, `backoffLimit`, `ttlSecondsAfterFinished` ajustados.
- [ ] Janitor respeitando `protectedSelectors` e `deleteAfterSeconds`.
- [ ] Sem erros `out of shared memory` após limitação de ops/locks/timeouts (ou tunado `max_locks_per_transaction`).

