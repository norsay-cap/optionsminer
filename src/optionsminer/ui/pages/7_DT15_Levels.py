"""DT15 daily range / levels — predictive intraday range for ES futures.

Independent of the option-chain snapshots: pulls ES + VIX daily bars live from
yfinance each time the page loads, computes the four anchored levels (avg±,
ext±) around today's anchor (yfinance Open by default, user-overridable to
the 9:30 AM ET RTH first-trade for a tighter intraday read).
"""

from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from optionsminer.analytics import dt15
from optionsminer.storage import dt15_storage
from optionsminer.storage.db import init_db
from optionsminer.ui.common import DT15_VARIANT_LABELS, dt15_variant_picker

init_db()

st.set_page_config(page_title="DT15 levels", layout="wide")

st.markdown("## ES futures · DT15 daily range")
st.caption(
    "Predicted intraday range for ES=F based on a blend of recent realised range and "
    "the VIX-implied move. Four anchored levels project the expected high/low band."
)
st.info(
    "**Note:** the avg± / ext± bands are projected **symmetrically around the open**. "
    "On trending days, expect the actual H/L to bias in the direction of the trend — "
    "the band is a width estimate, not a directional forecast."
)

variant = dt15_variant_picker()
st.caption(
    f"Methodology: **{DT15_VARIANT_LABELS[variant]}** · "
    + (
        "M_up=2.27, M_dn=2.97 (locked static)."
        if variant == "baseline"
        else "M_up/M_dn widened from a tighter base by an R1-driven path indicator "
        "(positive R1 widens upside, negative R1 widens downside)."
    )
)

with st.expander("**How to read this page**"):
    st.markdown(
        f"""
        **What this is.** A predictive estimate of today's ES intraday range, anchored on
        the session open. The prediction blends two estimators:

        1. **RM5** — the simple 5-day average of the daily High–Low range. Captures the
           current realised-vol regime.
        2. **VIX-implied range** = `K_BM · σ_VIX · prior_close`, where `K_BM = √(8/π) ≈
           {dt15.K_BM:.4f}` is the Brownian-motion expected absolute move (mean-absolute-
           deviation factor), and `σ_VIX = (VIX/100) / √252` is the per-day vol from
           prior VIX close. Multiplied by `{dt15.VIX_BLEND_K:.2f}` so the realised side
           dominates unless VIX-implied vol is meaningfully higher.

        `range_pred = max(RM5, {dt15.VIX_BLEND_K:.2f} · range_vix)`

        **The four levels** are then projected around the anchor `O_t`:

        | Level | Formula | Meaning |
        |---|---|---|
        | **avg+** | O_t + 0.5 · range_pred | Upper edge of the *expected* daily range |
        | **avg−** | O_t − 0.5 · range_pred | Lower edge of the expected daily range |
        | **ext+** | O_t + 0.5 · range_pred · {dt15.M_UP} | Upper *extension* — outsized-day stretch target |
        | **ext−** | O_t − 0.5 · range_pred · {dt15.M_DN} | Lower extension — note the asymmetry (downside fatter) |

        The `M_up = {dt15.M_UP}` / `M_dn = {dt15.M_DN}` asymmetry is locked from the original
        DT15 study and reflects equity-index downside fat-tail behaviour.

        **Anchor — important.**
        - Default is the **yfinance daily Open**, which for ES futures = the 6 PM ET
          previous-evening **ETH** session start. Computed against this, the levels reflect
          the *full overnight + RTH* range.
        - Override with the **9:30 AM ET RTH first-trade price** for a tighter, RTH-only
          intraday read — usually the more actionable view for day traders.

        **How to use it:**
        - **Trade towards avg+/avg−** as initial reaction targets when price moves off the open.
        - **Reaching ext+/ext−** is statistically a *trend-day signal* — fade with care, the
          market is in expansion mode (low chance of mean-reversion the same session).
        - **Range-pred lower than RM5 by a lot** = the market is pricing today as quieter
          than recent average. Combine with VRP and gamma regime for confluence.
        - **VIX-implied range >> RM5** = market is pricing in much more movement than has
          materialised — the levels lean on the wider VIX side via the blend.

        **Important — these bands are open-anchored, not drift-aware.** The avg± /
        ext± levels are projected symmetrically around the open, so on a strongly
        trending day price will systematically extend further on the trend side and
        less on the opposite side, even when the *total* range is correctly predicted.
        Treat the bands as a width estimate centred on the open; expect the actual
        H/L to **bias in the direction of the trend** during a directional session.
        See the **DT15 Backtest** page — the in-band hit rate is sensitive to drift
        as much as to range accuracy.
        """
    )

# Optional anchor override
col_a, col_b = st.columns([1, 1])
with col_a:
    use_override = st.checkbox(
        "Override anchor (use a custom open price)",
        value=False,
        key="dt15_use_override",
        help="Default anchor is yfinance's daily Open (= 6 PM ET ETH session start). "
        "Override with the 9:30 AM ET RTH first-trade for a tighter intraday read.",
    )
with col_b:
    override_value = st.number_input(
        "Anchor price override",
        value=0.00,
        step=0.25,
        format="%.2f",
        disabled=not use_override,
        key="dt15_override_value",
        help="ES=F price to use as the anchor O_t. Only used if the override checkbox is on.",
    )

# Compute
override_arg = float(override_value) if (use_override and override_value > 0) else None
try:
    with st.spinner(f"Pulling ES=F + ^VIX from yfinance ({variant})…"):
        lv = dt15.compute_live(today_open_override=override_arg, variant=variant)
except Exception as e:  # noqa: BLE001
    st.error(f"DT15 computation failed: {e}")
    st.stop()

# Persistence: auto-record the yfinance-anchored prediction once per day per
# variant. The override version is only persisted when the user clicks
# "Lock prediction" below.
if not use_override:
    try:
        dt15_storage.record_prediction(lv)
    except Exception as e:  # noqa: BLE001
        st.warning(f"Could not persist today's prediction: {e}")
try:
    n_settled = dt15_storage.settle_pending()
    if n_settled > 0:
        st.toast(f"Settled {n_settled} prior prediction(s)", icon="✅")
except Exception as e:  # noqa: BLE001
    st.warning(f"Settlement pass failed: {e}")

# Headline
anchor_label = "OVERRIDE" if lv.anchor_source == "override" else "yfinance Open (ETH 6 PM ET)"
st.caption(
    f"As of {lv.asof_date} · anchor = **{lv.today_open_used:,.2f}** ({anchor_label}) · "
    f"prior close {lv.prior_close:,.2f} · prior VIX {lv.vix_prior_close:.2f}"
)

c1, c2, c3, c4 = st.columns(4)
c1.metric(
    "RM5 (5-day mean H–L)",
    f"{lv.rm5:,.2f}",
    help="Simple average of the last 5 daily High − Low ranges. The realised-vol baseline.",
)
c2.metric(
    "VIX-implied range",
    f"{lv.range_vix:,.2f}",
    delta=f"{dt15.VIX_BLEND_K:.0%} = {dt15.VIX_BLEND_K * lv.range_vix:,.2f}",
    help="K_BM · σ_VIX · prior_close. The expected daily absolute move from prior VIX close. "
    "Blended into the prediction at 60% weight.",
)
c3.metric(
    "Range prediction",
    f"{lv.range_pred:,.2f}",
    help="max(RM5, 0.60 · range_vix). The realised side wins unless VIX is meaningfully bid.",
)
c4.metric(
    "Open used (anchor)",
    f"{lv.today_open_used:,.2f}",
    delta=(f"{lv.today_open_used - lv.today_open_yf:+,.2f} vs yf"
           if lv.anchor_source == "override" else None),
    help="The O_t price that all four levels are projected from.",
)

# Variant-specific M / R1 row
m_c1, m_c2, m_c3, m_c4 = st.columns(4)
m_c1.metric(
    "M_up used",
    f"{lv.m_up_used:.3f}",
    delta=(f"vs baseline {dt15.M_UP_BASELINE:.2f}"
           if variant == "enh_b" else None),
    help="Upside-extension multiplier. Baseline locks at 2.27; Enhancement B "
    "starts at 1.87 and widens proportionally to positive R1 (recent up-trend).",
)
m_c2.metric(
    "M_dn used",
    f"{lv.m_dn_used:.3f}",
    delta=(f"vs baseline {dt15.M_DN_BASELINE:.2f}"
           if variant == "enh_b" else None),
    help="Downside-extension multiplier. Baseline locks at 2.97; Enhancement B "
    "starts at 2.57 and widens proportionally to negative R1 (recent down-trend).",
)
m_c3.metric(
    "R1 (raw)",
    f"{lv.r1:.5f}" if lv.r1 is not None else "—",
    help="TSPL-weighted sum of the past 250 daily log returns. Positive = recent "
    "up-trend, negative = recent down-trend. Only computed for Enhancement B.",
)
m_c4.metric(
    "R1 (σ-normalised)",
    f"{lv.r1_normalized:+.2f}σ" if lv.r1_normalized is not None else "—",
    help="R1 divided by σ_R1 (≈0.00142). |value| > 1 means the path indicator is "
    "more than 1 std-dev away from zero, which materially widens the relevant side.",
)

if use_override and override_value > 0:
    st.warning(
        f"You're viewing an **override-anchored** prediction — this is NOT yet "
        f"persisted to the backtest. Click **Lock prediction** to replace today's "
        f"recorded prediction with this override-anchored version."
    )
    if st.button("🔒 Lock prediction (replaces today's record)", type="primary"):
        dt15_storage.record_prediction(lv)
        st.toast("Override-anchored prediction recorded.", icon="🔒")

st.divider()

# Levels table
st.markdown("#### Levels (anchored on O_t)")

l1, l2, l3, l4, l5 = st.columns(5)
l1.metric(
    f"ext+  (M_up={dt15.M_UP})",
    f"{lv.ext_plus:,.2f}",
    delta=f"{lv.ext_plus - lv.today_open_used:+,.2f}",
    help="Upper extension target. Reaching it is a trend-day signal.",
)
l2.metric(
    "avg+",
    f"{lv.avg_plus:,.2f}",
    delta=f"{lv.avg_plus - lv.today_open_used:+,.2f}",
    help="Upper edge of expected daily range.",
)
l3.metric(
    "Anchor (O_t)",
    f"{lv.today_open_used:,.2f}",
    help="The open price all levels project from.",
)
l4.metric(
    "avg−",
    f"{lv.avg_minus:,.2f}",
    delta=f"{lv.avg_minus - lv.today_open_used:+,.2f}",
    help="Lower edge of expected daily range.",
)
l5.metric(
    f"ext−  (M_dn={dt15.M_DN})",
    f"{lv.ext_minus:,.2f}",
    delta=f"{lv.ext_minus - lv.today_open_used:+,.2f}",
    help="Lower extension target. Note asymmetry — downside multiplier > upside.",
)

# Visualisation: horizontal level lines on a number-line, banded
st.markdown("#### Visual")
fig = go.Figure()
fig.update_xaxes(visible=False)
fig.update_yaxes(visible=True, title="Price")

# Bands
fig.add_hrect(y0=lv.avg_minus, y1=lv.avg_plus,
              fillcolor="rgba(0,196,154,0.10)", line_width=0,
              annotation_text="expected band (avg± )", annotation_position="top left")
fig.add_hrect(y0=lv.avg_plus, y1=lv.ext_plus,
              fillcolor="rgba(255,209,102,0.08)", line_width=0)
fig.add_hrect(y0=lv.ext_minus, y1=lv.avg_minus,
              fillcolor="rgba(255,107,107,0.08)", line_width=0)

for label, y, color in [
    (f"ext+  ({lv.ext_plus:,.2f})",  lv.ext_plus,  "#FFD166"),
    (f"avg+  ({lv.avg_plus:,.2f})",  lv.avg_plus,  "#00C49A"),
    (f"O_t   ({lv.today_open_used:,.2f})", lv.today_open_used, "#FFFFFF"),
    (f"avg−  ({lv.avg_minus:,.2f})", lv.avg_minus, "#00C49A"),
    (f"ext−  ({lv.ext_minus:,.2f})", lv.ext_minus, "#FF6B6B"),
]:
    fig.add_hline(y=y, line_color=color, line_width=2,
                  line_dash="solid" if "O_t" in label else "dash",
                  annotation_text=label, annotation_position="right")

# Anchor a marker at prior close so the visual scale is sensible
fig.add_scatter(x=[0], y=[lv.prior_close], mode="markers+text",
                marker=dict(size=10, color="#888"),
                text=[f"prior close {lv.prior_close:,.2f}"],
                textposition="middle right", showlegend=False)

fig.update_layout(
    height=520, template="plotly_dark", margin=dict(l=10, r=120, t=10, b=10),
)
st.plotly_chart(fig, width="stretch")

st.caption(
    "DT15 constants are locked from the original study and not user-tunable. "
    "Levels are recomputed live each page load — no snapshot persistence is used."
)
