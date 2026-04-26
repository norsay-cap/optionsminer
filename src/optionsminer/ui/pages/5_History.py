"""Historical trends across snapshots — the value-add of persistence.

Shows time series of GEX, ATM IV term, VRP, RR25, and PCR for the selected
ticker so the trader can see regime drift, not just today's snapshot.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots
from sqlalchemy import select

from optionsminer.config import settings
from optionsminer.storage.db import session_scope
from optionsminer.storage.models import DerivedMetrics, Snapshot
from optionsminer.ui.common import page_header

st.set_page_config(page_title="History", layout="wide")
st.sidebar.markdown("### Snapshot")

# Share the ticker selection with the rest of the dashboard via session state.
default_ticker = "^SPX" if "^SPX" in settings.tickers else settings.tickers[0]
if "om_ticker" not in st.session_state:
    st.session_state["om_ticker"] = default_ticker
elif st.session_state["om_ticker"] not in settings.tickers:
    st.session_state["om_ticker"] = default_ticker

ticker = st.sidebar.selectbox(
    "Ticker",
    options=settings.tickers,
    key="om_ticker",
)
limit = st.sidebar.slider("Last N snapshots", 5, 500, 100, key="om_history_limit")

page_header(f"{ticker} · history", f"Last {limit} snapshots")

with st.expander("**How to read this page**"):
    st.markdown(
        """
        This page shows how the regime has been **shifting over time** — usually more
        valuable than any single snapshot, because most signals are best read as deviations
        from their own recent norms.

        - **Spot vs Total GEX (top):** when GEX dips toward or below zero while spot is
          rising, dealer positioning is becoming less supportive — vol expansion may be
          coming. Conversely, GEX climbing during a chop confirms the suppression regime.
        - **ATM IV term (middle):** watch for the **7D line crossing above the 30D line** —
          that's a backwardation flip and historically precedes vol spikes by hours-to-days.
        - **VRP:** when this turns *negative*, the market is under-pricing actual movement.
          One of the highest-edge long-vol setups.
        - **Skew:** RR25 trending down while spot is making new highs = hedges being
          *removed* into strength → safety net thinning.
        - **PCR:** for index PCR, **direction matters more than absolute level**. Rising into
          a top = institutions adding hedges (typical). Falling into a top = hedges being
          lifted (bearish — they don't need them anymore).

        **Best regime-shift signals (any 2 of these together = high conviction):**
        1. VRP turns negative
        2. Term slope flips from positive to negative
        3. Total GEX drops below zero
        4. RR25 expands from already-rich levels
        """
    )

with session_scope() as s:
    rows = s.execute(
        select(
            Snapshot.snapshot_id,
            Snapshot.snapshot_ts,
            Snapshot.spot,
            DerivedMetrics.total_gex,
            DerivedMetrics.zero_gamma,
            DerivedMetrics.atm_iv_7,
            DerivedMetrics.atm_iv_30,
            DerivedMetrics.atm_iv_90,
            DerivedMetrics.term_slope,
            DerivedMetrics.rr25_30d,
            DerivedMetrics.skew_90_110_30d,
            DerivedMetrics.pcr_vol,
            DerivedMetrics.pcr_oi,
            DerivedMetrics.vrp_30,
            DerivedMetrics.implied_move_weekly,
            DerivedMetrics.call_wall,
            DerivedMetrics.put_wall,
            DerivedMetrics.max_pain_30d,
        )
        .join(DerivedMetrics, DerivedMetrics.snapshot_id == Snapshot.snapshot_id, isouter=True)
        .where(Snapshot.ticker == ticker.upper())
        .order_by(Snapshot.snapshot_ts.desc())
        .limit(limit)
    ).all()

if not rows:
    st.info(f"No snapshots for {ticker} yet.")
    st.stop()

df = pd.DataFrame(rows, columns=[
    "snapshot_id", "snapshot_ts", "spot", "total_gex", "zero_gamma",
    "atm_iv_7", "atm_iv_30", "atm_iv_90", "term_slope",
    "rr25_30d", "skew_90_110_30d", "pcr_vol", "pcr_oi", "vrp_30",
    "implied_move_weekly", "call_wall", "put_wall", "max_pain_30d",
]).sort_values("snapshot_ts").reset_index(drop=True)

# Spot + GEX
fig = make_subplots(specs=[[{"secondary_y": True}]])
fig.add_scatter(x=df["snapshot_ts"], y=df["spot"], name="spot",
                line=dict(color="#FFD166"), secondary_y=False)
fig.add_bar(x=df["snapshot_ts"], y=df["total_gex"], name="Total GEX",
            marker=dict(color="rgba(0,196,154,0.45)"), opacity=0.6, secondary_y=True)
fig.update_layout(height=320, template="plotly_dark", margin=dict(l=10, r=10, t=30, b=10),
                  title="Spot vs Total GEX")
fig.update_yaxes(title_text="Spot", secondary_y=False)
fig.update_yaxes(title_text="GEX ($/1%)", secondary_y=True)
st.plotly_chart(fig, width='stretch')

# IV term: 7/30/90
fig2 = go.Figure()
for col, color in (("atm_iv_7", "#FF6B6B"), ("atm_iv_30", "#00C49A"), ("atm_iv_90", "#118AB2")):
    fig2.add_scatter(x=df["snapshot_ts"], y=df[col] * 100, mode="lines+markers",
                     name=col.replace("atm_iv_", "ATM IV "),
                     line=dict(color=color))
fig2.update_layout(height=300, template="plotly_dark", margin=dict(l=10, r=10, t=30, b=10),
                   title="ATM IV term (%)", yaxis_title="IV (%)")
st.plotly_chart(fig2, width='stretch')

# VRP + RR25
left, right = st.columns(2)
with left:
    fig3 = go.Figure()
    fig3.add_scatter(x=df["snapshot_ts"], y=df["vrp_30"] * 100, mode="lines+markers",
                     line=dict(color="#00C49A"))
    fig3.add_hline(y=0, line_color="#888", line_dash="dot")
    fig3.update_layout(height=280, template="plotly_dark", title="VRP (vol pts)",
                       margin=dict(l=10, r=10, t=30, b=10), yaxis_title="VRP %")
    st.plotly_chart(fig3, width='stretch')
with right:
    fig4 = go.Figure()
    fig4.add_scatter(x=df["snapshot_ts"], y=df["rr25_30d"] * 100, name="RR25",
                     line=dict(color="#FF6B6B"))
    fig4.add_scatter(x=df["snapshot_ts"], y=df["skew_90_110_30d"] * 100, name="Skew 90/110",
                     line=dict(color="#118AB2"))
    fig4.update_layout(height=280, template="plotly_dark", title="Skew (vol pts)",
                       margin=dict(l=10, r=10, t=30, b=10), yaxis_title="vol pts (%)")
    st.plotly_chart(fig4, width='stretch')

# PCR
fig5 = go.Figure()
fig5.add_scatter(x=df["snapshot_ts"], y=df["pcr_vol"], name="PCR volume",
                 line=dict(color="#00C49A"))
fig5.add_scatter(x=df["snapshot_ts"], y=df["pcr_oi"], name="PCR OI",
                 line=dict(color="#118AB2"))
fig5.update_layout(height=260, template="plotly_dark", title="Put/Call ratios",
                   margin=dict(l=10, r=10, t=30, b=10))
st.plotly_chart(fig5, width='stretch')

st.dataframe(df.tail(50), width='stretch', hide_index=True)
