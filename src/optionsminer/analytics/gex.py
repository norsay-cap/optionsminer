"""Gamma Exposure (GEX) — dealer-hedging-flow indicator.

Standard SqueezeMetrics-style sign convention: dealers are assumed long calls
and short puts (call gamma adds, put gamma subtracts to total). This is the
common-case approximation; it breaks for 0DTE-heavy retail flow but remains
the practitioner default for daily/weekly horizons.

`GEX_strike = sign · gamma · OI · 100 · S² · 0.01`

Units: dollars of dealer delta to hedge per 1% spot move.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from optionsminer.analytics import greeks as gk

CONTRACT_MULT = 100.0  # SPY/SPX equity-style contracts


@dataclass(frozen=True)
class GexProfile:
    spot: float
    total_gex: float
    by_strike: pd.DataFrame   # columns: strike, gex (sum across calls+puts)
    zero_gamma: float | None  # spot level where total_gex(S)=0
    flip_curve: pd.DataFrame  # columns: spot_grid, total_gex
    call_wall: float | None   # strike with max +gex (resistance)
    put_wall: float | None    # strike with min -gex (support)


def per_strike_gex(
    chain: pd.DataFrame,
    spot: float,
    *,
    contract_mult: float = CONTRACT_MULT,
) -> pd.DataFrame:
    """One row per (strike, cp) with $ gex.

    Filters: requires non-null gamma and OI > 0.
    """
    df = chain.copy()
    df = df[df["gamma"].notna() & df["open_interest"].fillna(0).gt(0)]
    sign = np.where(df["cp"].str.upper() == "C", 1.0, -1.0)
    df["gex_dollars"] = (
        sign * df["gamma"] * df["open_interest"] * contract_mult * (spot**2) * 0.01
    )
    return df[["expiry", "strike", "cp", "gex_dollars", "gamma", "open_interest", "dte"]]


def aggregate_by_strike(per_strike: pd.DataFrame) -> pd.DataFrame:
    g = per_strike.groupby("strike", as_index=False)["gex_dollars"].sum()
    return g.sort_values("strike").reset_index(drop=True)


def total_gex_dollars(per_strike: pd.DataFrame) -> float:
    return float(per_strike["gex_dollars"].sum())


def find_zero_gamma(
    chain: pd.DataFrame,
    spot: float,
    *,
    r: float,
    q: float,
    pct_range: float = 0.10,
    n_steps: int = 81,
) -> tuple[float | None, pd.DataFrame]:
    """Sweep spot ±pct_range, recompute gamma per row, find sign-change point.

    Returns (zero_gamma_estimate, curve_df). If no sign change in the swept
    range, zero_gamma is None and the user should expand pct_range.

    Uses the snapshot's IVs as locked-in (the standard practitioner shortcut
    — re-solving IV across the surface for every spot is unreasonably slow
    and adds little for short-horizon what-ifs).
    """
    df = chain[chain["iv"].notna() & chain["open_interest"].fillna(0).gt(0)].copy()
    if df.empty:
        return None, pd.DataFrame(columns=["spot_grid", "total_gex"])

    K = df["strike"].to_numpy(float)
    T = df["dte"].to_numpy(float) / 365.0
    sig = df["iv"].to_numpy(float)
    oi = df["open_interest"].to_numpy(float)
    sign = np.where(df["cp"].str.upper().to_numpy() == "C", 1.0, -1.0)

    grid = np.linspace(spot * (1 - pct_range), spot * (1 + pct_range), n_steps)
    totals = np.empty_like(grid)
    for i, S in enumerate(grid):
        with np.errstate(divide="ignore", invalid="ignore"):
            g = gk.gamma(S, K, T, r, q, sig)
        g = np.where(np.isfinite(g), g, 0.0)
        totals[i] = float((sign * g * oi * CONTRACT_MULT * (S**2) * 0.01).sum())

    curve = pd.DataFrame({"spot_grid": grid, "total_gex": totals})

    # Zero-cross detection: find sign change, then linear interp
    zero = None
    for i in range(1, len(totals)):
        if totals[i - 1] == 0:
            zero = float(grid[i - 1])
            break
        if totals[i - 1] * totals[i] < 0:
            x0, x1, y0, y1 = grid[i - 1], grid[i], totals[i - 1], totals[i]
            zero = float(x0 - y0 * (x1 - x0) / (y1 - y0))
            break
    return zero, curve


def find_walls(
    by_strike: pd.DataFrame,
    spot: float,
    *,
    band_pct: float = 0.10,
) -> tuple[float | None, float | None]:
    """Largest +GEX strike above spot (call wall) and largest -GEX below (put wall).

    Restricted to strikes within band_pct of spot — far-OTM gex is dead weight.
    """
    if by_strike.empty:
        return None, None
    band = by_strike[
        (by_strike["strike"].between(spot * (1 - band_pct), spot * (1 + band_pct)))
    ]
    if band.empty:
        return None, None

    above = band[band["strike"] > spot]
    below = band[band["strike"] < spot]
    call_wall = (
        float(above.loc[above["gex_dollars"].idxmax(), "strike"])
        if not above.empty and above["gex_dollars"].max() > 0
        else None
    )
    put_wall = (
        float(below.loc[below["gex_dollars"].idxmin(), "strike"])
        if not below.empty and below["gex_dollars"].min() < 0
        else None
    )
    return call_wall, put_wall


def compute_profile(
    chain: pd.DataFrame,
    spot: float,
    *,
    r: float,
    q: float,
    max_dte: int | None = 60,
    exclude_0dte: bool = True,
) -> GexProfile:
    """Convenience: full GEX profile for the dashboard.

    By default we exclude 0DTE (overstates intraday gex with stale yesterday-OI)
    and cap at 60 DTE (longer-dated gex matters less for daily flows).
    """
    df = chain.copy()
    if max_dte is not None:
        df = df[df["dte"] <= max_dte]
    if exclude_0dte:
        df = df[df["dte"] > 0]

    per = per_strike_gex(df, spot)
    by = aggregate_by_strike(per)
    total = total_gex_dollars(per)
    zero, curve = find_zero_gamma(df, spot, r=r, q=q)
    call_wall, put_wall = find_walls(by, spot)
    return GexProfile(
        spot=spot,
        total_gex=total,
        by_strike=by,
        zero_gamma=zero,
        flip_curve=curve,
        call_wall=call_wall,
        put_wall=put_wall,
    )
