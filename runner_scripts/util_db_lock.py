# infra/runner/runner_scripts/util_db_lock.py
import os
from contextlib import contextmanager
from sqlalchemy import create_engine, text

DB_URL = os.environ.get("DB_URL")

@contextmanager
def advisory_lock(scope: str, key: str, engine=None):
    """
    Usa r3a_util.acquire_lock/_release_lock(scope,key) para garantir exclusão.
    O lock é por sessão; aqui abrimos uma conexão dedicada.
    """
    must_dispose = False
    if engine is None:
        if not DB_URL:
            raise RuntimeError("DB_URL não definido para advisory_lock()")
        engine = create_engine(DB_URL, pool_size=1, max_overflow=0, pool_pre_ping=True)
        must_dispose = True

    with engine.connect() as conn:
        ok = conn.execute(
            text("SELECT r3a_util.acquire_lock(:s,:k)"),
            {"s": scope, "k": key},
        ).scalar()
        if not ok:
            # Outro job já segurando o lock → sai silenciosamente
            yield False
            return
        try:
            yield True
        finally:
            conn.execute(
                text("SELECT r3a_util.release_lock(:s,:k)"),
                {"s": scope, "k": key},
            )
    if must_dispose:
        engine.dispose()
