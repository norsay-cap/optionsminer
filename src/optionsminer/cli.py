"""Command-line entry points: `optionsminer-init-db` and `optionsminer-snapshot`."""

from __future__ import annotations

import argparse
import logging
import sys

from optionsminer.config import settings
from optionsminer.providers.ingest import run_snapshot
from optionsminer.providers.yahoo import YahooProvider
from optionsminer.storage import disk_guard
from optionsminer.storage.db import init_db as _init_db


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def init_db() -> None:
    _setup_logging()
    _init_db()
    print(f"Initialised SQLite at {settings.db_path}")


def snapshot() -> None:
    _setup_logging()
    parser = argparse.ArgumentParser(description="Take an EOD options snapshot.")
    parser.add_argument(
        "--tickers",
        nargs="+",
        default=settings.tickers,
        help="Tickers to snapshot (default from config: %(default)s)",
    )
    parser.add_argument(
        "--max-dte",
        type=int,
        default=settings.snapshot_max_dte,
        help="Skip expiries beyond this many calendar days",
    )
    parser.add_argument(
        "--no-prune",
        action="store_true",
        help="Skip post-snapshot disk-cap enforcement",
    )
    args = parser.parse_args()

    _init_db()
    provider = YahooProvider()

    failures: list[tuple[str, str]] = []
    for tk in args.tickers:
        try:
            res = run_snapshot(provider, tk)
            print(
                f"[{tk}] snapshot_id={res['snapshot_id']} spot={res['spot']:.2f} "
                f"quotes={res['n_quotes']} bars_upserted={res['n_bars_upserted']}"
            )
        except Exception as e:  # noqa: BLE001
            logging.exception("Snapshot failed for %s", tk)
            failures.append((tk, str(e)))

    if not args.no_prune:
        rep = disk_guard.enforce()
        print(f"Disk: {rep.used_gb:.3f}/{rep.cap_gb:.0f} GB ({rep.used_pct:.2%}) — {rep.state}")

    if failures:
        for tk, msg in failures:
            print(f"FAILED: {tk}: {msg}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    snapshot()
