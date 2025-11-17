#!/usr/bin/env python3
import os, sys, psycopg2

DB_URL = os.environ.get("DB_URL")

SQLS = [
    ("recent_1m",  "SELECT COUNT(*) FROM r3a.ohlcv_partitioned WHERE \"interval\"='1m'  AND \"timestamp\" > now()-interval '24 hours'"),
    ("recent_15m", "SELECT COUNT(*) FROM r3a.ohlcv_partitioned WHERE \"interval\"='15m' AND \"timestamp\" > now()-interval '24 hours'"),
    ("recent_1h",  "SELECT COUNT(*) FROM r3a.ohlcv_partitioned WHERE \"interval\"='1h'  AND \"timestamp\" > now()-interval '24 hours'"),
    ("recent_1d",  "SELECT COUNT(*) FROM r3a.ohlcv_partitioned WHERE \"interval\"='1d'  AND \"timestamp\" > now()-interval '7 days'"),
]

MV_LIST = [
    # leave empty if you still don't have these MVs
    # "r3a.mv_scanner_top30_1m",
]

def refresh_mv(conn, mv):
    with conn.cursor() as cur:
        cur.execute(f"REFRESH MATERIALIZED VIEW CONCURRENTLY {mv};")
    return f"refreshed: {mv}"

def main():
    if not DB_URL:
        print("[ERR] DB_URL not set", file=sys.stderr)
        return 1
    dsn = DB_URL.replace("postgresql+psycopg2", "postgresql")
    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cur:
            for name, sql in SQLS:
                cur.execute(sql)
                c = cur.fetchone()[0]
                print(f"{name}: {c}")
        for mv in MV_LIST:
            print(refresh_mv(conn, mv))
    finally:
        conn.close()
    return 0

if __name__ == "__main__":
    sys.exit(main())