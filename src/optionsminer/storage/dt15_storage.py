"""Persistence + statistics for DT15 daily-range predictions.

Lifecycle:
1. `record_prediction(levels)` — write today's prediction row (UPSERT on
   pred_date so a later override-anchor lock replaces the auto-recorded
   yfinance-anchor version).
2. `settle_pending(asof=today)` — for every prediction whose pred_date is in
   the past and whose `settled_at` is NULL, fetch ES=F's actual O/H/L/C for
   that date and fill the outcome + hit-flag columns.
3. `summary()`, `recent(n)`, `to_dataframe()` — read-side helpers used by
   the Backtest page.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import pandas as pd
from sqlalchemy import func, select

from optionsminer.analytics.dt15 import K_BM, M_DN, M_UP, VIX_BLEND_K, DT15Levels, fetch_daily_bars
from optionsminer.storage.db import session_scope
from optionsminer.storage.models import DT15Prediction

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class DT15Summary:
    n_total: int
    n_settled: int
    in_band_rate: float | None       # P(low >= avg- AND high <= avg+)
    above_avg_plus_rate: float | None
    below_avg_minus_rate: float | None
    touched_ext_plus_rate: float | None
    touched_ext_minus_rate: float | None
    range_mae: float | None          # mean absolute error (points)
    range_mape: float | None         # mean absolute percentage error
    range_bias: float | None         # mean signed error (positive = under-predicting)
    range_correlation: float | None  # Pearson correlation of pred vs actual range


def record_prediction(levels: DT15Levels) -> DT15Prediction:
    """UPSERT today's prediction. Only the prediction columns are touched —
    if a row already exists with realised outcomes, those are preserved.
    """
    pred_source = "rm5" if levels.rm5 >= VIX_BLEND_K * levels.range_vix else "vix"
    now = datetime.utcnow().replace(tzinfo=None)

    with session_scope() as s:
        row = s.get(DT15Prediction, levels.asof_date)
        if row is None:
            row = DT15Prediction(
                pred_date=levels.asof_date,
                today_open_yf=levels.today_open_yf,
                today_open_used=levels.today_open_used,
                anchor_source=levels.anchor_source,
                prior_close=levels.prior_close,
                vix_prior_close=levels.vix_prior_close,
                rm5=levels.rm5,
                range_vix=levels.range_vix,
                range_pred=levels.range_pred,
                pred_source=pred_source,
                avg_plus=levels.avg_plus,
                avg_minus=levels.avg_minus,
                ext_plus=levels.ext_plus,
                ext_minus=levels.ext_minus,
                created_at=now,
            )
            s.add(row)
        else:
            # Only update prediction fields; never overwrite realised outcome
            row.today_open_yf = levels.today_open_yf
            row.today_open_used = levels.today_open_used
            row.anchor_source = levels.anchor_source
            row.prior_close = levels.prior_close
            row.vix_prior_close = levels.vix_prior_close
            row.rm5 = levels.rm5
            row.range_vix = levels.range_vix
            row.range_pred = levels.range_pred
            row.pred_source = pred_source
            row.avg_plus = levels.avg_plus
            row.avg_minus = levels.avg_minus
            row.ext_plus = levels.ext_plus
            row.ext_minus = levels.ext_minus
            row.created_at = now
        s.flush()
        return row


def _settle_one(row: DT15Prediction, bar: pd.Series) -> None:
    """Fill outcome + hit-flag columns on a row using the realised daily bar."""
    o, h, l, c = float(bar["Open"]), float(bar["High"]), float(bar["Low"]), float(bar["Close"])
    rng = h - l
    err = rng - row.range_pred

    row.actual_open = o
    row.actual_high = h
    row.actual_low = l
    row.actual_close = c
    row.actual_range = rng
    row.range_error = err
    row.range_error_pct = err / row.range_pred if row.range_pred else None

    row.high_above_avg_plus = 1 if h > row.avg_plus else 0
    row.low_below_avg_minus = 1 if l < row.avg_minus else 0
    row.inside_avg_band = 1 if (h <= row.avg_plus and l >= row.avg_minus) else 0
    row.touched_ext_plus = 1 if h >= row.ext_plus else 0
    row.touched_ext_minus = 1 if l <= row.ext_minus else 0
    row.settled_at = datetime.utcnow().replace(tzinfo=None)


def settle_pending(asof: date | None = None, lookback_days: int = 60) -> int:
    """Settle every unsettled prediction whose pred_date < asof.

    `lookback_days` bounds how far back we'll look for unsettled rows — keeps
    the yfinance pull cheap. For a daily scheduler this is plenty.

    Returns number of rows settled.
    """
    asof = asof or date.today()
    cutoff = asof - timedelta(days=lookback_days)

    with session_scope() as s:
        pending = list(
            s.scalars(
                select(DT15Prediction).where(
                    DT15Prediction.settled_at.is_(None),
                    DT15Prediction.pred_date < asof,
                    DT15Prediction.pred_date >= cutoff,
                )
            )
        )
        if not pending:
            return 0

        try:
            es = fetch_daily_bars("ES=F", period=f"{lookback_days + 5}d")
        except Exception as e:  # noqa: BLE001
            log.warning("DT15 settlement: ES=F fetch failed: %s", e)
            return 0

        # Index by date for O(1) lookup
        es_idx = {idx.date() if hasattr(idx, "date") else idx: row for idx, row in es.iterrows()}

        n = 0
        for p in pending:
            bar = es_idx.get(p.pred_date)
            if bar is None:
                continue  # market holiday or data gap
            _settle_one(p, bar)
            n += 1
        return n


def summary(min_date: date | None = None) -> DT15Summary:
    """Aggregate hit-rate / error stats over all settled predictions."""
    with session_scope() as s:
        q = select(DT15Prediction)
        if min_date is not None:
            q = q.where(DT15Prediction.pred_date >= min_date)
        rows = list(s.scalars(q))

    n_total = len(rows)
    settled = [r for r in rows if r.settled_at is not None]
    n_settled = len(settled)

    def _rate(field: str) -> float | None:
        vals = [getattr(r, field) for r in settled if getattr(r, field) is not None]
        return float(sum(vals) / len(vals)) if vals else None

    pred = [r.range_pred for r in settled]
    actual = [r.actual_range for r in settled]
    errs = [r.range_error for r in settled if r.range_error is not None]
    errs_pct = [r.range_error_pct for r in settled if r.range_error_pct is not None]

    mae = float(sum(abs(e) for e in errs) / len(errs)) if errs else None
    mape = float(sum(abs(e) for e in errs_pct) / len(errs_pct)) if errs_pct else None
    bias = float(sum(errs) / len(errs)) if errs else None

    corr = None
    if len(pred) >= 3:
        ser_p, ser_a = pd.Series(pred), pd.Series(actual)
        try:
            corr = float(ser_p.corr(ser_a))
        except Exception:  # noqa: BLE001
            corr = None

    return DT15Summary(
        n_total=n_total,
        n_settled=n_settled,
        in_band_rate=_rate("inside_avg_band"),
        above_avg_plus_rate=_rate("high_above_avg_plus"),
        below_avg_minus_rate=_rate("low_below_avg_minus"),
        touched_ext_plus_rate=_rate("touched_ext_plus"),
        touched_ext_minus_rate=_rate("touched_ext_minus"),
        range_mae=mae,
        range_mape=mape,
        range_bias=bias,
        range_correlation=corr,
    )


def to_dataframe(limit: int = 500) -> pd.DataFrame:
    """All predictions (settled + pending), most-recent first, as a DataFrame."""
    with session_scope() as s:
        rows = list(
            s.scalars(
                select(DT15Prediction)
                .order_by(DT15Prediction.pred_date.desc())
                .limit(limit)
            )
        )
    if not rows:
        return pd.DataFrame()

    return pd.DataFrame([
        {
            "pred_date": r.pred_date,
            "anchor_source": r.anchor_source,
            "anchor": r.today_open_used,
            "prior_close": r.prior_close,
            "vix_prior_close": r.vix_prior_close,
            "rm5": r.rm5,
            "range_vix": r.range_vix,
            "range_pred": r.range_pred,
            "pred_source": r.pred_source,
            "avg_plus": r.avg_plus,
            "avg_minus": r.avg_minus,
            "ext_plus": r.ext_plus,
            "ext_minus": r.ext_minus,
            "actual_open": r.actual_open,
            "actual_high": r.actual_high,
            "actual_low": r.actual_low,
            "actual_close": r.actual_close,
            "actual_range": r.actual_range,
            "range_error": r.range_error,
            "range_error_pct": r.range_error_pct,
            "inside_avg_band": r.inside_avg_band,
            "high_above_avg_plus": r.high_above_avg_plus,
            "low_below_avg_minus": r.low_below_avg_minus,
            "touched_ext_plus": r.touched_ext_plus,
            "touched_ext_minus": r.touched_ext_minus,
            "settled_at": r.settled_at,
        }
        for r in rows
    ])


def backfill_from_history(days: int = 60) -> int:
    """Reconstruct historical predictions from yfinance ES + VIX history.

    For each of the last `days` trading days, recompute what DT15 *would have
    predicted* using only data available before that day, then settle against
    the actual outcome. Lets you bootstrap a backtest without waiting weeks
    for live data to accumulate.

    Returns number of historical days inserted.
    """
    es = fetch_daily_bars("ES=F", period=f"{days + 30}d")
    vix = fetch_daily_bars("^VIX", period=f"{days + 30}d")

    if isinstance(es.columns, pd.MultiIndex):
        es.columns = es.columns.get_level_values(0)
    if isinstance(vix.columns, pd.MultiIndex):
        vix.columns = vix.columns.get_level_values(0)

    if len(es) < 7:
        return 0

    # For each "today" we need at least 7 trading days of prior data
    inserted = 0
    es_dates = list(es.index)
    target_dates = es_dates[-days:] if len(es_dates) > days else es_dates[6:]

    for current in target_dates:
        # Slice: everything up to and including `current`
        es_window = es.loc[:current]
        vix_window = vix.loc[:current]
        if len(es_window) < 7:
            continue

        try:
            from optionsminer.analytics.dt15 import compute_levels

            lv = compute_levels(es_window, vix_window, today_open_override=None)
        except ValueError:
            continue

        # Persist
        record_prediction(lv)
        inserted += 1

    # One settlement pass to fill outcomes for all the days we just backfilled
    settle_pending()
    return inserted
