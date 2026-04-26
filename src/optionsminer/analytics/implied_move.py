"""Expected-move calculations from straddle pricing and ATM IV."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.interpolate import PchipInterpolator


@dataclass(frozen=True)
class ImpliedMove:
    expiry_dte: int
    spot: float
    em_dollars_straddle: float | None  # 0.85 · straddle proxy
    em_pct_straddle: float | None
    em_pct_iv: float | None            # ATM IV · sqrt(T)
    upper: float | None
    lower: float | None


def _interp(strikes: np.ndarray, vals: np.ndarray) -> PchipInterpolator | None:
    mask = np.isfinite(strikes) & np.isfinite(vals) & (vals > 0)
    s, v = strikes[mask], vals[mask]
    if len(s) < 4:
        return None
    order = np.argsort(s)
    s, v = s[order], v[order]
    keep = np.concatenate(([True], np.diff(s) > 0))
    return PchipInterpolator(s[keep], v[keep], extrapolate=False)


def implied_move(chain: pd.DataFrame, spot: float, target_dte: int = 7) -> ImpliedMove | None:
    """1σ expected move to expiry. Defaults to weekly (7D)."""
    df = chain.copy()
    if df.empty:
        return None
    expiries = df.groupby("dte")["expiry"].first().reset_index()
    if expiries.empty:
        return None
    chosen = int(expiries.iloc[(expiries["dte"] - target_dte).abs().argmin()]["dte"])

    sub = df[df["dte"] == chosen]
    calls = sub[sub["cp"] == "C"]
    puts = sub[sub["cp"] == "P"]

    em_dollars = em_pct_straddle = None
    fc_mid = _interp(calls["strike"].to_numpy(float), calls["mid"].to_numpy(float))
    fp_mid = _interp(puts["strike"].to_numpy(float), puts["mid"].to_numpy(float))
    if fc_mid is not None and fp_mid is not None:
        try:
            c_at = float(fc_mid(spot))
            p_at = float(fp_mid(spot))
            if np.isfinite(c_at) and np.isfinite(p_at):
                straddle = c_at + p_at
                em_dollars = 0.85 * straddle
                em_pct_straddle = em_dollars / spot
        except ValueError:
            pass

    em_pct_iv = None
    fc_iv = _interp(calls["strike"].to_numpy(float), calls["iv"].to_numpy(float))
    fp_iv = _interp(puts["strike"].to_numpy(float), puts["iv"].to_numpy(float))
    atm_ivs = []
    for f in (fc_iv, fp_iv):
        if f is None:
            continue
        try:
            v = float(f(spot))
            if np.isfinite(v):
                atm_ivs.append(v)
        except ValueError:
            continue
    if atm_ivs:
        atm = float(np.mean(atm_ivs))
        em_pct_iv = atm * np.sqrt(max(chosen, 1) / 365.0)

    upper = lower = None
    em_pct = em_pct_straddle if em_pct_straddle is not None else em_pct_iv
    if em_pct is not None:
        upper = spot * (1 + em_pct)
        lower = spot * (1 - em_pct)

    return ImpliedMove(
        expiry_dte=chosen,
        spot=spot,
        em_dollars_straddle=em_dollars,
        em_pct_straddle=em_pct_straddle,
        em_pct_iv=em_pct_iv,
        upper=upper,
        lower=lower,
    )
