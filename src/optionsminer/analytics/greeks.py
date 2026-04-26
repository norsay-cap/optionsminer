"""Black-Scholes greeks + implied vol solver.

All inputs/outputs are vectorised (NumPy arrays) where possible — the option
chain has thousands of strikes per snapshot and per-row Python loops would be
the bottleneck.

Conventions:
    S  spot
    K  strike
    T  time to expiry in years (calendar days / 365)
    r  risk-free rate (annualised, decimal)
    q  continuous dividend yield (annualised, decimal)
    sigma  implied vol (annualised, decimal — i.e. 0.18 for 18%)
    cp  'C' or 'P' (case-insensitive)

Vega is returned per 1.00 vol move (i.e. multiply by 0.01 for "per vol point").
Theta is per year — divide by 365 for per-calendar-day.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray
from scipy.stats import norm

ArrayF = NDArray[np.float64]


def _to_array(x) -> ArrayF:  # noqa: ANN001
    return np.asarray(x, dtype=np.float64)


def _cp_sign(cp) -> ArrayF:  # noqa: ANN001
    cp_arr = np.asarray(cp)
    return np.where(np.char.upper(cp_arr.astype(str)) == "C", 1.0, -1.0)


def d1_d2(S: ArrayF, K: ArrayF, T: ArrayF, r: float, q: float, sigma: ArrayF) -> tuple[ArrayF, ArrayF]:
    S, K, T, sigma = _to_array(S), _to_array(K), _to_array(T), _to_array(sigma)
    sqrt_t = np.sqrt(np.maximum(T, 1e-12))
    sig = np.maximum(sigma, 1e-8)
    d1 = (np.log(S / K) + (r - q + 0.5 * sig**2) * T) / (sig * sqrt_t)
    d2 = d1 - sig * sqrt_t
    return d1, d2


def bs_price(S, K, T, r, q, sigma, cp) -> ArrayF:  # noqa: ANN001
    """Black-Scholes price for European options on a dividend-paying spot."""
    d1, d2 = d1_d2(S, K, T, r, q, sigma)
    sign = _cp_sign(cp)
    disc_q = np.exp(-q * T)
    disc_r = np.exp(-r * T)
    return sign * (S * disc_q * norm.cdf(sign * d1) - K * disc_r * norm.cdf(sign * d2))


def delta(S, K, T, r, q, sigma, cp) -> ArrayF:  # noqa: ANN001
    d1, _ = d1_d2(S, K, T, r, q, sigma)
    sign = _cp_sign(cp)
    return sign * np.exp(-q * T) * norm.cdf(sign * d1)


def gamma(S, K, T, r, q, sigma) -> ArrayF:  # noqa: ANN001
    d1, _ = d1_d2(S, K, T, r, q, sigma)
    sqrt_t = np.sqrt(np.maximum(T, 1e-12))
    return np.exp(-q * T) * norm.pdf(d1) / (S * sigma * sqrt_t)


def vega(S, K, T, r, q, sigma) -> ArrayF:  # noqa: ANN001
    """Per 1.00 vol move (i.e. raw — divide by 100 for per vol-point)."""
    d1, _ = d1_d2(S, K, T, r, q, sigma)
    return S * np.exp(-q * T) * norm.pdf(d1) * np.sqrt(np.maximum(T, 1e-12))


def theta(S, K, T, r, q, sigma, cp) -> ArrayF:  # noqa: ANN001
    """Per year — divide by 365 for per-calendar-day."""
    d1, d2 = d1_d2(S, K, T, r, q, sigma)
    sign = _cp_sign(cp)
    sqrt_t = np.sqrt(np.maximum(T, 1e-12))
    term1 = -S * np.exp(-q * T) * norm.pdf(d1) * sigma / (2.0 * sqrt_t)
    term2 = -sign * r * K * np.exp(-r * T) * norm.cdf(sign * d2)
    term3 = sign * q * S * np.exp(-q * T) * norm.cdf(sign * d1)
    return term1 + term2 + term3


def charm(S, K, T, r, q, sigma, cp) -> ArrayF:  # noqa: ANN001
    """∂Δ/∂t — per year. Drives EOD delta-hedging flows."""
    d1, d2 = d1_d2(S, K, T, r, q, sigma)
    sign = _cp_sign(cp)
    sqrt_t = np.sqrt(np.maximum(T, 1e-12))
    factor = (2.0 * (r - q) * T - d2 * sigma * sqrt_t) / (2.0 * T * sigma * sqrt_t)
    base = -np.exp(-q * T) * norm.pdf(d1) * factor
    drift = sign * q * np.exp(-q * T) * norm.cdf(sign * d1)
    return base + drift


def vanna(S, K, T, r, q, sigma) -> ArrayF:  # noqa: ANN001
    """∂Δ/∂σ = ∂Vega/∂S. Drives vol-crush rallies."""
    d1, d2 = d1_d2(S, K, T, r, q, sigma)
    return -np.exp(-q * T) * norm.pdf(d1) * d2 / sigma


def implied_vol_brent(
    target_price: float,
    S: float,
    K: float,
    T: float,
    r: float,
    q: float,
    cp: str,
    *,
    lo: float = 1e-4,
    hi: float = 5.0,
    tol: float = 1e-6,
    max_iter: int = 80,
) -> float | None:
    """Brent-style bisection IV solver. Returns None on no-arbitrage failure.

    Avoids scipy.optimize import overhead per-strike — this is the inner-loop
    function for chain IV recompute.
    """
    if not np.isfinite(target_price) or target_price <= 0 or T <= 0:
        return None

    intrinsic = max((S - K) if cp.upper() == "C" else (K - S), 0.0) * np.exp(-r * T)
    if target_price < intrinsic - 1e-6:
        return None

    def f(sig: float) -> float:
        return float(bs_price(S, K, T, r, q, sig, cp)) - target_price

    f_lo, f_hi = f(lo), f(hi)
    if f_lo * f_hi > 0:
        # Expand once before giving up — extreme IVs do exist on illiquid wings
        hi2 = 10.0
        f_hi2 = f(hi2)
        if f_lo * f_hi2 > 0:
            return None
        hi, f_hi = hi2, f_hi2

    a, b, fa, fb = lo, hi, f_lo, f_hi
    for _ in range(max_iter):
        m = 0.5 * (a + b)
        fm = f(m)
        if abs(fm) < tol or (b - a) < tol:
            return float(m)
        if fa * fm < 0:
            b, fb = m, fm
        else:
            a, fa = m, fm
    return float(0.5 * (a + b))
