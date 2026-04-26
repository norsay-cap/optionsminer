"""Open-interest walls — gamma-weighted strike concentration as S/R levels."""

from __future__ import annotations

import pandas as pd


def gamma_oi_walls(
    chain: pd.DataFrame,
    spot: float,
    *,
    band_pct: float = 0.10,
    top_n: int = 5,
) -> pd.DataFrame:
    """Top-N strikes ranked by |gamma · OI|, restricted to ±band_pct of spot.

    Returns columns: strike, side ('above'|'below'), call_oi, put_oi, gamma_oi.
    """
    df = chain.copy()
    df = df[
        df["gamma"].notna()
        & df["open_interest"].fillna(0).gt(0)
        & df["strike"].between(spot * (1 - band_pct), spot * (1 + band_pct))
    ]
    if df.empty:
        return pd.DataFrame(columns=["strike", "side", "call_oi", "put_oi", "gamma_oi"])

    df["gamma_oi"] = df["gamma"] * df["open_interest"]
    pivot = (
        df.pivot_table(
            index="strike",
            columns="cp",
            values=["open_interest", "gamma_oi"],
            aggfunc="sum",
            fill_value=0.0,
        )
    )
    out = pd.DataFrame(
        {
            "strike": pivot.index,
            "call_oi": pivot.get(("open_interest", "C"), 0.0).values
                if ("open_interest", "C") in pivot.columns else 0.0,
            "put_oi": pivot.get(("open_interest", "P"), 0.0).values
                if ("open_interest", "P") in pivot.columns else 0.0,
            "gamma_oi": (
                pivot.get(("gamma_oi", "C"), 0.0).values
                if ("gamma_oi", "C") in pivot.columns else 0.0
            )
            + (
                pivot.get(("gamma_oi", "P"), 0.0).values
                if ("gamma_oi", "P") in pivot.columns else 0.0
            ),
        }
    )
    out["side"] = out["strike"].apply(lambda k: "above" if k > spot else "below")
    return out.nlargest(top_n, "gamma_oi").reset_index(drop=True)
