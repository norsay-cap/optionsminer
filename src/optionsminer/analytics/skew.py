"""IV skew and term-structure metrics.

All inputs come from the loader's chain DataFrame (with the synthesised
`iv` column = iv_recalc when available else iv_yahoo).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.interpolate import PchipInterpolator


@dataclass(frozen=True)
class SkewSnapshot:
    expiry_dte: int
    atm_iv: float | None
    iv_25d_call: float | None
    iv_25d_put: float | None
    rr_25d: float | None       # IV(25Δ put) - IV(25Δ call); + = put skew
    skew_90_110: float | None  # IV(K=0.9·S) - IV(K=1.1·S)
    iv_curve: pd.DataFrame     # strike -> iv (sorted)


def _interp_iv_by_strike(strikes: np.ndarray, ivs: np.ndarray) -> PchipInterpolator | None:
    """Monotonic cubic interp of IV(strike). Returns None if too few points."""
    mask = np.isfinite(strikes) & np.isfinite(ivs) & (ivs > 0)
    s, i = strikes[mask], ivs[mask]
    if len(s) < 4:
        return None
    order = np.argsort(s)
    s, i = s[order], i[order]
    # Drop duplicate strikes — PchipInterpolator requires strictly increasing
    keep = np.concatenate(([True], np.diff(s) > 0))
    return PchipInterpolator(s[keep], i[keep], extrapolate=False)


def _interp_iv_by_delta(deltas: np.ndarray, ivs: np.ndarray) -> PchipInterpolator | None:
    mask = np.isfinite(deltas) & np.isfinite(ivs) & (ivs > 0)
    d, i = deltas[mask], ivs[mask]
    if len(d) < 4:
        return None
    order = np.argsort(d)
    d, i = d[order], i[order]
    keep = np.concatenate(([True], np.diff(d) > 0))
    return PchipInterpolator(d[keep], i[keep], extrapolate=False)


def skew_for_expiry(chain: pd.DataFrame, spot: float, target_dte: int) -> SkewSnapshot | None:
    """Pick the expiry with DTE closest to target_dte and compute skew metrics."""
    df = chain.dropna(subset=["iv"]).copy()
    if df.empty:
        return None

    expiries = df.groupby("dte")["expiry"].first().reset_index()
    if expiries.empty:
        return None
    chosen = int(expiries.iloc[(expiries["dte"] - target_dte).abs().argmin()]["dte"])

    sub = df[df["dte"] == chosen].copy()
    if sub.empty:
        return None

    # ATM IV: average call+put interpolated to spot
    atm = []
    for cp in ("C", "P"):
        leg = sub[sub["cp"] == cp]
        f = _interp_iv_by_strike(leg["strike"].to_numpy(float), leg["iv"].to_numpy(float))
        if f is not None:
            try:
                v = float(f(spot))
                if np.isfinite(v):
                    atm.append(v)
            except ValueError:
                pass
    atm_iv = float(np.mean(atm)) if atm else None

    # 25Δ risk reversal (use puts at delta=-0.25, calls at delta=0.25)
    rr_25d = iv25c = iv25p = None
    calls = sub[sub["cp"] == "C"]
    puts = sub[sub["cp"] == "P"]
    fc = _interp_iv_by_delta(calls["delta"].to_numpy(float), calls["iv"].to_numpy(float))
    fp = _interp_iv_by_delta(puts["delta"].to_numpy(float), puts["iv"].to_numpy(float))
    try:
        if fc is not None:
            iv25c = float(fc(0.25))
        if fp is not None:
            iv25p = float(fp(-0.25))
        if iv25c is not None and iv25p is not None and np.isfinite(iv25c) and np.isfinite(iv25p):
            rr_25d = iv25p - iv25c
    except ValueError:
        pass

    # 90-110 moneyness skew (call-side reference at 110%, put-side at 90%)
    skew_90_110 = None
    f_all = _interp_iv_by_strike(sub["strike"].to_numpy(float), sub["iv"].to_numpy(float))
    if f_all is not None:
        try:
            iv90 = float(f_all(spot * 0.90))
            iv110 = float(f_all(spot * 1.10))
            if np.isfinite(iv90) and np.isfinite(iv110):
                skew_90_110 = iv90 - iv110
        except ValueError:
            pass

    curve = sub.groupby("strike", as_index=False)["iv"].mean().sort_values("strike")

    return SkewSnapshot(
        expiry_dte=chosen,
        atm_iv=atm_iv,
        iv_25d_call=iv25c if iv25c is not None and np.isfinite(iv25c) else None,
        iv_25d_put=iv25p if iv25p is not None and np.isfinite(iv25p) else None,
        rr_25d=rr_25d,
        skew_90_110=skew_90_110,
        iv_curve=curve,
    )


def term_structure(chain: pd.DataFrame, spot: float) -> pd.DataFrame:
    """One row per expiry with ATM IV — the term-structure curve."""
    df = chain.dropna(subset=["iv"]).copy()
    out = []
    for dte, group in df.groupby("dte"):
        atm_vals = []
        for cp in ("C", "P"):
            leg = group[group["cp"] == cp]
            f = _interp_iv_by_strike(leg["strike"].to_numpy(float), leg["iv"].to_numpy(float))
            if f is None:
                continue
            try:
                v = float(f(spot))
                if np.isfinite(v):
                    atm_vals.append(v)
            except ValueError:
                pass
        if atm_vals:
            out.append({"dte": int(dte), "atm_iv": float(np.mean(atm_vals))})
    return pd.DataFrame(out).sort_values("dte").reset_index(drop=True)


def term_slope(term: pd.DataFrame, short_dte: int = 7, long_dte: int = 30) -> float | None:
    """IV(long) / IV(short) - 1. Negative = backwardation (stress)."""
    if term.empty:
        return None
    short = term.iloc[(term["dte"] - short_dte).abs().argmin()]["atm_iv"]
    long_ = term.iloc[(term["dte"] - long_dte).abs().argmin()]["atm_iv"]
    if not (short > 0 and long_ > 0):
        return None
    return float(long_ / short - 1.0)
