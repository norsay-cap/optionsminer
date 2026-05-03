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


# Persistent state lives under non-widget keys so multipage navigation
# doesn't lose them — Streamlit can drop widget-key-tied state on certain
# page transitions, but plain session_state keys we manage ourselves
# survive consistently.
_TICKER_KEY = "_om_ticker_persistent"


def _persistent_ticker() -> str:
    """Read-or-init the persistent ticker, validating against current config."""
    default_ticker = "^SPX" if "^SPX" in settings.tickers else settings.tickers[0]
    if _TICKER_KEY not in st.session_state:
        st.session_state[_TICKER_KEY] = default_ticker
    if st.session_state[_TICKER_KEY] not in settings.tickers:
        st.session_state[_TICKER_KEY] = default_ticker
    return st.session_state[_TICKER_KEY]


def ticker_selectbox(label: str = "Ticker") -> str:
    """Render the ticker dropdown anywhere with the same persisted state.

    Used by sidebar_picker AND the History page so all pages stay in sync.
    """
    current = _persistent_ticker()
    current_idx = settings.tickers.index(current)
    chosen = st.sidebar.selectbox(label, options=settings.tickers, index=current_idx)
    # Manually write back to the persistent key (no key= on the widget,
    # so Streamlit doesn't try to manage it — we own the persistence).
    st.session_state[_TICKER_KEY] = chosen
    return chosen


def sidebar_picker() -> tuple[str, Snapshot | None]:
    """Render ticker + snapshot pickers. Returns (ticker, chosen Snapshot).

    Selections persist across all pages within the same browser session via
    non-widget session_state keys. State resets on browser tab close /
    hard refresh — the typical desired UX.
    """
    st.sidebar.markdown("### Snapshot")
    ticker = ticker_selectbox("Ticker")

    snaps = list_snapshots(ticker, limit=200)
    if not snaps:
        st.sidebar.warning(f"No snapshots for {ticker}. Take one from the Admin page.")
        return ticker, None

    labels = [f"{s.snapshot_ts:%Y-%m-%d %H:%M}  ·  spot {s.spot:.2f}" for s in snaps]

    # Per-ticker persistent key for snapshot date — survives navigation but
    # doesn't collide across tickers (different snapshot list lengths).
    snap_key = f"_om_snap_{ticker}"
    if snap_key not in st.session_state:
        st.session_state[snap_key] = 0
    # Clamp if a prune dropped the previously selected snapshot
    if st.session_state[snap_key] >= len(snaps):
        st.session_state[snap_key] = 0

    idx = st.sidebar.selectbox(
        "Date",
        options=list(range(len(labels))),
        format_func=lambda i: labels[i],
        index=st.session_state[snap_key],
    )
    st.session_state[snap_key] = idx
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
    "ticker_selectbox",
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
