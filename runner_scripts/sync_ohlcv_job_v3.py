#!/usr/bin/env python3
# infra/runner/runner_scripts/sync_ohlcv_job_v3.py
import os, sys, time
from datetime import datetime
from sqlalchemy import create_engine, text
from utils.logging_utils import setup_logging
from core.data.binance_downloader import BinanceOHLCVSync
from runner_scripts.util_db_lock import advisory_lock

DB_URL = os.environ.get("DB_URL")
BINANCE_API_KEY = os.environ.get("BINANCE_API_KEY", "")
BINANCE_API_SECRET = os.environ.get("BINANCE_API_SECRET", "")

SYMBOLS_ENV = [s.strip() for s in os.environ.get("SYNC_SYMBOLS","").split(",") if s.strip()]
INTERVALS = [i.strip() for i in os.environ.get("SYNC_INTERVALS","").split(",") if i.strip()]
AUTO_PERIOD = os.environ.get("AUTO_PERIOD","true").lower() == "true"
START = os.environ.get("SYNC_START","")
END = os.environ.get("SYNC_END","now")
BATCH_SIZE = int(os.environ.get("BATCH_SIZE","500"))
FALLBACK_START = os.environ.get("FALLBACK_START","2020-01-01")

logger = setup_logging(
    name="sync_job_v3",
    filename=os.environ.get("LOG_FILE","/var/log/sync_job_v3.log"),
    log_level=os.environ.get("LOG_LEVEL","INFO"),
    log_to_console=True, log_to_file=True, log_to_db=False, db_conn=DB_URL
)

def parse_dt(s: str):
    if not s or s.lower() == "now":
        return datetime.utcnow()
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return datetime.strptime(s, "%Y-%m-%d")

def main():
    if not DB_URL:
        print("DB_URL não definido", file=sys.stderr); return 2
    if not INTERVALS:
        print("SYNC_INTERVALS é obrigatório", file=sys.stderr); return 2

    # intervalo “principal” deste Pod (para lock por intervalo)
    interval_for_lock = os.getenv("SYNC_INTERVAL", os.getenv("INTERVAL", INTERVALS[0]))
    scope = "r3a-sync"
    key   = f"interval:{interval_for_lock}"

    engine = create_engine(DB_URL, pool_size=2, max_overflow=0, pool_pre_ping=True)

    # LOCK por INTERVALO: impede 2 Pods deste mesmo intervalo rodarem simultâneos
    with advisory_lock(scope, key, engine) as got:
        if not got:
            logger.info(f"[LOCK] Já existe job ativo para {key}. Abortando.")
            return 0

        syncer = BinanceOHLCVSync(
            db_conn=DB_URL,
            binance_api_key=BINANCE_API_KEY,
            binance_api_secret=BINANCE_API_SECRET,
            resume_state_file="ohlcv_resume_state.json",
            logger=logger
        )

        if SYMBOLS_ENV:
            symbols = SYMBOLS_ENV
            logger.info(f"[SYMBOLS] usando da env: {symbols}")
        else:
            symbols = syncer.get_symbols_from_db(order_by="pair_name ASC")
            logger.info(f"[SYMBOLS] carregados do DB: {len(symbols)} pares")

        resume_state = syncer.load_resume_state()

        if AUTO_PERIOD:
            end_time = datetime.utcnow()
            for symbol in symbols:
                for itv in INTERVALS:
                    # LOCK fino (símbolo+intervalo) — cada iteração pega e solta
                    lk = f"{symbol}:{itv}"
                    with engine.connect() as conn:
                        ok = conn.execute(text("SELECT r3a_util.acquire_lock(:s,:k)"), {"s": scope, "k": lk}).scalar()
                        if not ok:
                            logger.info(f"[LOCK] ocupado {lk}, outro job em andamento; skip.")
                            continue
                        try:
                            last = syncer.get_last_timestamp_from_db(symbol, itv)
                            start = last if last else parse_dt(FALLBACK_START)
                            logger.info(f"[AUTO] {symbol}-{itv}: {start} -> {end_time}")
                            t0 = time.time()
                            try:
                                syncer.sync_ohlcv(symbol, itv, start, end_time, batch_size=BATCH_SIZE, resume_state=resume_state)
                                syncer.warn_on_db_gaps(symbol, itv, start, end_time, auto_resync=True, resync_gap_limit=100)
                            finally:
                                t1 = time.time()
                                req = len(syncer.get_expected_timestamps(start, end_time, itv))
                                ins = len(syncer.load_ohlcv_from_db(symbol, itv, start, end_time))
                                syncer.log_sync_audit(symbol, itv, start, end_time, req, ins, req-ins, t1-t0, "OK" if req==ins else "GAPS")
                        finally:
                            conn.execute(text("SELECT r3a_util.release_lock(:s,:k)"), {"s": scope, "k": lk})
        else:
            start = parse_dt(START); end = parse_dt(END)
            for symbol in symbols:
                for itv in INTERVALS:
                    lk = f"{symbol}:{itv}"
                    with engine.connect() as conn:
                        ok = conn.execute(text("SELECT r3a_util.acquire_lock(:s,:k)"), {"s": scope, "k": lk}).scalar()
                        if not ok:
                            logger.info(f"[LOCK] ocupado {lk}, outro job em andamento; skip.")
                            continue
                        try:
                            logger.info(f"[STATIC] {symbol}-{itv}: {start} -> {end}")
                            t0 = time.time()
                            try:
                                syncer.sync_ohlcv(symbol, itv, start, end, batch_size=BATCH_SIZE, resume_state=resume_state)
                                syncer.warn_on_db_gaps(symbol, itv, start, end, auto_resync=True, resync_gap_limit=100)
                            finally:
                                t1 = time.time()
                                req = len(syncer.get_expected_timestamps(start, end, itv))
                                ins = len(syncer.load_ohlcv_from_db(symbol, itv, start, end))
                                syncer.log_sync_audit(symbol, itv, start, end, req, ins, req-ins, t1-t0, "OK" if req==ins else "GAPS")
                        finally:
                            conn.execute(text("SELECT r3a_util.release_lock(:s,:k)"), {"s": scope, "k": lk})
    engine.dispose()
    return 0

if __name__ == "__main__":
    sys.exit(main())
