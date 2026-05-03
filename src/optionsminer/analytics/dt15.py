"""DT15 daily range estimation for ES futures.

Predicts today's intraday range and projects four anchored levels (avg±, ext±)
around an anchor price (default: yfinance daily Open = 6 PM ET ETH session
start; can be overridden with the 9:30 AM ET RTH first-trade for a tighter
intraday read).

Methodology:
- range_vix  = K_BM * sigma_VIX * prior_close   (Brownian-motion expected absolute move)
- range_pred = max(RM5, 0.60 * range_vix)       (blend of recent realised + VIX-implied)
- avg±       = O_t  ±  0.5  * range_pred
- ext+       = O_t  +  0.5  * range_pred * 2.27
- ext-       = O_t  -  0.5  * range_pred * 2.97

Constants are locked from the original DT15 study and are not user-tunable.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

# Locked constants from the DT15 range estimation study
K_BM = float(np.sqrt(8.0 / np.pi))   # ~1.5957691216
VIX_BLEND_K = 0.60
M_UP = 2.27
M_DN = 2.97


@dataclass(frozen=True)
class DT15Levels:
    asof_date: date
    today_open_yf: float
    today_open_used: float
    anchor_source: str           # 'yfinance' or 'override'
    prior_close: float
    vix_prior_close: float
    rm5: float
    range_vix: float
    range_pred: float
    avg_plus: float
    avg_minus: float
    ext_plus: float
    ext_minus: float


def compute_levels(
    es_df: pd.DataFrame,
    vix_df: pd.DataFrame,
    today_open_override: float | None = None,
) -> DT15Levels:
    """Compute DT15 levels from already-fetched daily bars.

    Both inputs must be daily OHLCV indexed by date with at least 7 rows of
    overlapping history. The most-recent row is treated as 'today'.

    Args:
        es_df:  Daily bars for ES=F. Columns Open/High/Low/Close (case-sensitive).
        vix_df: Daily bars for ^VIX. Same shape.
        today_open_override: Optional anchor price; defaults to yfinance Open.

    Raises:
        ValueError: if there are fewer than 7 overlapping ES days.
    """
    es = es_df.copy()
    vix = vix_df.copy()

    if isinstance(es.columns, pd.MultiIndex):
        es.columns = es.columns.get_level_values(0)
    if isinstance(vix.columns, pd.MultiIndex):
        vix.columns = vix.columns.get_level_values(0)

    if len(es) < 7:
        raise ValueError(
            f"Only {len(es)} ES days available — need >=7 for RM5 + prior close"
        )

    last_idx = es.index[-1]
    today_open_yf = float(es["Open"].iloc[-1])
    prior_close = float(es["Close"].iloc[-2])
    last5_ranges = (es["High"] - es["Low"]).iloc[-6:-1].tolist()
    vix_prior_close = float(vix["Close"].reindex(es.index).ffill().iloc[-2])

    today_open = (
        float(today_open_override) if today_open_override is not None else today_open_yf
    )

    rm5 = float(np.mean(last5_ranges))
    sigma_vix = (vix_prior_close / 100.0) / np.sqrt(252.0)
    range_vix = K_BM * sigma_vix * prior_close
    range_pred = max(rm5, VIX_BLEND_K * range_vix)

    asof = last_idx.date() if hasattr(last_idx, "date") else date.today()

    return DT15Levels(
        asof_date=asof,
        today_open_yf=today_open_yf,
        today_open_used=today_open,
        anchor_source="override" if today_open_override is not None else "yfinance",
        prior_close=prior_close,
        vix_prior_close=vix_prior_close,
        rm5=rm5,
        range_vix=range_vix,
        range_pred=range_pred,
        avg_plus=today_open + 0.5 * range_pred,
        avg_minus=today_open - 0.5 * range_pred,
        ext_plus=today_open + 0.5 * range_pred * M_UP,
        ext_minus=today_open - 0.5 * range_pred * M_DN,
    )


def fetch_daily_bars(ticker: str, period: str = "30d") -> pd.DataFrame:
    """Pull last N calendar days of daily OHLCV from yfinance.

    Kept here (rather than reusing YahooProvider) because DT15 needs the raw
    yfinance shape (Open/High/Low/Close columns + DatetimeIndex), and the call
    is so cheap there's no benefit to going through the snapshot infrastructure.
    """
    import yfinance as yf

    df = yf.download(ticker, period=period, progress=False, auto_adjust=False)
    if df is None or df.empty:
        raise RuntimeError(f"yfinance returned no data for {ticker}")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df


def compute_live(today_open_override: float | None = None) -> DT15Levels:
    """Convenience: pull ES + VIX live from yfinance and compute the levels."""
    es = fetch_daily_bars("ES=F")
    vix = fetch_daily_bars("^VIX")
    return compute_levels(es, vix, today_open_override=today_open_override)
