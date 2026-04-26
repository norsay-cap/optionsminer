"""Max pain — the strike that minimises total writer payout at expiry.

Mostly folklore on its own (per the research brief), but a useful confluence
indicator when it lines up with high-OI walls or zero-gamma flip.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def max_pain(chain: pd.DataFrame, expiry_dte: int | None = None) -> tuple[float | None, pd.DataFrame]:
    """Return (max_pain_strike, payout_curve) for one expiry.

    If `expiry_dte` is None we use the soonest non-zero DTE expiry.
    """
    df = chain.copy()
    df = df[df["open_interest"].fillna(0) > 0]
    if df.empty:
        return None, pd.DataFrame(columns=["strike", "payout"])

    if expiry_dte is None:
        nonzero = df[df["dte"] > 0]
        if nonzero.empty:
            return None, pd.DataFrame(columns=["strike", "payout"])
        expiry_dte = int(nonzero["dte"].min())

    sub = df[df["dte"] == expiry_dte]
    if sub.empty:
        return None, pd.DataFrame(columns=["strike", "payout"])

    strikes = np.sort(sub["strike"].unique())
    calls = sub[sub["cp"] == "C"][["strike", "open_interest"]].rename(
        columns={"open_interest": "oi_c"}
    )
    puts = sub[sub["cp"] == "P"][["strike", "open_interest"]].rename(
        columns={"open_interest": "oi_p"}
    )

    payouts = []
    for K in strikes:
        # Calls: payout to holder = sum_j OI_call_j · max(K - K_j, 0) is wrong direction
        # Writer pays: sum_j OI_call_j · max(spot - K_j, 0). At candidate spot K:
        call_pay = (np.maximum(K - calls["strike"].to_numpy(float), 0.0) * calls["oi_c"].to_numpy(float)).sum()
        put_pay = (np.maximum(puts["strike"].to_numpy(float) - K, 0.0) * puts["oi_p"].to_numpy(float)).sum()
        payouts.append(call_pay + put_pay)

    curve = pd.DataFrame({"strike": strikes, "payout": payouts})
    mp = float(curve.loc[curve["payout"].idxmin(), "strike"])
    return mp, curve
