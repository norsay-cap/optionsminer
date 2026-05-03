"""Persistence + statistics for DT15 daily-range predictions.

Two methodologies are tracked side-by-side per day via the composite PK
(pred_date, variant). All read/write functions take an optional `variant`
arg so the dashboard can filter and the scheduler can record both.

Lifecycle:
1. `record_prediction(levels)` — UPSERTs on (pred_date, variant). Variant
   comes from the DT15Levels object.
2. `settle_pending(asof, lookback_days, variant=None)` — for every
   unsettled prediction whose pred_date is in the past, fetches ES=F's
   actual O/H/L/C for that date and fills outcome + hit-flag columns.
   Variant filter optional; default settles everything.
3. Read helpers (`summary`, `to_dataframe`, `recent`) take optional
   variant arg to filter.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import pandas as pd
from sqlalchemy import select

from optionsminer.analytics.dt15 import DT15Levels, fetch_daily_bars
from optionsminer.storage.db import session_scope
from optionsminer.storage.models import DT15Prediction

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class DT15Summary:
    variant: str
    n_total: int
    n_settled: int
    in_band_rate: float | None
    above_avg_plus_rate: float | None
    below_avg_minus_rate: float | None
    touched_ext_plus_rate: float | None
    touched_ext_minus_rate: float | None
    range_mae: float | None
    range_mape: float | None
    range_bias: float | None
    range_correlation: float | None


def record_prediction(levels: DT15Levels) -> DT15Prediction:
    """UPSERT today's prediction. Preserves any already-settled outcome."""
    pred_source = "rm5" if levels.rm5 >= 0.60 * levels.range_vix else "vix"
    now = datetime.utcnow().replace(tzinfo=None)

    with session_scope() as s:
        row = s.get(DT15Prediction, (levels.asof_date, levels.variant))
        if row is None:
            row = DT15Prediction(
                pred_date=levels.asof_date,
                variant=levels.variant,
                today_open_yf=levels.today_open_yf,
                today_open_used=levels.today_open_used,
                anchor_source=levels.anchor_source,
                prior_close=levels.prior_close,
                vix_prior_close=levels.vix_prior_close,
                rm5=levels.rm5,
                range_vix=levels.range_vix,
                range_pred=levels.range_pred,
                pred_source=pred_source,
                m_up_used=levels.m_up_used,
                m_dn_used=levels.m_dn_used,
                r1=levels.r1,
                r1_normalized=levels.r1_normalized,
                sigma_r1_used=levels.sigma_r1_used,
                sigma_r1_source=levels.sigma_r1_source,
                avg_plus=levels.avg_plus,
                avg_minus=levels.avg_minus,
                ext_plus=levels.ext_plus,
                ext_minus=levels.ext_minus,
                created_at=now,
            )
            s.add(row)
        else:
            row.today_open_yf = levels.today_open_yf
            row.today_open_used = levels.today_open_used
            row.anchor_source = levels.anchor_source
            row.prior_close = levels.prior_close
            row.vix_prior_close = levels.vix_prior_close
            row.rm5 = levels.rm5
            row.range_vix = levels.range_vix
            row.range_pred = levels.range_pred
            row.pred_source = pred_source
            row.m_up_used = levels.m_up_used
            row.m_dn_used = levels.m_dn_used
            row.r1 = levels.r1
            row.r1_normalized = levels.r1_normalized
            row.sigma_r1_used = levels.sigma_r1_used
            row.sigma_r1_source = levels.sigma_r1_source
            row.avg_plus = levels.avg_plus
            row.avg_minus = levels.avg_minus
            row.ext_plus = levels.ext_plus
            row.ext_minus = levels.ext_minus
            row.created_at = now
        s.flush()
        return row


def _settle_one(row: DT15Prediction, bar: pd.Series) -> None:
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


def settle_pending(
    asof: date | None = None,
    lookback_days: int = 60,
    variant: str | None = None,
) -> int:
    """Settle every unsettled prediction whose pred_date < asof."""
    asof = asof or date.today()
    cutoff = asof - timedelta(days=lookback_days)

    with session_scope() as s:
        q = select(DT15Prediction).where(
            DT15Prediction.settled_at.is_(None),
            DT15Prediction.pred_date < asof,
            DT15Prediction.pred_date >= cutoff,
        )
        if variant is not None:
            q = q.where(DT15Prediction.variant == variant)
        pending = list(s.scalars(q))
        if not pending:
            return 0

        try:
            es = fetch_daily_bars("ES=F", period=f"{lookback_days + 5}d")
        except Exception as e:  # noqa: BLE001
            log.warning("DT15 settlement: ES=F fetch failed: %s", e)
            return 0

        es_idx = {idx.date() if hasattr(idx, "date") else idx: row for idx, row in es.iterrows()}

        n = 0
        for p in pending:
            bar = es_idx.get(p.pred_date)
            if bar is None:
                continue
            _settle_one(p, bar)
            n += 1
        return n


def summary(min_date: date | None = None, variant: str = "baseline") -> DT15Summary:
    """Aggregate stats for a single variant. Pass variant explicitly."""
    with session_scope() as s:
        q = select(DT15Prediction).where(DT15Prediction.variant == variant)
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
        try:
            corr = float(pd.Series(pred).corr(pd.Series(actual)))
        except Exception:  # noqa: BLE001
            corr = None

    return DT15Summary(
        variant=variant,
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


def to_dataframe(limit: int = 500, variant: str | None = None) -> pd.DataFrame:
    """All predictions, most-recent first. Optionally filter by variant."""
    with session_scope() as s:
        q = select(DT15Prediction).order_by(DT15Prediction.pred_date.desc()).limit(limit)
        if variant is not None:
            q = q.where(DT15Prediction.variant == variant)
        rows = list(s.scalars(q))
    if not rows:
        return pd.DataFrame()

    return pd.DataFrame([
        {
            "pred_date": r.pred_date,
            "variant": r.variant,
            "anchor_source": r.anchor_source,
            "anchor": r.today_open_used,
            "prior_close": r.prior_close,
            "vix_prior_close": r.vix_prior_close,
            "rm5": r.rm5,
            "range_vix": r.range_vix,
            "range_pred": r.range_pred,
            "pred_source": r.pred_source,
            "m_up_used": r.m_up_used,
            "m_dn_used": r.m_dn_used,
            "r1": r.r1,
            "r1_normalized": r.r1_normalized,
            "sigma_r1_used": r.sigma_r1_used,
            "sigma_r1_source": r.sigma_r1_source,
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


def backfill_from_history(days: int = 60, variant: str = "baseline") -> int:
    """Reconstruct predictions for the last N trading days using only prior data.

    Args:
        days: how many trading days back to seed.
        variant: 'baseline' or 'enh_b'.
    """
    from optionsminer.analytics.dt15 import TSPL_NLAGS, compute_levels

    # Enh-B needs 250 days of prior returns PER ROW for the TSPL kernel AND
    # 252 prior R1 values for the rolling σ_R1 estimator. For N target days
    # we therefore need ~(N + 502 + buffer) trading days available. Pull 3y
    # which gives ~750 trading days — plenty for any realistic backfill,
    # AND ensures the rolling σ kicks in (not the fallback) on every
    # backfilled row.
    if variant == "enh_b":
        es_period = "3y"
        vix_period = "3y"
    else:
        # Baseline only needs 7 prior days per row, but the slider can ask for
        # up to 250 trading days = ~365 calendar days of backfill, plus a small
        # cushion. Pull 2y to comfortably cover any realistic slider value.
        es_period = "2y"
        vix_period = "2y"
    es = fetch_daily_bars("ES=F", period=es_period)
    vix = fetch_daily_bars("^VIX", period=vix_period)

    if isinstance(es.columns, pd.MultiIndex):
        es.columns = es.columns.get_level_values(0)
    if isinstance(vix.columns, pd.MultiIndex):
        vix.columns = vix.columns.get_level_values(0)

    needed_history = TSPL_NLAGS + 7 if variant == "enh_b" else 7
    if len(es) < needed_history:
        return 0

    inserted = 0
    es_dates = list(es.index)
    target_dates = es_dates[-days:] if len(es_dates) > days else es_dates[needed_history:]

    for current in target_dates:
        es_window = es.loc[:current]
        vix_window = vix.loc[:current]
        if len(es_window) < needed_history:
            continue

        try:
            lv = compute_levels(es_window, vix_window, today_open_override=None, variant=variant)
        except ValueError:
            continue

        record_prediction(lv)
        inserted += 1

    settle_pending(variant=variant)
    return inserted
