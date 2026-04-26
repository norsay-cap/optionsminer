"""Snapshot ingest: provider chain → IV recompute → greeks → DB rows."""

from __future__ import annotations

import logging
from datetime import date, timedelta

import numpy as np
import pandas as pd

from optionsminer.analytics import greeks as gk
from optionsminer.config import settings
from optionsminer.providers.base import ChainSnapshot, DataProvider
from optionsminer.storage.db import session_scope
from optionsminer.storage.models import OptionQuote, Snapshot, UnderlyingBar

log = logging.getLogger(__name__)


def enrich_with_greeks(snap: ChainSnapshot, *, r: float, q: float) -> pd.DataFrame:
    """Recompute IV from mid quote, then compute greeks per row.

    Returns a DataFrame matching the OptionQuote table columns.
    """
    df = snap.quotes.copy()

    # Tradeable price: prefer mid, fall back to last when mid missing
    df["px"] = df["mid"].where(df["mid"].notna() & (df["mid"] > 0), df["last"])

    # Time to expiry in years (calendar)
    today = snap.snapshot_ts.date()
    df["T"] = df["expiry"].apply(lambda d: max((d - today).days, 0)) / 365.0

    # IV recompute per row (scalar — vectorising Brent is more code than it saves)
    iv_recalc: list[float | None] = []
    for px, K, T, cp in zip(df["px"], df["strike"], df["T"], df["cp"], strict=False):
        if (
            not isinstance(px, float | int | np.floating)
            or px is None
            or pd.isna(px)
            or px <= 0
            or T <= 0
        ):
            iv_recalc.append(None)
            continue
        iv = gk.implied_vol_brent(float(px), snap.spot, float(K), float(T), r, q, str(cp))
        iv_recalc.append(iv if iv is not None and 0.001 < iv < 8.0 else None)
    df["iv_recalc"] = iv_recalc

    # Greeks computed with the recomputed IV; fallback to provider IV when
    # ours failed (illiquid wings the solver couldn't anchor)
    iv_for_greeks = df["iv_recalc"].where(df["iv_recalc"].notna(), df["iv_provider"])
    df["iv_for_greeks"] = iv_for_greeks

    valid = (df["T"] > 0) & iv_for_greeks.notna() & (iv_for_greeks > 0)

    S, K, T = snap.spot, df["strike"].to_numpy(float), df["T"].to_numpy(float)
    sig = iv_for_greeks.fillna(np.nan).to_numpy(float)
    cp = df["cp"].to_numpy(str)

    with np.errstate(divide="ignore", invalid="ignore"):
        d = gk.delta(S, K, T, r, q, sig, cp)
        g = gk.gamma(S, K, T, r, q, sig)
        v = gk.vega(S, K, T, r, q, sig)
        th = gk.theta(S, K, T, r, q, sig, cp)
        ch = gk.charm(S, K, T, r, q, sig, cp)
        va = gk.vanna(S, K, T, r, q, sig)

    invalid_mask = (~valid).to_numpy()
    for arr in (d, g, v, th, ch, va):
        arr[invalid_mask] = np.nan

    df["delta"], df["gamma"], df["vega"], df["theta"], df["charm"], df["vanna"] = (
        d, g, v, th, ch, va,
    )

    # Final ORM-ready frame
    df = df.rename(columns={"iv_provider": "iv_yahoo"})
    keep = [
        "expiry", "strike", "cp", "dte", "bid", "ask", "last", "mid",
        "volume", "open_interest", "iv_yahoo", "iv_recalc",
        "delta", "gamma", "vega", "theta", "charm", "vanna",
        "last_trade_ts",
    ]
    return df[keep]


def persist_snapshot(snap: ChainSnapshot, enriched: pd.DataFrame, *, source: str) -> int:
    """Write a snapshot + its quotes to the DB. Returns snapshot_id."""
    div_q = settings.div_yield_for(snap.ticker)
    with session_scope() as sess:
        s_row = Snapshot(
            ticker=snap.ticker,
            snapshot_ts=snap.snapshot_ts.replace(tzinfo=None),  # sqlite-friendly
            spot=snap.spot,
            risk_free=settings.risk_free_rate,
            div_yield=div_q,
            source=source,
        )
        sess.add(s_row)
        sess.flush()  # populate snapshot_id

        rows = []
        for r in enriched.itertuples(index=False):
            rows.append(
                OptionQuote(
                    snapshot_id=s_row.snapshot_id,
                    expiry=r.expiry,
                    strike=float(r.strike),
                    cp=r.cp,
                    dte=int(r.dte),
                    bid=_safe_float(r.bid),
                    ask=_safe_float(r.ask),
                    last=_safe_float(r.last),
                    mid=_safe_float(r.mid),
                    volume=_safe_int(r.volume),
                    open_interest=_safe_int(r.open_interest),
                    iv_yahoo=_safe_float(r.iv_yahoo),
                    iv_recalc=_safe_float(r.iv_recalc),
                    delta=_safe_float(r.delta),
                    gamma=_safe_float(r.gamma),
                    vega=_safe_float(r.vega),
                    theta=_safe_float(r.theta),
                    charm=_safe_float(r.charm),
                    vanna=_safe_float(r.vanna),
                    last_trade_ts=(
                        pd.Timestamp(r.last_trade_ts).to_pydatetime().replace(tzinfo=None)
                        if pd.notna(r.last_trade_ts)
                        else None
                    ),
                )
            )
        sess.bulk_save_objects(rows)
        return s_row.snapshot_id


def persist_bars(ticker: str, bars: pd.DataFrame) -> int:
    """Upsert daily OHLCV. Returns rows touched."""
    if bars.empty:
        return 0
    with session_scope() as sess:
        n = 0
        for r in bars.itertuples(index=False):
            existing = sess.get(UnderlyingBar, (ticker.upper(), r.bar_date))
            if existing:
                existing.open, existing.high, existing.low, existing.close = (
                    float(r.open), float(r.high), float(r.low), float(r.close),
                )
                existing.volume = _safe_int(r.volume)
            else:
                sess.add(
                    UnderlyingBar(
                        ticker=ticker.upper(),
                        bar_date=r.bar_date,
                        open=float(r.open),
                        high=float(r.high),
                        low=float(r.low),
                        close=float(r.close),
                        volume=_safe_int(r.volume),
                    )
                )
            n += 1
        return n


def run_snapshot(provider: DataProvider, ticker: str) -> dict:
    """End-to-end: fetch chain, enrich, persist, derive metrics, return summary."""
    snap = provider.fetch_chain(ticker, max_dte=settings.snapshot_max_dte)
    enriched = enrich_with_greeks(
        snap,
        r=settings.risk_free_rate,
        q=settings.div_yield_for(ticker),
    )

    # Bars first — VRP needs them; pull before metrics computation
    start = (snap.snapshot_ts.date() - timedelta(days=90))
    try:
        bars = provider.fetch_underlying_history(ticker, start=start)
        n_bars = persist_bars(ticker, bars)
    except Exception as e:  # noqa: BLE001
        log.warning("Underlying history fetch failed for %s: %s", ticker, e)
        n_bars = 0

    sid = persist_snapshot(snap, enriched, source=provider.name)

    # Auto-compute and store the DerivedMetrics row
    try:
        from optionsminer.analytics.compute import compute_and_store

        compute_and_store(sid)
        n_metrics = 1
    except Exception as e:  # noqa: BLE001
        log.exception("Metrics computation failed for snapshot %s: %s", sid, e)
        n_metrics = 0

    return {
        "snapshot_id": sid,
        "ticker": ticker,
        "spot": snap.spot,
        "n_quotes": len(enriched),
        "n_bars_upserted": n_bars,
        "metrics_written": n_metrics,
    }


# -- helpers ---------------------------------------------------------------

def _safe_float(x) -> float | None:  # noqa: ANN001
    if x is None or pd.isna(x):
        return None
    f = float(x)
    return f if np.isfinite(f) else None


def _safe_int(x) -> int | None:  # noqa: ANN001
    if x is None or pd.isna(x):
        return None
    return int(x)


__all__ = ["enrich_with_greeks", "persist_snapshot", "persist_bars", "run_snapshot"]


# Convenience for callers that don't want to wire dates manually
_ = date  # keep import in case future versions of mypy complain
