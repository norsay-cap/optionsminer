"""GEX profile: per-strike bars + zero-gamma curve + walls."""

from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from optionsminer.analytics import gex as gex_mod
from optionsminer.config import settings
from optionsminer.ui.common import cached_chain, fmt_money, fmt_strike, page_header, sidebar_picker

st.set_page_config(page_title="GEX profile", layout="wide")
ticker, snap = sidebar_picker()
if snap is None:
    st.stop()

chain = cached_chain(snap.snapshot_id)

max_dte = st.sidebar.slider("Max DTE", 1, 90, 60, step=1)
exclude_0dte = st.sidebar.checkbox("Exclude 0DTE (recommended)", value=True)
band_pct = st.sidebar.slider("Strike band (±% of spot)", 1, 25, 8) / 100.0

profile = gex_mod.compute_profile(
    chain,
    snap.spot,
    r=settings.risk_free_rate,
    q=settings.div_yield_for(ticker),
    max_dte=max_dte,
    exclude_0dte=exclude_0dte,
)

page_header(
    f"{snap.ticker} · GEX profile",
    f"Spot {snap.spot:,.2f}  ·  Total GEX {fmt_money(profile.total_gex)} per 1% spot move",
)

with st.expander("**How to read this page**"):
    st.markdown(
        """
        - **Per-strike bars:** green = positive (call) gamma the dealer is long, red = negative
          (put) gamma the dealer is short. Tall green bars above spot are **call walls**
          (resistance); tall red bars below spot are **put walls** (support).
        - **Yellow vertical line = current spot.** White dashed = the **zero-gamma flip** —
          the regime line.
        - **Flip curve:** total GEX as the spot is shifted ±10%. The crossing point with zero
          confirms the flip level. The **slope of the curve through zero** tells you how
          fast the regime would change — steep slope = sensitive boundary.
        - **Sliders in the sidebar** let you cap DTE (default 60D) and exclude 0DTE (default
          on, because yfinance OI is yesterday's stale number).

        **How to act:**
        - **Spot above flip + positive total GEX:** dealers fade rallies → range trading
          between the walls works; sell premium.
        - **Spot below flip + negative total GEX:** dealers chase moves → don't fade
          extensions, momentum trades favoured.
        - **Spot near flip:** transitional — reduce size, watch for the cross.
        - **A wall flips colour or shifts strike materially day-over-day** → fresh OI build,
          a strong signal something is positioning at that level.
        """
    )

c1, c2, c3, c4 = st.columns(4)
c1.metric(
    "Total GEX",
    fmt_money(profile.total_gex),
    help="Sum of $-gamma · OI across all strikes (per 1% spot move). "
    "Positive = vol suppression; Negative = vol expansion.",
)
c2.metric(
    "Zero-gamma",
    fmt_strike(profile.zero_gamma),
    delta=(
        f"{(profile.zero_gamma - snap.spot):+.2f}"
        if profile.zero_gamma is not None else None
    ),
    help="Spot level where total GEX = 0 — the regime line. "
    "The delta number shows distance from current spot.",
)
c3.metric(
    "Call wall",
    fmt_strike(profile.call_wall),
    help="Strike above spot with the largest +GEX. Acts as resistance — dealers must sell delta as price approaches.",
)
c4.metric(
    "Put wall",
    fmt_strike(profile.put_wall),
    help="Strike below spot with the largest −GEX. Acts as support — dealers must buy delta as price approaches.",
)

# By-strike bar chart, banded
band_lo, band_hi = snap.spot * (1 - band_pct), snap.spot * (1 + band_pct)
bs = profile.by_strike[
    profile.by_strike["strike"].between(band_lo, band_hi)
].copy()

bar = go.Figure()
bar.add_bar(
    x=bs["strike"],
    y=bs["gex_dollars"],
    marker=dict(color=["#00C49A" if v >= 0 else "#FF6B6B" for v in bs["gex_dollars"]]),
    name="GEX $/1%",
)
bar.add_vline(x=snap.spot, line_dash="solid", line_color="#FFD166", annotation_text="spot")
if profile.zero_gamma is not None:
    bar.add_vline(x=profile.zero_gamma, line_dash="dash", line_color="#FFFFFF",
                  annotation_text="zero-gamma")
if profile.call_wall is not None:
    bar.add_vline(x=profile.call_wall, line_dash="dot", line_color="#00C49A",
                  annotation_text="call wall")
if profile.put_wall is not None:
    bar.add_vline(x=profile.put_wall, line_dash="dot", line_color="#FF6B6B",
                  annotation_text="put wall")
bar.update_layout(
    height=460, template="plotly_dark", margin=dict(l=10, r=10, t=10, b=10),
    xaxis_title="Strike", yaxis_title="GEX ($ per 1% move)",
)
st.plotly_chart(bar, width='stretch')

# Zero-gamma flip curve
st.markdown("#### Total GEX vs spot (flip curve)")
fc = profile.flip_curve
flip = go.Figure()
flip.add_scatter(x=fc["spot_grid"], y=fc["total_gex"], mode="lines",
                 line=dict(color="#00C49A"), name="Total GEX")
flip.add_hline(y=0, line_color="#888", line_dash="dot")
flip.add_vline(x=snap.spot, line_color="#FFD166", line_dash="solid",
               annotation_text="spot")
if profile.zero_gamma is not None:
    flip.add_vline(x=profile.zero_gamma, line_color="#FFFFFF", line_dash="dash",
                   annotation_text="zero-gamma")
flip.update_layout(
    height=320, template="plotly_dark", margin=dict(l=10, r=10, t=10, b=10),
    xaxis_title="Hypothetical spot", yaxis_title="Σ GEX ($/1%)",
)
st.plotly_chart(flip, width='stretch')

st.caption(
    "Methodology note: the flip curve uses snapshot IVs frozen as spot is shifted (the "
    "standard practitioner shortcut). 0DTE is excluded by default because yfinance OI is "
    "yesterday's close, which would distort intraday 0DTE GEX. See the **Guide** page for the "
    "full GEX explainer."
)
