"""Unusual options activity, within yfinance EOD-snapshot constraints.

What the brief said is feasible without intraday tape:
  - vol/OI ratio
  - vol vs avg(20D) per contract (requires history; we approximate per-snapshot
    using same-strike+expiry rows from prior snapshots if available, else just
    flag absolute volume vs OI)
  - notional dollar size

What is NOT feasible: sweep detection, block prints, aggressor classification.
"""

from __future__ import annotations

import pandas as pd


def unusual_today(
    chain: pd.DataFrame,
    *,
    min_volume: int = 500,
    min_vol_oi: float = 0.5,
    min_dte: int = 7,
    max_dte: int = 60,
    min_moneyness_pct: float = 0.02,
    spot: float | None = None,
) -> pd.DataFrame:
    """Filter the chain to candidate UOA rows (single-snapshot heuristics).

    Returns rows ranked by `vol_oi_ratio · sqrt(volume)` so big-volume,
    high-vol/OI hits sort to the top.
    """
    df = chain.copy()
    df = df.dropna(subset=["volume", "open_interest"])
    df["volume"] = df["volume"].astype(float)
    df["open_interest"] = df["open_interest"].astype(float)

    df = df[df["dte"].between(min_dte, max_dte)]
    df = df[df["volume"] >= min_volume]
    df = df[df["open_interest"] > 0]
    df["vol_oi_ratio"] = df["volume"] / df["open_interest"]
    df = df[df["vol_oi_ratio"] >= min_vol_oi]

    if spot is not None:
        df["moneyness"] = df["strike"] / spot - 1.0
        df = df[df["moneyness"].abs() >= min_moneyness_pct]

    df["notional_dollars"] = df["mid"].fillna(df["last"].fillna(0)) * df["volume"] * 100.0
    df = df[df["notional_dollars"] >= 250_000]

    df["score"] = df["vol_oi_ratio"] * (df["volume"] ** 0.5)
    cols = ["expiry", "strike", "cp", "dte", "bid", "ask", "mid", "volume",
            "open_interest", "vol_oi_ratio", "notional_dollars", "iv", "score"]
    cols = [c for c in cols if c in df.columns]
    return df.sort_values("score", ascending=False)[cols].reset_index(drop=True)
