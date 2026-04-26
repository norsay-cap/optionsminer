"""Realised volatility (Yang-Zhang, Parkinson, close-to-close) and VRP.

VRP = IV − RV. Persistent +ve on equity indices because of insurance demand.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

TRADING_DAYS = 252


@dataclass(frozen=True)
class VRP:
    rv_close: float | None
    rv_parkinson: float | None
    rv_yang_zhang: float | None
    iv30: float | None
    vrp: float | None  # iv30 - rv_yz (preferred), in vol points (e.g. 0.03 = 3 pts)


def rv_close_to_close(close: pd.Series, window: int = 21) -> float | None:
    if len(close) < window + 1:
        return None
    r = np.log(close / close.shift(1)).dropna().tail(window)
    if r.empty:
        return None
    return float(np.sqrt(TRADING_DAYS / window * (r**2).sum()))


def rv_parkinson(high: pd.Series, low: pd.Series, window: int = 21) -> float | None:
    if len(high) < window:
        return None
    r = np.log(high / low).tail(window)
    if r.empty:
        return None
    return float(np.sqrt(TRADING_DAYS / (4 * window * np.log(2)) * (r**2).sum()))


def rv_yang_zhang(
    open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series, window: int = 21
) -> float | None:
    """Yang-Zhang: drift-independent and gap-aware. The recommended estimator."""
    n = window
    if len(close) < n + 1:
        return None

    o, h, l, c = open_.tail(n + 1), high.tail(n + 1), low.tail(n + 1), close.tail(n + 1)

    # Overnight (close_{t-1} -> open_t) variance
    overnight = np.log(o / c.shift(1)).dropna()
    sigma_o2 = float((overnight**2).sum() / (n - 1)) if len(overnight) >= 2 else 0.0

    # Open-to-close variance
    oc = np.log(c / o).dropna()
    sigma_c2 = float((oc**2).sum() / (n - 1)) if len(oc) >= 2 else 0.0

    # Rogers-Satchell (drift-independent intraday range component)
    h_ = np.log(h / o)
    l_ = np.log(l / o)
    c_ = np.log(c / o)
    rs = (h_ * (h_ - c_) + l_ * (l_ - c_)).dropna()
    sigma_rs2 = float(rs.sum() / n) if len(rs) > 0 else 0.0

    k = 0.34 / (1.34 + (n + 1) / (n - 1))
    var_yz = sigma_o2 + k * sigma_c2 + (1 - k) * sigma_rs2
    return float(np.sqrt(var_yz * TRADING_DAYS))


def compute_vrp(bars: pd.DataFrame, atm_iv30: float | None) -> VRP:
    """Compute realised vols from `bars` (open, high, low, close) and the VRP."""
    if bars.empty:
        return VRP(None, None, None, atm_iv30, None)

    rv_cc = rv_close_to_close(bars["close"])
    rv_p = rv_parkinson(bars["high"], bars["low"])
    rv_yz = rv_yang_zhang(bars["open"], bars["high"], bars["low"], bars["close"])

    vrp = None
    if atm_iv30 is not None and rv_yz is not None:
        vrp = float(atm_iv30 - rv_yz)

    return VRP(
        rv_close=rv_cc,
        rv_parkinson=rv_p,
        rv_yang_zhang=rv_yz,
        iv30=atm_iv30,
        vrp=vrp,
    )
