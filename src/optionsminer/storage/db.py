"""SQLite engine + session factory."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime

from sqlalchemy import create_engine, event, inspect
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from optionsminer.config import settings
from optionsminer.storage.models import Base

log = logging.getLogger(__name__)


def _make_engine() -> Engine:
    eng = create_engine(
        settings.db_url,
        echo=False,
        future=True,
        connect_args={"check_same_thread": False, "timeout": 30},
    )

    @event.listens_for(eng, "connect")
    def _set_sqlite_pragma(dbapi_conn, _record):  # noqa: ANN001
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA temp_store=MEMORY")
        cur.execute("PRAGMA cache_size=-64000")  # 64 MB
        cur.close()

    return eng


engine: Engine = _make_engine()
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)


def _migrate_dt15_to_variant_pk() -> None:
    """One-time migration: dt15_predictions PK changed from `pred_date` to
    `(pred_date, variant)` and gained M_up/M_dn/R1 columns.

    SQLite can't ALTER PRIMARY KEY in place, so we rename the old table out
    of the way and let create_all() build the new one. The user re-runs the
    backfill (which is fast — ~10 sec for 60 days). Old rows are preserved
    under a timestamped suffix in case anyone wants to inspect them.
    """
    insp = inspect(engine)
    if "dt15_predictions" not in insp.get_table_names():
        return  # fresh install, nothing to migrate
    cols = {c["name"] for c in insp.get_columns("dt15_predictions")}
    if "variant" in cols:
        return  # already migrated

    suffix = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    legacy_name = f"dt15_predictions_legacy_{suffix}"
    with engine.begin() as conn:
        conn.exec_driver_sql(f"ALTER TABLE dt15_predictions RENAME TO {legacy_name}")
    log.warning(
        "Migrated dt15_predictions: old single-PK table renamed to %s. "
        "Re-run the DT15 Backtest 'Backfill last N days' to repopulate "
        "with the new (pred_date, variant) schema.",
        legacy_name,
    )


def _migrate_dt15_add_sigma_r1_cols() -> None:
    """Add sigma_r1_used + sigma_r1_source columns if missing (v2 schema).

    Safe SQLite ALTER (no PK change). Old rows get NULL for the new columns —
    they used the locked σ_R1=0.00142, which the dashboard handles when
    sigma_r1_source IS NULL. Backfilling overwrites those rows with the new
    rolling σ_R1.
    """
    insp = inspect(engine)
    if "dt15_predictions" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("dt15_predictions")}
    with engine.begin() as conn:
        if "sigma_r1_used" not in cols:
            conn.exec_driver_sql("ALTER TABLE dt15_predictions ADD COLUMN sigma_r1_used FLOAT")
            log.info("Added sigma_r1_used column to dt15_predictions")
        if "sigma_r1_source" not in cols:
            conn.exec_driver_sql(
                "ALTER TABLE dt15_predictions ADD COLUMN sigma_r1_source VARCHAR(16)"
            )
            log.info("Added sigma_r1_source column to dt15_predictions")


def init_db() -> None:
    """Create all tables. Idempotent. Runs in-place migrations as needed."""
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    _migrate_dt15_to_variant_pk()
    Base.metadata.create_all(engine)
    _migrate_dt15_add_sigma_r1_cols()  # after create_all so first install is no-op


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional session context — commits on success, rolls back on error."""
    sess = SessionLocal()
    try:
        yield sess
        sess.commit()
    except Exception:
        sess.rollback()
        raise
    finally:
        sess.close()
