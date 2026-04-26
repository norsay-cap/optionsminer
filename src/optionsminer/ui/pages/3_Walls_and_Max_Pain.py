"""Walls + max pain — combined view since they're interpreted together."""

from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from optionsminer.analytics import max_pain as mp_mod
from optionsminer.analytics import walls as walls_mod
from optionsminer.ui.common import cached_chain, fmt_strike, page_header, sidebar_picker

st.set_page_config(page_title="Walls & max pain", layout="wide")
ticker, snap = sidebar_picker()
if snap is None:
    st.stop()

chain = cached_chain(snap.snapshot_id)

band_pct = st.sidebar.slider("Band ±% of spot", 1, 20, 8) / 100.0
top_n = st.sidebar.slider("Top-N walls", 3, 15, 6)

walls = walls_mod.gamma_oi_walls(chain, snap.spot, band_pct=band_pct, top_n=top_n)

# soonest non-zero expiry max pain
mp_strike, mp_curve = mp_mod.max_pain(chain)

page_header(
    f"{snap.ticker} · OI walls & max pain",
    f"Spot {snap.spot:,.2f}  ·  Snapshot {snap.snapshot_ts:%Y-%m-%d %H:%M UTC}",
)

with st.expander("**How to read this page**"):
    st.markdown(
        """
        **Walls** (left): the strikes within ±band% of spot ranked by `|gamma · OI|`. We use
        gamma-weighted OI rather than raw OI because far-OTM strikes — even with large OI —
        barely affect dealer hedging. Strikes **above spot are green** (potential resistance);
        **below spot are red** (potential support).

        **Max-pain payout curve** (right): the total writer payout if the underlying expired
        at each hypothetical strike. The white dashed line marks the minimum (max pain).

        **How to act:**
        - Walls work as **soft S/R**, especially in positive-GEX regimes.
        - **Range-trade between the dominant call wall and put wall** when gamma is positive.
        - **A break of a major wall in negative-GEX regimes** often triggers acceleration.
        - **Max pain alone is mostly folklore.** Treat it as a *confluence* signal — when it
          coincides with the zero-gamma flip and a dominant wall, the level is real.
        - Watch the **History** page for *new* walls appearing day-over-day — fresh OI
          builds are stronger signals than old ones.
        """
    )

c1, c2 = st.columns(2)
c1.metric(
    "Max pain (front expiry)",
    fmt_strike(mp_strike),
    help="Strike that minimises total writer payout on the soonest expiry. "
    "Use as confluence with zero-gamma + walls, not standalone.",
)
c2.metric(
    "Walls within band",
    str(len(walls)),
    help="Count of strikes inside the ±band% range that pass the gamma·OI threshold.",
)

left, right = st.columns([3, 2])
with left:
    st.markdown("#### Gamma-weighted OI walls")
    if walls.empty:
        st.info("No qualifying strikes — try widening the band.")
    else:
        fig = go.Figure()
        fig.add_bar(
            x=walls["strike"],
            y=walls["gamma_oi"],
            marker=dict(color=["#00C49A" if s == "above" else "#FF6B6B" for s in walls["side"]]),
        )
        fig.add_vline(x=snap.spot, line_color="#FFD166", annotation_text="spot")
        fig.update_layout(
            height=380, template="plotly_dark", margin=dict(l=10, r=10, t=10, b=10),
            xaxis_title="Strike", yaxis_title="|gamma · OI|",
        )
        st.plotly_chart(fig, width='stretch')
        st.dataframe(walls, width='stretch', hide_index=True)

with right:
    st.markdown("#### Max-pain payout curve")
    if mp_curve.empty:
        st.info("No OI to compute payout.")
    else:
        # Restrict for readability
        band = mp_curve[mp_curve["strike"].between(snap.spot * 0.9, snap.spot * 1.1)]
        fig2 = go.Figure()
        fig2.add_scatter(x=band["strike"], y=band["payout"], mode="lines",
                         line=dict(color="#00C49A"))
        fig2.add_vline(x=snap.spot, line_color="#FFD166", annotation_text="spot")
        if mp_strike is not None:
            fig2.add_vline(x=mp_strike, line_color="#FFFFFF", line_dash="dash",
                           annotation_text="max pain")
        fig2.update_layout(
            height=380, template="plotly_dark", margin=dict(l=10, r=10, t=10, b=10),
            xaxis_title="Hypothetical expiry print", yaxis_title="Total writer payout",
        )
        st.plotly_chart(fig2, width='stretch')

st.caption(
    "See the **Guide** page for the full walls + max-pain explainer."
)
