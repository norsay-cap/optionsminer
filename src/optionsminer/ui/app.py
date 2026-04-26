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
        "Go to the **Admin** page in the sidebar and click **Take snapshot now**, "
        "or wait for the scheduled run (21:15 UTC weekdays). "
        "First-time users should also visit the **Guide** page."
    )
    st.stop()

m = get_metrics(snap.snapshot_id)
chain = cached_chain(snap.snapshot_id)

page_header(
    f"{snap.ticker} · spot {snap.spot:,.2f}",
    f"Snapshot {snap.snapshot_ts:%Y-%m-%d %H:%M UTC}  ·  "
    f"{len(chain):,} strikes  ·  source {snap.source}",
)

st.caption(
    "New here? See the **Guide** page in the sidebar for what every signal means and how to act on it."
)

# Top-line numbers — every metric has a help= tooltip explaining what it is and how to read it
c1, c2, c3, c4 = st.columns(4)
c1.metric(
    "Total GEX  (per 1%)",
    fmt_money(m.total_gex if m else None),
    help=(
        "Gamma Exposure — dollars of dealer delta to hedge per 1% spot move. "
        "**Positive** = dealers fade rallies/buy dips → vol suppression. "
        "**Negative** = dealers chase moves → vol expansion. "
        "Magnitude scale (SPX): >$5B is meaningfully positive, <−$5B meaningfully negative."
    ),
)
c2.metric(
    "Zero-gamma flip",
    fmt_strike(m.zero_gamma if m else None),
    delta=(
        f"{(m.zero_gamma - snap.spot):+.2f}" if m and m.zero_gamma is not None else None
    ),
    help=(
        "The hypothetical spot price where total GEX = 0. The **regime line** between "
        "vol-suppression (above) and vol-expansion (below). The delta number shows distance from spot."
    ),
)
c3.metric(
    "ATM IV (30D)",
    fmt_vol(m.atm_iv_30 if m else None),
    help=(
        "At-the-money implied vol for the ~30-day expiry. The market's price of vol — what "
        "options buyers are paying. Compare to RV (realised) via the VRP metric."
    ),
)
c4.metric(
    "VRP (IV30 − RV21)",
    fmt_vol(m.vrp_30 if m else None),
    help=(
        "Volatility Risk Premium. **Positive** = vol is rich (premium-seller regime). "
        "**Negative** = realised exceeds implied → vol is cheap, favours buying premium. "
        "Modern post-2023 SPX normal range is +2 to +4 vol pts."
    ),
)

st.divider()

c5, c6, c7, c8 = st.columns(4)
c5.metric(
    "Call wall",
    fmt_strike(m.call_wall if m else None),
    help=(
        "The strike above spot with the most positive gamma · OI. Acts as soft resistance — "
        "dealers must sell delta as price approaches it."
    ),
)
c6.metric(
    "Put wall",
    fmt_strike(m.put_wall if m else None),
    help=(
        "The strike below spot with the most negative gamma · OI. Acts as soft support — "
        "dealers must buy delta as price approaches it."
    ),
)
c7.metric(
    "Max pain (front)",
    fmt_strike(m.max_pain_30d if m else None),
    help=(
        "Strike at which total writer payout is minimised on the soonest expiry. "
        "Use only as **confluence** — meaningful when it lines up with zero-gamma and the dominant wall."
    ),
)
c8.metric(
    "Implied move (1W)",
    fmt_pct(m.implied_move_weekly if m else None),
    help=(
        "1-σ expected move into the next weekly expiry, derived from the ATM straddle "
        "(0.85 · straddle ≈ 1σ). Use as a Bollinger-style range for swing trading."
    ),
)

c9, c10, c11, c12 = st.columns(4)
c9.metric(
    "25Δ Risk Reversal (30D)",
    fmt_vol(m.rr25_30d if m else None),
    help=(
        "IV(25-delta put) − IV(25-delta call). **Positive = put skew = crash hedged.** "
        "Modern SPX range ~4–8 vol pts. >10 = aggressive hedging (often contrarian bullish). "
        "<2 = hedging exhausted (often near tops or capitulation lows)."
    ),
)
c10.metric(
    "Skew 90/110 (30D)",
    fmt_vol(m.skew_90_110_30d if m else None),
    help=(
        "IV(strike = 0.9·spot) − IV(strike = 1.1·spot). Same direction as RR25 but "
        "moneyness-anchored — cleaner read on short-dated expiries."
    ),
)
c11.metric(
    "PCR (volume, ≥7 DTE)",
    f"{m.pcr_vol:.2f}" if m and m.pcr_vol else "—",
    help=(
        "Put/Call volume ratio (excludes 0DTE retail noise). "
        "**On indices like SPX/SPY, this is NOT contrarian** — high values reflect institutional hedging "
        "of long stock, often *bullish* positioning."
    ),
)
c12.metric(
    "Term slope (7→30D)",
    fmt_vol(m.term_slope if m else None),
    help=(
        "IV(30D)/IV(7D) − 1. **Positive = contango** (normal). **Negative = backwardation** (acute stress). "
        "Backwardation is historically the strongest VRP edge — vol mispriced rich."
    ),
)

st.divider()

# Plain-English regime read with explicit "what to do about it"
if m is not None:
    st.markdown("#### Regime read")
    bullets: list[str] = []

    # Gamma regime
    if m.total_gex is not None and m.zero_gamma is not None:
        if m.total_gex > 0 and snap.spot > m.zero_gamma:
            bullets.append(
                f"🟢 **Vol-suppression regime.** Total GEX {fmt_money(m.total_gex)}, spot "
                f"{snap.spot - m.zero_gamma:+.2f} above the {fmt_strike(m.zero_gamma)} flip. "
                f"Dealers will fade rallies and buy dips. *Favours premium-selling and "
                f"range-trading between the {fmt_strike(m.put_wall)}/{fmt_strike(m.call_wall)} walls.*"
            )
        elif m.total_gex < 0 and snap.spot < m.zero_gamma:
            bullets.append(
                f"🔴 **Vol-expansion regime.** Total GEX {fmt_money(m.total_gex)}, spot "
                f"{snap.spot - m.zero_gamma:+.2f} below the {fmt_strike(m.zero_gamma)} flip. "
                f"Dealers will chase moves. *Favours directional/momentum trades; avoid being "
                f"short premium.*"
            )
        else:
            bullets.append(
                f"🟡 **Transitional gamma regime.** Spot {snap.spot:,.2f} is near the "
                f"{fmt_strike(m.zero_gamma)} flip. Watch for the cross — reduce position size."
            )

    # Term structure
    if m.term_slope is not None:
        if m.term_slope < -0.02:
            bullets.append(
                f"🔴 **Term structure backwardated** ({fmt_vol(m.term_slope)}) — front-end vol "
                f"bid above 30D. Acute stress / vol spike in progress. *Avoid being short premium; "
                f"long-vol structures favoured.*"
            )
        elif m.term_slope < 0:
            bullets.append(
                f"🟡 **Term structure mildly backwardated** ({fmt_vol(m.term_slope)}). Watch for "
                f"this trend deepening — it usually leads vol spikes by hours-to-days."
            )
        elif m.term_slope > 0.08:
            bullets.append(
                f"🟢 **Steep contango** ({fmt_vol(m.term_slope)}) — complacency. Premium-selling "
                f"calendars and condors structurally favoured."
            )

    # VRP
    if m.vrp_30 is not None:
        if m.vrp_30 < 0:
            bullets.append(
                f"🔴 **VRP negative** ({fmt_vol(m.vrp_30)}) — realised vol exceeds implied. "
                f"Vol is *cheap* and the market is under-pricing actual movement. "
                f"*Long-premium / long-vol setups favoured (long straddles, VIX calls).*"
            )
        elif m.vrp_30 > 0.04:
            bullets.append(
                f"🟢 **VRP rich** ({fmt_vol(m.vrp_30)}) — implied substantially over realised. "
                f"*Short-premium structures favoured (iron condors, short strangles, calendars).*"
            )

    # Skew
    if m.rr25_30d is not None:
        if m.rr25_30d > 0.10:
            bullets.append(
                f"🟢 **Heavy 25Δ put skew** ({fmt_vol(m.rr25_30d)}) — aggressive hedging, crash "
                f"priced in. *Often a contrarian bullish signal; favour selling puts or buying calls.*"
            )
        elif 0.04 < m.rr25_30d <= 0.10:
            bullets.append(
                f"🟡 **Normal put skew** ({fmt_vol(m.rr25_30d)}) — within the post-2023 SPX range "
                f"(~4–8 vol pts)."
            )
        elif m.rr25_30d < 0.02:
            bullets.append(
                f"🔴 **Skew flat** ({fmt_vol(m.rr25_30d)}) — put hedging exhausted. Often near "
                f"local tops or after capitulation. *Be alert for vol expansion.*"
            )

    # Implied move
    if m.implied_move_weekly is not None:
        upper = snap.spot * (1 + m.implied_move_weekly)
        lower = snap.spot * (1 - m.implied_move_weekly)
        bullets.append(
            f"📊 **Weekly implied range:** {lower:,.2f} — {upper:,.2f} "
            f"(±{fmt_pct(m.implied_move_weekly)} from spot)."
        )

    for b in bullets:
        st.markdown(f"- {b}")

st.markdown(
    "Use the sidebar to read the **Guide**, drill into **GEX profile**, **IV skew**, "
    "**Walls & max pain**, **Unusual activity**, or the **History** view of past snapshots."
)
