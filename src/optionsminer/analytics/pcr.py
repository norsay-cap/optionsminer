"""Put/Call ratios — volume-based and OI-based, with DTE filter to suppress 0DTE noise."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class PCR:
    pcr_volume: float | None
    pcr_oi: float | None
    n_calls_vol: int
    n_puts_vol: int
    n_calls_oi: int
    n_puts_oi: int


def put_call_ratio(chain: pd.DataFrame, *, min_dte: int = 7) -> PCR:
    """Per the brief: filter to DTE >= 7 to remove 0DTE retail-gambling distortion."""
    df = chain[chain["dte"] >= min_dte].copy()
    calls = df[df["cp"] == "C"]
    puts = df[df["cp"] == "P"]

    cv = float(calls["volume"].fillna(0).sum())
    pv = float(puts["volume"].fillna(0).sum())
    co = float(calls["open_interest"].fillna(0).sum())
    po = float(puts["open_interest"].fillna(0).sum())

    return PCR(
        pcr_volume=(pv / cv) if cv > 0 else None,
        pcr_oi=(po / co) if co > 0 else None,
        n_calls_vol=int(cv),
        n_puts_vol=int(pv),
        n_calls_oi=int(co),
        n_puts_oi=int(po),
    )
