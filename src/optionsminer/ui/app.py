"""Streamlit entrypoint — overview / dashboard home.

Run:
    uv run streamlit run src/optionsminer/ui/app.py

Each `pages/*.py` file shows up automatically as a sidebar nav item.
"""

from __future__ import annotations

import os

import streamlit as st

from optionsminer.storage import disk_guard
from optionsminer.storage.db import init_db
from optionsminer.ui.common import (
    cached_chain,
    fmt_money,
    fmt_pct,
    fmt_strike,
    fmt_vol,
    get_metrics,
    page_header,
    sidebar_picker,
)

st.set_page_config(
    page_title="optionsminer",
    page_icon=":chart_with_upwards_trend:",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Make sure the schema exists on first run (Coolify volume might be empty)
init_db()

# Optional in-process scheduler — driven by env var so local dev doesn't run it
if os.environ.get("OPTIONSMINER_ENABLE_SCHEDULER", "").lower() in ("1", "true", "yes"):
    from optionsminer import scheduler as _sched

    @st.cache_resource(show_spinner=False)
    def _start_scheduler():  # noqa: ANN202
        return _sched.start()

    _start_scheduler()

st.markdown(
    "# optionsminer  \n*Self-hosted options analytics for SPY/SPX.*"
)

ticker, snap = sidebar_picker()

# Disk meter — always visible, this was an explicit user requirement
rep = disk_guard.report()
sb_emoji = {"OK": ":white_check_mark:", "WARN": ":warning:", "OVER": ":x:"}[rep.state]
st.sidebar.markdown("### Storage")
st.sidebar.metric(
    label=f"DB usage  {sb_emoji}",
    value=f"{rep.used_gb:.3f} / {rep.cap_gb:.0f} GB",
    delta=f"{rep.used_pct*100:.1f}%",
)

if snap is None:
    st.info(
        "No snapshots yet for this ticker.\n\n"
        "On the host, run:\n```\nuv run optionsminer-snapshot\n```\n"
        "Then refresh."
    )
    st.stop()

m = get_metrics(snap.snapshot_id)
chain = cached_chain(snap.snapshot_id)

page_header(
    f"{snap.ticker} · spot {snap.spot:,.2f}",
    f"Snapshot {snap.snapshot_ts:%Y-%m-%d %H:%M UTC}  ·  "
    f"{len(chain):,} strikes  ·  source {snap.source}",
)

# Top-line numbers
c1, c2, c3, c4 = st.columns(4)
c1.metric("Total GEX  (per 1%)", fmt_money(m.total_gex if m else None))
c2.metric(
    "Zero-gamma flip",
    fmt_strike(m.zero_gamma if m else None),
    delta=(
        f"{(m.zero_gamma - snap.spot):+.2f}" if m and m.zero_gamma is not None else None
    ),
)
c3.metric("ATM IV (30D)", fmt_vol(m.atm_iv_30 if m else None))
c4.metric("VRP (IV30 − RV21)", fmt_vol(m.vrp_30 if m else None))

st.divider()

c5, c6, c7, c8 = st.columns(4)
c5.metric("Call wall", fmt_strike(m.call_wall if m else None))
c6.metric("Put wall", fmt_strike(m.put_wall if m else None))
c7.metric("Max pain (front)", fmt_strike(m.max_pain_30d if m else None))
c8.metric("Implied move (1W)", fmt_pct(m.implied_move_weekly if m else None))

c9, c10, c11, c12 = st.columns(4)
c9.metric("25Δ Risk Reversal (30D)", fmt_vol(m.rr25_30d if m else None))
c10.metric("Skew 90/110 (30D)", fmt_vol(m.skew_90_110_30d if m else None))
c11.metric("PCR (volume, ≥7 DTE)", f"{m.pcr_vol:.2f}" if m and m.pcr_vol else "—")
c12.metric("Term slope (7→30D)", fmt_vol(m.term_slope if m else None))

st.divider()

# Quick regime read
if m is not None:
    bullets: list[str] = []
    if m.total_gex is not None:
        regime = "positive (vol-suppression)" if m.total_gex > 0 else "negative (vol-expansion)"
        bullets.append(f"**Gamma regime:** {regime} — total GEX {fmt_money(m.total_gex)} per 1%.")
    if m.zero_gamma is not None:
        side = "above" if snap.spot > m.zero_gamma else "below"
        bullets.append(
            f"**Spot is {side} the zero-gamma flip** at {fmt_strike(m.zero_gamma)} "
            f"(distance {abs(snap.spot - m.zero_gamma):.2f})."
        )
    if m.term_slope is not None:
        if m.term_slope < 0:
            bullets.append(
                f"**Term structure is backwardated** ({fmt_vol(m.term_slope)}) — front-end vol bid relative to 30D."
            )
        elif m.term_slope > 0.05:
            bullets.append(
                f"**Steep contango** ({fmt_vol(m.term_slope)}) — complacency / low front-end vol."
            )
    if m.vrp_30 is not None:
        if m.vrp_30 < 0:
            bullets.append(
                f"**VRP is negative** — implied vol cheaper than realised. Premium-buying regime."
            )
        elif m.vrp_30 > 0.04:
            bullets.append(
                f"**VRP is rich** ({fmt_vol(m.vrp_30)}) — favourable for premium-selling structures."
            )
    if m.rr25_30d is not None and m.rr25_30d > 0.04:
        bullets.append(
            f"**Heavy 25Δ put skew** ({fmt_vol(m.rr25_30d)}) — crash hedged, drift-up regime favoured."
        )

    if bullets:
        st.markdown("#### Regime read")
        for b in bullets:
            st.markdown(f"- {b}")

st.markdown(
    "Use the sidebar to drill into **GEX profile**, **IV skew**, "
    "**Unusual activity**, or the **History** view of past snapshots."
)
