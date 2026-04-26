"""Optional in-process scheduler: takes a daily EOD snapshot inside the container.

Activated by setting OPTIONSMINER_ENABLE_SCHEDULER=true. By default the
scheduler is OFF — Coolify can drive snapshots externally if preferred.

When ON, the entrypoint launches both the Streamlit server *and* this
scheduler in the same container. APScheduler's BackgroundScheduler runs the
job in a worker thread so it doesn't block the UI.

Default schedule: 21:15 UTC daily (~ 4:15 PM ET / 3:15 PM CT) — after the
US equity options market close.
"""

from __future__ import annotations

import logging
import os
import sys

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from optionsminer.config import settings
from optionsminer.providers.ingest import run_snapshot
from optionsminer.providers.yahoo import YahooProvider
from optionsminer.storage import disk_guard
from optionsminer.storage.db import init_db

log = logging.getLogger(__name__)


def _job() -> None:
    log.info("Scheduled snapshot starting (tickers=%s)", settings.tickers)
    provider = YahooProvider()
    for tk in settings.tickers:
        try:
            res = run_snapshot(provider, tk)
            log.info(
                "Snapshot OK %s id=%s spot=%.2f quotes=%s bars=%s",
                tk, res["snapshot_id"], res["spot"], res["n_quotes"], res["n_bars_upserted"],
            )
        except Exception as e:  # noqa: BLE001
            log.exception("Snapshot FAIL for %s: %s", tk, e)
    rep = disk_guard.enforce()
    log.info("Disk: %.3f / %.0f GB (%s)", rep.used_gb, rep.cap_gb, rep.state)


def start() -> BackgroundScheduler:
    """Start the scheduler in the current process. Idempotent for one process."""
    init_db()

    schedule = os.environ.get("OPTIONSMINER_SCHEDULE_CRON", "15 21 * * 1-5")
    log.info("Scheduling daily snapshot at cron='%s' UTC", schedule)
    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(
        _job,
        trigger=CronTrigger.from_crontab(schedule, timezone="UTC"),
        id="daily_snapshot",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    scheduler.start()
    return scheduler


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    sched = start()
    log.info("Scheduler started; press Ctrl-C to exit.")
    try:
        # Keep process alive
        import time
        while True:
            time.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        sched.shutdown()
        sys.exit(0)
