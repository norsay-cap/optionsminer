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

with st.expander("**How to read this page**"):
    st.markdown(
        """
        Each row is a strike where today's volume exceeds the configured thresholds —
        a candidate for "someone is positioning here." The **score column** ranks candidates
        by `vol/OI · sqrt(volume)` so big-volume, high-vol/OI hits surface first.

        **What the columns mean:**
        - `vol_oi_ratio` — today's volume divided by yesterday's OI. **>1.0** means more
          contracts traded today than existed yesterday — strong sign of new positioning.
        - `notional_dollars` — total $ value at the mid (price × volume × 100 multiplier).
        - `iv` — recomputed implied vol at this strike.
        - `score` — internal ranking (higher = more unusual).

        **How to act:**
        - **Filter to your trading horizon.** Default is DTE 7–60 to filter expiry-roll noise
          and far-out lottery plays. Narrow if you're focused on weeklies.
        - **A new big block at a strike you haven't seen before, combined with fresh OI build
          the next day, is the strongest signal.** Single-snapshot UOA is noise more often
          than signal — wait for *repeat* activity.
        - **Cross-check against walls.** A UOA hit at a strike that's *also* a major OI wall
          is more meaningful than one at a random strike.
        - **Loosen the filters** if no rows pass — the defaults are conservative.

        **What this dashboard CANNOT detect** (needs trade tape, not yfinance):
        - Sweeps (single buyer hitting multiple exchanges simultaneously)
        - Block prints (off-exchange large trades)
        - Aggressor classification (was it a buy or a sell?)

        These will be available once we swap in the Schwab broker provider.
        """
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

st.caption(
    "See the **Guide** page for the full UOA explainer and what's possible when we swap to "
    "Schwab data."
)
