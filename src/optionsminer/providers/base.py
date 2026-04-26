"""Provider abstraction so we can swap yfinance for Schwab / Polygon later.

A provider returns plain pandas DataFrames in a documented schema. The ingest
pipeline then handles greeks, IV recompute, and DB persistence — providers do
not touch the DB.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime

import pandas as pd


@dataclass(frozen=True)
class ChainSnapshot:
    """Raw chain pull from a provider — not yet persisted, no greeks computed."""

    ticker: str
    snapshot_ts: datetime          # UTC
    spot: float

    # quotes columns: expiry (date), strike (float), cp ('C'|'P'),
    # bid, ask, last, mid, volume, open_interest, iv_provider, last_trade_ts
    quotes: pd.DataFrame


class DataProvider(ABC):
    """Provider interface. Implementations must NOT raise on per-strike
    bad data — drop the row instead. Raise only on hard failures (network,
    auth, ticker-not-found).
    """

    name: str

    @abstractmethod
    def fetch_chain(self, ticker: str, max_dte: int = 180) -> ChainSnapshot: ...

    @abstractmethod
    def fetch_underlying_history(
        self,
        ticker: str,
        start: date,
        end: date | None = None,
    ) -> pd.DataFrame:
        """Daily OHLCV bars. Columns: bar_date, open, high, low, close, volume."""
