"""Shared Streamlit helpers — sidebar, formatters, snapshot picker."""

from __future__ import annotations

import streamlit as st
from sqlalchemy import select

from optionsminer.analytics.loader import latest_snapshot, list_snapshots, load_chain
from optionsminer.config import settings
from optionsminer.storage.db import session_scope
from optionsminer.storage.models import DerivedMetrics, Snapshot


def page_header(title: str, subtitle: str | None = None) -> None:
    st.markdown(f"## {title}")
    if subtitle:
        st.caption(subtitle)


def sidebar_picker() -> tuple[str, Snapshot | None]:
    """Render ticker + snapshot pickers. Returns (ticker, chosen Snapshot)."""
    st.sidebar.markdown("### Snapshot")
    ticker = st.sidebar.selectbox("Ticker", options=settings.tickers, index=0)
    snaps = list_snapshots(ticker, limit=200)
    if not snaps:
        st.sidebar.warning(f"No snapshots for {ticker}. Run `optionsminer-snapshot`.")
        return ticker, None
    labels = [f"{s.snapshot_ts:%Y-%m-%d %H:%M}  ·  spot {s.spot:.2f}" for s in snaps]
    idx = st.sidebar.selectbox(
        "Date", options=list(range(len(labels))), format_func=lambda i: labels[i], index=0
    )
    return ticker, snaps[idx]


def get_metrics(snapshot_id: int) -> DerivedMetrics | None:
    with session_scope() as s:
        return s.get(DerivedMetrics, snapshot_id)


@st.cache_data(show_spinner=False, ttl=300)
def cached_chain(snapshot_id: int):  # noqa: ANN201
    return load_chain(snapshot_id)


def fmt_money(x: float | None, suffix: str = "") -> str:
    if x is None:
        return "—"
    if abs(x) >= 1e9:
        return f"${x/1e9:.2f}B{suffix}"
    if abs(x) >= 1e6:
        return f"${x/1e6:.2f}M{suffix}"
    if abs(x) >= 1e3:
        return f"${x/1e3:.1f}K{suffix}"
    return f"${x:,.2f}{suffix}"


def fmt_pct(x: float | None, decimals: int = 2) -> str:
    if x is None:
        return "—"
    return f"{x*100:.{decimals}f}%"


def fmt_vol(x: float | None) -> str:
    """Format an IV value (e.g. 0.18 -> 18.00%)."""
    return fmt_pct(x, decimals=2) if x is not None else "—"


def fmt_strike(x: float | None) -> str:
    return f"{x:,.2f}" if x is not None else "—"


__all__ = [
    "page_header",
    "sidebar_picker",
    "get_metrics",
    "cached_chain",
    "fmt_money",
    "fmt_pct",
    "fmt_vol",
    "fmt_strike",
    "latest_snapshot",
    "_select_count",
]


def _select_count():  # noqa: ANN202
    return select  # re-export for downstream pages
