"""Disk-usage guard.

Tracks total bytes under the data dir, warns past `disk_warn_pct` of the cap,
and prunes the oldest snapshots when usage exceeds the cap. Designed to be
called after every snapshot write.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import delete, func, select

from optionsminer.config import settings
from optionsminer.storage.db import session_scope
from optionsminer.storage.models import Snapshot

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class DiskReport:
    used_bytes: int
    cap_bytes: int
    warn_bytes: int

    @property
    def used_gb(self) -> float:
        return self.used_bytes / (1024**3)

    @property
    def cap_gb(self) -> float:
        return self.cap_bytes / (1024**3)

    @property
    def used_pct(self) -> float:
        return self.used_bytes / self.cap_bytes if self.cap_bytes else 0.0

    @property
    def state(self) -> str:
        if self.used_bytes >= self.cap_bytes:
            return "OVER"
        if self.used_bytes >= self.warn_bytes:
            return "WARN"
        return "OK"


def directory_size(path: Path) -> int:
    """Recursive byte total of all files under `path`. Skips broken symlinks."""
    total = 0
    if not path.exists():
        return 0
    for p in path.rglob("*"):
        try:
            if p.is_file():
                total += p.stat().st_size
        except (OSError, FileNotFoundError):
            continue
    return total


def report(data_dir: Path | None = None) -> DiskReport:
    d = data_dir or settings.data_dir
    used = directory_size(d)
    cap = int(settings.disk_cap_gb * (1024**3))
    warn = int(cap * settings.disk_warn_pct)
    return DiskReport(used_bytes=used, cap_bytes=cap, warn_bytes=warn)


def prune_oldest(target_bytes: int | None = None, min_keep: int = 10) -> int:
    """Delete oldest snapshots (by snapshot_ts) until usage <= target_bytes.

    Args:
        target_bytes: stop pruning when usage falls to this level. Defaults to
            `disk_warn_pct` of the cap so we leave headroom after a prune.
        min_keep: never drop below this many snapshots — even an over-cap DB
            should retain some history.

    Returns:
        Number of snapshots deleted.
    """
    if target_bytes is None:
        target_bytes = int(
            settings.disk_cap_gb * (1024**3) * settings.disk_warn_pct
        )

    deleted = 0
    while True:
        cur = report().used_bytes
        if cur <= target_bytes:
            break

        with session_scope() as sess:
            count = sess.scalar(select(func.count(Snapshot.snapshot_id)))
            if count is None or count <= min_keep:
                log.warning(
                    "Disk over cap but only %s snapshots remain (min_keep=%s) — stopping prune",
                    count,
                    min_keep,
                )
                break

            oldest = sess.scalars(
                select(Snapshot).order_by(Snapshot.snapshot_ts.asc()).limit(50)
            ).all()
            if not oldest:
                break
            ids = [s.snapshot_id for s in oldest]
            sess.execute(delete(Snapshot).where(Snapshot.snapshot_id.in_(ids)))
            deleted += len(ids)
            log.info("Pruned %s old snapshots; new total deleted=%s", len(ids), deleted)

        # SQLite needs VACUUM to actually release pages back to the OS.
        _vacuum()

    return deleted


def _vacuum() -> None:
    """Reclaim free pages so on-disk size matches logical size."""
    from optionsminer.storage.db import engine

    with engine.begin() as conn:
        conn.exec_driver_sql("VACUUM")


def enforce(prune_when_over: bool = True) -> DiskReport:
    """Single entry point — call after every snapshot write.

    Returns the post-enforcement disk report. Logs at WARN/ERROR appropriately.
    """
    rep = report()
    if rep.state == "OVER" and prune_when_over:
        log.error(
            "Disk usage %.2f GB exceeds cap %.2f GB — pruning oldest snapshots",
            rep.used_gb,
            rep.cap_gb,
        )
        prune_oldest()
        rep = report()
    elif rep.state == "WARN":
        log.warning(
            "Disk usage %.2f GB at %.0f%% of cap %.2f GB",
            rep.used_gb,
            rep.used_pct * 100,
            rep.cap_gb,
        )
    return rep
