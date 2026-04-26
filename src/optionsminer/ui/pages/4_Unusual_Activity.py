"""Unusual options activity — yfinance-feasible UOA filter."""

from __future__ import annotations

import streamlit as st

from optionsminer.analytics import unusual as uoa_mod
from optionsminer.ui.common import cached_chain, page_header, sidebar_picker

st.set_page_config(page_title="Unusual activity", layout="wide")
ticker, snap = sidebar_picker()
if snap is None:
    st.stop()

chain = cached_chain(snap.snapshot_id)

st.sidebar.markdown("### Filters")
min_vol = st.sidebar.number_input("Min volume", min_value=0, value=500, step=100)
min_vol_oi = st.sidebar.slider("Min vol/OI", 0.1, 5.0, 0.5, step=0.1)
min_dte = st.sidebar.slider("Min DTE", 0, 30, 7)
max_dte = st.sidebar.slider("Max DTE", 7, 180, 60)
min_money = st.sidebar.slider("Min |moneyness|", 0.0, 0.10, 0.02, step=0.005)

uoa = uoa_mod.unusual_today(
    chain,
    min_volume=int(min_vol),
    min_vol_oi=float(min_vol_oi),
    min_dte=int(min_dte),
    max_dte=int(max_dte),
    min_moneyness_pct=float(min_money),
    spot=snap.spot,
)

page_header(
    f"{snap.ticker} · Unusual options activity",
    f"{len(uoa)} candidate rows · spot {snap.spot:,.2f} · "
    f"{snap.snapshot_ts:%Y-%m-%d %H:%M UTC}",
)

if uoa.empty:
    st.info("No rows pass the current filters. Loosen the thresholds.")
else:
    st.dataframe(
        uoa.head(200),
        width='stretch',
        hide_index=True,
        column_config={
            "vol_oi_ratio": st.column_config.NumberColumn(format="%.2f"),
            "notional_dollars": st.column_config.NumberColumn(format="$%,.0f"),
            "iv": st.column_config.NumberColumn(format="%.2f"),
            "score": st.column_config.NumberColumn(format="%.0f"),
            "mid": st.column_config.NumberColumn(format="%.2f"),
            "bid": st.column_config.NumberColumn(format="%.2f"),
            "ask": st.column_config.NumberColumn(format="%.2f"),
        },
    )

with st.expander("What this can — and can't — see"):
    st.markdown(
        "- yfinance gives EOD volume + OI snapshots only, so the UOA filter here is based on "
        "  vol/OI ratios, absolute volume, notional dollars, and moneyness.\n"
        "- **Not detectable from yfinance:** sweeps, blocks, aggressor classification — those "
        "  need NBBO + trade tape (Polygon, Tradier, or Schwab).\n"
        "- The **score** column ranks candidates by `vol/OI · sqrt(volume)` so big-volume, "
        "  high-vol/OI hits surface first."
    )
