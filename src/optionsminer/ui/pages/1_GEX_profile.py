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

c1, c2, c3, c4 = st.columns(4)
c1.metric("Total GEX", fmt_money(profile.total_gex))
c2.metric("Zero-gamma", fmt_strike(profile.zero_gamma))
c3.metric("Call wall", fmt_strike(profile.call_wall))
c4.metric("Put wall", fmt_strike(profile.put_wall))

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

with st.expander("Notes"):
    st.markdown(
        "- **Positive GEX** → dealers long gamma → sell rallies, buy dips → vol suppression.\n"
        "- **Below zero-gamma** → dealers short gamma → chase moves → vol expansion.\n"
        "- The flip curve uses snapshot IVs frozen as spot is shifted (the standard practitioner "
        "  shortcut — re-solving IV per shifted spot is too slow and adds little for short-horizon "
        "  what-ifs).\n"
        "- 0DTE is excluded by default because yfinance OI is yesterday's close, which "
        "  meaningfully distorts intraday 0DTE GEX."
    )
