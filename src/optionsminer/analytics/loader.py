"""Helpers to load a snapshot's chain back from the DB into a DataFrame
that the analytics functions can consume directly.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd
from sqlalchemy import select

from optionsminer.storage.db import session_scope
from optionsminer.storage.models import OptionQuote, Snapshot, UnderlyingBar


def latest_snapshot(ticker: str) -> Snapshot | None:
    with session_scope() as s:
        return s.scalars(
            select(Snapshot)
            .where(Snapshot.ticker == ticker.upper())
            .order_by(Snapshot.snapshot_ts.desc())
            .limit(1)
        ).first()


def list_snapshots(ticker: str, limit: int = 250) -> list[Snapshot]:
    with session_scope() as s:
        return list(
            s.scalars(
                select(Snapshot)
                .where(Snapshot.ticker == ticker.upper())
                .order_by(Snapshot.snapshot_ts.desc())
                .limit(limit)
            )
        )


def load_chain(snapshot_id: int) -> pd.DataFrame:
    """Return the OptionQuote rows for a snapshot as a DataFrame."""
    with session_scope() as s:
        rows = s.execute(
            select(
                OptionQuote.expiry,
                OptionQuote.strike,
                OptionQuote.cp,
                OptionQuote.dte,
                OptionQuote.bid,
                OptionQuote.ask,
                OptionQuote.last,
                OptionQuote.mid,
                OptionQuote.volume,
                OptionQuote.open_interest,
                OptionQuote.iv_yahoo,
                OptionQuote.iv_recalc,
                OptionQuote.delta,
                OptionQuote.gamma,
                OptionQuote.vega,
                OptionQuote.theta,
                OptionQuote.charm,
                OptionQuote.vanna,
                OptionQuote.last_trade_ts,
            ).where(OptionQuote.snapshot_id == snapshot_id)
        ).all()

    df = pd.DataFrame(rows, columns=[
        "expiry", "strike", "cp", "dte", "bid", "ask", "last", "mid",
        "volume", "open_interest", "iv_yahoo", "iv_recalc",
        "delta", "gamma", "vega", "theta", "charm", "vanna", "last_trade_ts",
    ])
    df["iv"] = df["iv_recalc"].where(df["iv_recalc"].notna(), df["iv_yahoo"])
    return df


def load_bars(ticker: str, lookback_days: int = 90) -> pd.DataFrame:
    with session_scope() as s:
        rows = s.execute(
            select(
                UnderlyingBar.bar_date,
                UnderlyingBar.open,
                UnderlyingBar.high,
                UnderlyingBar.low,
                UnderlyingBar.close,
                UnderlyingBar.volume,
            )
            .where(UnderlyingBar.ticker == ticker.upper())
            .order_by(UnderlyingBar.bar_date.desc())
            .limit(lookback_days)
        ).all()
    df = pd.DataFrame(rows, columns=["bar_date", "open", "high", "low", "close", "volume"])
    return df.sort_values("bar_date").reset_index(drop=True)


def history_df(ticker: str, limit: int = 250) -> pd.DataFrame:
    """Time series of derived metrics for charting trends."""
    with session_scope() as s:
        rows = s.execute(
            select(
                Snapshot.snapshot_ts,
                Snapshot.spot,
                # derived_metrics are 1:1 — left join surfaces NULLs for snapshots
                # without metrics yet (e.g. just-ingested, not yet computed).
            )
            .where(Snapshot.ticker == ticker.upper())
            .order_by(Snapshot.snapshot_ts.desc())
            .limit(limit)
        ).all()
    return pd.DataFrame(rows, columns=["snapshot_ts", "spot"])


__all__ = [
    "latest_snapshot",
    "list_snapshots",
    "load_chain",
    "load_bars",
    "history_df",
]


_ = datetime  # silence unused
