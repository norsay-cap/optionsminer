"""DT15 daily range estimation for ES futures.

Two methodologies are supported and selectable per call via `variant`:

- **'baseline'**: locked static M multipliers (M_up=2.27, M_dn=2.97). Original
  DT15 specification.
- **'enh_b'**: Enhancement B — tightened static base (M_up=1.87, M_dn=2.57)
  plus an R1-driven dynamic widening term derived from a TSPL-weighted sum
  of the past 250 daily log returns. Calibrated 2018–2022 IS, validated
  2023–2025 OOS for better breach-rate calibration.

Both methodologies share the same size predictor:
- range_vix = K_BM · σ_VIX · prior_close
- range_pred = max(RM5, 0.60 · range_vix)
- avg± = O_t ± 0.5 · range_pred

They differ only in how the M_up / M_dn multipliers that produce ext± are
computed. Enhancement B's multipliers are time-varying:

    M_up^(t) = 1.87 · (1 + 1.59 · max(0,  R1/σ_R1))
    M_dn^(t) = 2.57 · (1 + 1.93 · max(0, -R1/σ_R1))

R1 is sentiment in the path: positive R1 means recent up-trend → wider
upside extension to absorb continuation; negative R1 → wider downside.
Constants are locked from the study and not user-tunable.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

# Locked constants — do NOT tune
K_BM = float(np.sqrt(8.0 / np.pi))   # ~1.5957691216
VIX_BLEND_K = 0.60

# Baseline static M (2018–2022 IS calibration)
M_UP_BASELINE = 2.27
M_DN_BASELINE = 2.97

# Enhancement B: tightened static base + R1-dynamic widening
M_UP_TIGHT = 1.87
M_DN_TIGHT = 2.57
LAM_UP = 1.59
LAM_DN = 1.93

# Guyon-Lekeufack TSPL kernel parameters (VIX-style, Table 3)
TSPL_ALPHA = 1.06
TSPL_DELTA = 0.020
TSPL_NLAGS = 250            # ~1y of past daily returns
SIGMA_R1 = 0.00142          # IS-calibrated std of R1, stable across regimes

# Backwards compat — older code paths import M_UP / M_DN as the baseline values
M_UP = M_UP_BASELINE
M_DN = M_DN_BASELINE

VARIANTS: tuple[str, ...] = ("baseline", "enh_b")


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

    # Methodology + dynamic multiplier values
    variant: str                 # 'baseline' or 'enh_b'
    m_up_used: float
    m_dn_used: float
    r1: float | None             # None for baseline
    r1_normalized: float | None  # None for baseline


def _tspl_weights(alpha: float, delta: float, n_lags: int, dt: float = 1.0 / 252) -> np.ndarray:
    """TSPL kernel weights, normalised so that w·1·dt = 1 (proper density)."""
    z = (delta ** (1 - alpha)) / (alpha - 1)
    taus = np.arange(n_lags) * dt
    w = ((taus + delta) ** (-alpha)) / z
    return (w / (w.sum() * dt)) * dt


def _required_es_days(variant: str) -> int:
    """Minimum ES daily bars needed for a given variant."""
    if variant == "enh_b":
        return TSPL_NLAGS + 7
    return 7


def compute_levels(
    es_df: pd.DataFrame,
    vix_df: pd.DataFrame,
    today_open_override: float | None = None,
    *,
    variant: str = "enh_b",
) -> DT15Levels:
    """Compute DT15 levels from already-fetched daily bars.

    Args:
        es_df, vix_df: daily OHLCV indexed by date (Open/High/Low/Close columns).
        today_open_override: optional anchor price; defaults to yfinance Open.
        variant: 'baseline' or 'enh_b'.

    Raises:
        ValueError: if not enough history for the chosen variant.
    """
    if variant not in VARIANTS:
        raise ValueError(f"Unknown variant {variant!r}; expected one of {VARIANTS}")

    es = es_df.copy()
    vix = vix_df.copy()
    if isinstance(es.columns, pd.MultiIndex):
        es.columns = es.columns.get_level_values(0)
    if isinstance(vix.columns, pd.MultiIndex):
        vix.columns = vix.columns.get_level_values(0)

    needed = _required_es_days(variant)
    if len(es) < needed:
        raise ValueError(
            f"Only {len(es)} ES days available — variant '{variant}' needs >= {needed}"
        )

    last_idx = es.index[-1]
    today_open_yf = float(es["Open"].iloc[-1])
    prior_close = float(es["Close"].iloc[-2])
    last5_ranges = (es["High"] - es["Low"]).iloc[-6:-1].tolist()
    vix_prior_close = float(vix["Close"].reindex(es.index).ffill().iloc[-2])

    today_open = float(today_open_override) if today_open_override is not None else today_open_yf

    # Size predictor (variant-independent)
    rm5 = float(np.mean(last5_ranges))
    sigma_vix = (vix_prior_close / 100.0) / np.sqrt(252.0)
    range_vix = K_BM * sigma_vix * prior_close
    range_pred = max(rm5, VIX_BLEND_K * range_vix)
    half = 0.5 * range_pred

    # M multipliers
    r1: float | None = None
    r1_norm: float | None = None
    if variant == "baseline":
        m_up = M_UP_BASELINE
        m_dn = M_DN_BASELINE
    else:  # enh_b
        log_rets = np.log(es["Close"] / es["Close"].shift(1)).dropna().values
        # past_rets EXCLUDES today's return → no look-ahead
        past_rets = log_rets[-TSPL_NLAGS - 1:-1]
        if len(past_rets) < TSPL_NLAGS:
            raise ValueError(
                f"Not enough past returns for TSPL kernel: {len(past_rets)} / {TSPL_NLAGS}"
            )
        w1 = _tspl_weights(TSPL_ALPHA, TSPL_DELTA, TSPL_NLAGS)[::-1]
        r1 = float(np.dot(w1, past_rets))
        r1_norm = r1 / SIGMA_R1
        m_up = M_UP_TIGHT * (1.0 + LAM_UP * max(0.0, r1_norm))
        m_dn = M_DN_TIGHT * (1.0 + LAM_DN * max(0.0, -r1_norm))

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
        avg_plus=today_open + half,
        avg_minus=today_open - half,
        ext_plus=today_open + half * m_up,
        ext_minus=today_open - half * m_dn,
        variant=variant,
        m_up_used=m_up,
        m_dn_used=m_dn,
        r1=r1,
        r1_normalized=r1_norm,
    )


def fetch_daily_bars(ticker: str, period: str = "30d") -> pd.DataFrame:
    """Pull last N calendar days of daily OHLCV from yfinance."""
    import yfinance as yf

    df = yf.download(ticker, period=period, progress=False, auto_adjust=False)
    if df is None or df.empty:
        raise RuntimeError(f"yfinance returned no data for {ticker}")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df


def compute_live(
    today_open_override: float | None = None,
    *,
    variant: str = "enh_b",
) -> DT15Levels:
    """Pull ES + VIX live and compute. Period auto-sized for the variant."""
    es_period = "2y" if variant == "enh_b" else "30d"
    es = fetch_daily_bars("ES=F", period=es_period)
    vix = fetch_daily_bars("^VIX", period="30d")
    return compute_levels(es, vix, today_open_override=today_open_override, variant=variant)
