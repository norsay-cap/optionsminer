"""IV skew + term structure: smile per expiry + ATM term curve."""

from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from optionsminer.analytics import skew as skew_mod
from optionsminer.ui.common import cached_chain, fmt_vol, page_header, sidebar_picker

st.set_page_config(page_title="IV skew & term", layout="wide")
ticker, snap = sidebar_picker()
if snap is None:
    st.stop()

chain = cached_chain(snap.snapshot_id)

target_dte = st.sidebar.slider("Skew target DTE", 1, 90, 30, step=1)
sk = skew_mod.skew_for_expiry(chain, snap.spot, target_dte=target_dte)
term = skew_mod.term_structure(chain, snap.spot)

page_header(
    f"{snap.ticker} · IV skew & term structure",
    f"Spot {snap.spot:,.2f}  ·  Snapshot {snap.snapshot_ts:%Y-%m-%d %H:%M UTC}",
)

with st.expander("**How to read this page**"):
    st.markdown(
        """
        **Smile chart** (left): IV by strike for the chosen expiry. The "smile" or "smirk"
        shape reflects fear of crashes (left side higher = put skew). The two horizontal
        dotted lines show IV at the 25-delta call and 25-delta put — their **difference is
        the Risk Reversal** above.

        **Term structure** (right): ATM IV across all expiries. The shape tells you how the
        market expects vol to evolve.
        - **Upward slope (contango):** normal — far-dated vol higher than near. Above +5% =
          complacency.
        - **Downward slope (backwardation):** stress — front-end bid above 30D. Historically
          the strongest VRP edge for long-vol setups.

        **Trading takeaways:**
        - **Steep put skew + low ATM IV** = "crash hedged, drift up." Favours selling puts /
          call spreads / outright calls.
        - **Skew flattening during a selloff** = capitulation; puts no longer bid. Usually
          near a tradeable bottom.
        - **Skew expanding while market is calm** = something is being aggressively hedged.
          Watch for the catalyst.
        - Compare today's RR25 to its history (use the **History** page) — absolute thresholds
          are misleading because skew has structurally compressed since 2023.
        """
    )

c1, c2, c3, c4 = st.columns(4)
c1.metric(
    "ATM IV",
    fmt_vol(sk.atm_iv),
    help="At-the-money implied vol for the selected expiry. The market's price of vol at this tenor.",
)
c2.metric(
    "25Δ Risk Reversal",
    fmt_vol(sk.rr_25d),
    help="IV(25Δ put) − IV(25Δ call). Positive = put skew = crash hedged. "
    "Modern SPX range ~4–8 vol pts.",
)
c3.metric(
    "Skew 90/110",
    fmt_vol(sk.skew_90_110),
    help="IV(K=0.9·spot) − IV(K=1.1·spot). Same direction as RR25 but moneyness-anchored — "
    "cleaner read on short-dated.",
)
c4.metric(
    "Used DTE",
    f"{sk.expiry_dte}D",
    help="The expiry actually selected (closest available to your slider target).",
)

# Smile chart
left, right = st.columns(2)
with left:
    st.markdown("#### IV smile  (selected expiry)")
    fig = go.Figure()
    band = sk.iv_curve[sk.iv_curve["strike"].between(snap.spot * 0.85, snap.spot * 1.15)]
    fig.add_scatter(x=band["strike"], y=band["iv"] * 100, mode="lines+markers",
                    line=dict(color="#00C49A"), name="IV")
    fig.add_vline(x=snap.spot, line_color="#FFD166", line_dash="solid",
                  annotation_text="spot")
    if sk.iv_25d_call is not None and sk.iv_25d_put is not None:
        fig.add_hline(y=sk.iv_25d_call * 100, line_color="#888", line_dash="dot",
                      annotation_text="25Δ call")
        fig.add_hline(y=sk.iv_25d_put * 100, line_color="#888", line_dash="dot",
                      annotation_text="25Δ put")
    fig.update_layout(
        height=420, template="plotly_dark", margin=dict(l=10, r=10, t=10, b=10),
        xaxis_title="Strike", yaxis_title="Implied vol (%)",
    )
    st.plotly_chart(fig, width='stretch')

with right:
    st.markdown("#### ATM IV term structure")
    if term.empty:
        st.info("No expiries with usable ATM IV.")
    else:
        fig2 = go.Figure()
        fig2.add_scatter(
            x=term["dte"], y=term["atm_iv"] * 100, mode="lines+markers",
            line=dict(color="#00C49A"),
        )
        slope = skew_mod.term_slope(term)
        fig2.update_layout(
            height=420, template="plotly_dark", margin=dict(l=10, r=10, t=10, b=10),
            xaxis_title="DTE (days)", yaxis_title="ATM IV (%)",
            title=f"7→30D slope: {fmt_vol(slope)}",
        )
        st.plotly_chart(fig2, width='stretch')

st.caption(
    "See the **Guide** page for the full skew + term-structure explainer."
)
