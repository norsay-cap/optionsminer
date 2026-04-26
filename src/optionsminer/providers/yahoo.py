"""Yahoo Finance provider via yfinance.

Quirks handled:
- yfinance returns chains per-expiry; we aggregate to a single frame.
- IV in the yfinance chain is theirs, often inconsistent — we keep it as
  `iv_provider` and the ingest pipeline recomputes from mid quotes.
- Stale quotes (lastTradeDate older than today) are dropped from any
  IV-sensitive analytics downstream — we still keep the row for OI metrics.
- For ^SPX (SPX index), yfinance exposes `^SPX` and the chains there.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone

import pandas as pd
import yfinance as yf
from tenacity import retry, stop_after_attempt, wait_exponential

from optionsminer.providers.base import ChainSnapshot, DataProvider

log = logging.getLogger(__name__)


class YahooProvider(DataProvider):
    name = "yfinance"

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10), reraise=True)
    def fetch_chain(self, ticker: str, max_dte: int = 180) -> ChainSnapshot:
        tk = yf.Ticker(ticker)

        spot = self._spot_for(tk, ticker)
        snapshot_ts = datetime.now(timezone.utc)
        today = snapshot_ts.date()

        try:
            expiries = list(tk.options or [])
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(f"yfinance failed to list expiries for {ticker}: {e}") from e

        if not expiries:
            raise RuntimeError(f"No option expiries returned for {ticker}")

        frames = []
        for exp_str in expiries:
            try:
                exp = date.fromisoformat(exp_str)
            except ValueError:
                continue
            dte = (exp - today).days
            if dte < 0 or dte > max_dte:
                continue
            try:
                chain = tk.option_chain(exp_str)
            except Exception as e:  # noqa: BLE001
                log.warning("yfinance chain fetch failed for %s %s: %s", ticker, exp_str, e)
                continue

            for cp_label, df in (("C", chain.calls), ("P", chain.puts)):
                if df is None or df.empty:
                    continue
                f = self._normalise(df, exp, cp_label, dte)
                if not f.empty:
                    frames.append(f)

        if not frames:
            raise RuntimeError(f"No usable option rows assembled for {ticker}")

        quotes = pd.concat(frames, ignore_index=True)
        return ChainSnapshot(
            ticker=ticker.upper(),
            snapshot_ts=snapshot_ts,
            spot=spot,
            quotes=quotes,
        )

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10), reraise=True)
    def fetch_underlying_history(
        self,
        ticker: str,
        start: date,
        end: date | None = None,
    ) -> pd.DataFrame:
        tk = yf.Ticker(ticker)
        end_eff = end or date.today()
        df = tk.history(
            start=start.isoformat(),
            end=(end_eff.isoformat()),
            interval="1d",
            auto_adjust=False,
        )
        if df is None or df.empty:
            return pd.DataFrame(columns=["bar_date", "open", "high", "low", "close", "volume"])
        df = df.reset_index().rename(
            columns={
                "Date": "bar_date",
                "Open": "open",
                "High": "high",
                "Low": "low",
                "Close": "close",
                "Volume": "volume",
            }
        )
        df["bar_date"] = pd.to_datetime(df["bar_date"]).dt.date
        return df[["bar_date", "open", "high", "low", "close", "volume"]]

    # -- helpers ---------------------------------------------------------------

    @staticmethod
    def _spot_for(tk: "yf.Ticker", ticker: str) -> float:
        # `fast_info` is the cheapest accurate field on yfinance >= 0.2
        try:
            spot = float(tk.fast_info["last_price"])
            if spot > 0:
                return spot
        except Exception:  # noqa: BLE001
            pass
        # Fallback: 1-day history close
        h = tk.history(period="1d", interval="1m")
        if h is None or h.empty:
            raise RuntimeError(f"Could not determine spot for {ticker}")
        return float(h["Close"].iloc[-1])

    @staticmethod
    def _normalise(df: pd.DataFrame, exp: date, cp: str, dte: int) -> pd.DataFrame:
        """Map yfinance columns to our canonical schema and clip nonsense rows."""
        cols = {
            "strike": "strike",
            "bid": "bid",
            "ask": "ask",
            "lastPrice": "last",
            "volume": "volume",
            "openInterest": "open_interest",
            "impliedVolatility": "iv_provider",
            "lastTradeDate": "last_trade_ts",
        }
        out = pd.DataFrame()
        for src, dst in cols.items():
            out[dst] = df[src] if src in df.columns else None

        out["expiry"] = exp
        out["cp"] = cp
        out["dte"] = dte

        for c in ("strike", "bid", "ask", "last", "iv_provider"):
            out[c] = pd.to_numeric(out[c], errors="coerce")
        for c in ("volume", "open_interest"):
            out[c] = pd.to_numeric(out[c], errors="coerce").fillna(0).astype("Int64")

        # Mid only when both legs of the quote are present and sane
        bid_ok = out["bid"].fillna(0) > 0
        ask_ok = out["ask"].fillna(0) > 0
        out["mid"] = ((out["bid"] + out["ask"]) / 2.0).where(bid_ok & ask_ok)

        # Drop rows with no strike (corrupt yfinance data does this rarely)
        out = out.dropna(subset=["strike"])
        # Drop dupe (strike, cp, expiry) — yfinance occasionally emits
        out = out.drop_duplicates(subset=["expiry", "strike", "cp"], keep="last")

        return out[
            [
                "expiry",
                "strike",
                "cp",
                "dte",
                "bid",
                "ask",
                "last",
                "mid",
                "volume",
                "open_interest",
                "iv_provider",
                "last_trade_ts",
            ]
        ]
