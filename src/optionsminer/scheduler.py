"""Optional in-process scheduler: takes a daily snapshot inside the container.

Activated by setting OPTIONSMINER_ENABLE_SCHEDULER=true. By default the
scheduler is OFF — Coolify can drive snapshots externally if preferred.

When ON, the entrypoint launches both the Streamlit server *and* this
scheduler in the same container. APScheduler's BackgroundScheduler runs the
job in a worker thread so it doesn't block the UI.

Default schedule: 19:00 America/New_York daily Mon-Fri = 7 PM ET. Reasoning:
- yfinance options chains are stable from ~4:30 PM ET, so 7 PM is fine for
  the SPX/SPY snapshot.
- DT15 predictions need today's 6 PM ET ETH session open as the anchor;
  running at 7 PM gives yfinance a 1-hour buffer to publish that value.
- Using `America/New_York` (not UTC) means DST is handled — the run time
  stays at 7 PM ET year-round.
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

    # Record today's DT15 prediction for BOTH methodologies, with a staleness
    # check that detects when yfinance hasn't yet published the new session's
    # bar (returns the same data as the prior run). On staleness we log a
    # WARNING and skip the persist rather than overwriting good data with a
    # duplicate. Then settle any prior unsettled rows.
    try:
        from sqlalchemy import select

        from optionsminer.analytics.dt15 import VARIANTS, compute_live
        from optionsminer.storage import dt15_storage
        from optionsminer.storage.db import session_scope
        from optionsminer.storage.models import DT15Prediction

        for variant in VARIANTS:
            try:
                lv = compute_live(variant=variant)

                # Staleness check: did yfinance return the same bar as the
                # most-recent prior prediction for this variant?
                with session_scope() as sess:
                    prior = sess.scalars(
                        select(DT15Prediction)
                        .where(DT15Prediction.variant == variant)
                        .order_by(DT15Prediction.pred_date.desc())
                        .limit(1)
                    ).first()
                    is_stale = (
                        prior is not None
                        and prior.pred_date == lv.asof_date
                        and abs(prior.today_open_yf - lv.today_open_yf) < 0.01
                    )
                if is_stale:
                    log.warning(
                        "DT15 STALE ANCHOR (%s): yfinance returned the same bar "
                        "as the prior recorded prediction (pred_date=%s, "
                        "today_open_yf=%.2f). yfinance has not yet rolled the "
                        "new session's bar. Skipping persist to avoid "
                        "overwriting good data.",
                        variant, lv.asof_date, lv.today_open_yf,
                    )
                    continue

                dt15_storage.record_prediction(lv)
                log.info("DT15 (%s): recorded prediction for %s", variant, lv.asof_date)
            except Exception as e:  # noqa: BLE001
                log.exception("DT15 record FAIL for variant %s: %s", variant, e)
        n_settled = dt15_storage.settle_pending()
        log.info("DT15: settled %d prior rows across all variants", n_settled)
    except Exception as e:  # noqa: BLE001
        log.exception("DT15 scheduled record/settle FAIL: %s", e)

    rep = disk_guard.enforce()
    log.info("Disk: %.3f / %.0f GB (%s)", rep.used_gb, rep.cap_gb, rep.state)


def start() -> BackgroundScheduler:
    """Start the scheduler in the current process. Idempotent for one process."""
    init_db()

    tz = os.environ.get("OPTIONSMINER_SCHEDULE_TZ", "America/New_York")
    schedule = os.environ.get("OPTIONSMINER_SCHEDULE_CRON", "0 19 * * 1-5")
    log.info("Scheduling daily snapshot at cron='%s' tz='%s'", schedule, tz)
    scheduler = BackgroundScheduler(timezone=tz)
    scheduler.add_job(
        _job,
        trigger=CronTrigger.from_crontab(schedule, timezone=tz),
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
