"""User guide — how to read every signal in the dashboard.

Numbered `0_` so it appears first in the sidebar (right under the home page),
making it easy for new users to discover. Pure-markdown page, no live data.
"""

from __future__ import annotations

import streamlit as st

st.set_page_config(page_title="Guide", layout="wide")

st.markdown("# How to use optionsminer")

st.caption(
    "Reference guide for every signal on the dashboard — what it means, "
    "what numbers to look for, and how to act on them."
)

st.info(
    "**Quickest path:** the home page already prints a *Regime read* — "
    "2–5 plain-English bullets summarising today's setup. The other pages "
    "let you drill in. Hover the **❔** next to any metric for a one-line tooltip."
)

with st.expander("**Quick start** — what to look at, in what order", expanded=True):
    st.markdown(
        """
        1. **Home page → Regime read.** Plain-English summary of where dealers are positioned,
           whether vol is rich or cheap, and the current term-structure regime.
        2. **GEX profile.** The single most actionable view. Shows where dealer hedging will
           push price. Above the *zero-gamma flip* = vol-suppression regime (sell rallies, buy
           dips, chop). Below = vol-expansion regime (trend days, momentum).
        3. **Walls & Max pain.** Use as confluence levels for support/resistance and intraday pins.
        4. **IV skew.** Crash-fear gauge. Steep put skew + low ATM IV = "crash hedged, drift up".
        5. **Unusual activity.** Where the volume is *today* relative to existing OI.
        6. **History.** Once you have a few weeks of snapshots, this is where regime changes
           become visible. Look for: VRP turning negative, term structure flipping into
           backwardation, GEX dropping below zero — all early warning signs.
        """
    )

st.markdown("## The signals")

with st.expander("**Gamma Exposure (GEX) and the zero-gamma flip**"):
    st.markdown(
        """
        **What it is.** GEX measures how much **dealer delta** must be re-hedged for every 1%
        move in spot. The standard practitioner convention assumes dealers are *long calls*
        (overwriters, public buys puts) and *short puts* (insurance writers).

        **Per-strike formula:** `GEX = sign · gamma · OI · 100 · spot² · 0.01` (sign = +1 for
        calls, −1 for puts under the standard convention). The dashboard sums this across all
        strikes and expiries (default: max 60 DTE, 0DTE excluded).

        **What the value means.**
        - **Positive total GEX** → dealers are net-long gamma → they sell into rallies and
          buy into dips. Result: vol suppression, mean-reversion, choppy ranges.
        - **Negative total GEX** → dealers are net-short gamma → they chase moves
          (buy higher / sell lower). Result: trend days, momentum extension, expanded ranges.
        - **Magnitude scale (SPX):** above $5B/1% is meaningfully positive, below −$5B/1% is
          meaningfully negative. Anything in between is the messy middle.

        **Zero-gamma flip.** The hypothetical spot price at which Σ GEX = 0. This is the
        regime boundary — when spot crosses below it, dealer behaviour flips from suppressing
        vol to amplifying it. Treat it like a regime line on your chart.

        **How to act.**
        - **Spot well above flip + positive GEX:** favour premium-selling structures
          (iron condors, short strangles) and fade extreme intraday moves.
        - **Spot below flip + negative GEX:** favour directional and momentum trades; be
          careful selling premium because realised vol can blow out.
        - **Spot near flip:** transitional zone — reduce position size, watch for the cross.

        **Common pitfalls.**
        - 0DTE GEX from yfinance is unreliable (OI is yesterday's close). The dashboard
          excludes 0DTE by default for this reason.
        - GEX assumes a fixed flow direction. In reality some strikes are dealer-short
          (heavy retail call buying), which inverts the sign. Daily aggregate is still useful;
          per-strike interpretation needs care.
        """
    )

with st.expander("**IV Skew (25Δ Risk Reversal, 90/110 moneyness)**"):
    st.markdown(
        """
        **What it is.** The shape of implied vol across strikes for a single expiry. Equity
        indices show a permanent **put skew** — OTM puts trade at higher IV than OTM calls
        because of insurance demand.

        **Metrics on the dashboard.**
        - **25Δ Risk Reversal (RR25)** = `IV(25-delta put) − IV(25-delta call)`. Positive ⇒ put
          skew (the normal state). Higher = more crash fear priced in.
        - **Skew 90/110** = `IV(K = 0.9·spot) − IV(K = 1.1·spot)`. Same direction, but
          moneyness-anchored — cleaner for short-dated where delta moves fast.

        **What the value means.**
        - **RR25 ≈ 4–8 vol pts** is the normal post-2023 SPX/SPY range. Skew is structurally
          lower than pre-2020 (overwriter ETF supply: JEPI/JEPQ/SPYI dampens it).
        - **RR25 > 10 vol pts** = aggressive hedging, "crash priced in" — historically a
          contrarian bullish signal.
        - **RR25 < 2 vol pts** = put skew flattening, hedging exhausted — often near local
          tops or after capitulation lows where puts no longer bid.

        **How to act.**
        - **Steep put skew + low ATM IV:** "crash hedged, drift up" regime. Favour selling
          puts, call spreads, or buying calls outright.
        - **Skew flattening during a selloff:** capitulation signal — start scaling in long.
        - **Skew expanding from already-rich levels:** real risk-off, reduce exposure.

        **Pitfalls.**
        - Skew of weekly/0DTE expiries is dominated by flow and gamma positioning, not fear.
          Don't compare a 1-day RR25 to a 30-day RR25.
        - When ATM IV spikes, skew mechanically appears to flatten because the absolute
          IV-difference shrinks relative to the level. Use the History page to compare to
          recent levels rather than absolutes.
        """
    )

with st.expander("**IV Term Structure & Term Slope**"):
    st.markdown(
        """
        **What it is.** ATM implied vol plotted across expiries (7D, 30D, 90D, …). The shape
        tells you how the market expects vol to evolve.

        **Term Slope** = `IV(30D) / IV(7D) − 1`.
        - **Positive (contango)** = normal — longer-dated vol higher than front. Above +5%
          = complacency.
        - **Negative (backwardation)** = front-end vol higher than 30D — acute stress, vol
          spike in progress. **Historically the strongest VRP edge.**

        **How to act.**
        - **Steep contango** + positive GEX = textbook premium-selling regime. Calendars,
          iron condors, short strangles all work.
        - **Backwardation** = the market is pricing imminent volatility. Avoid being short
          premium. If you're already long premium, this is when you collect.
        - **Term slope flipping from positive to negative** is an early-warning signal that
          shows up before the VIX spike makes the news.

        **Best confirmation:** combine with VRP. Backwardated *and* VRP < 0 = vol is cheap
        AND about to expand. Long-vol setup.
        """
    )

with st.expander("**Volatility Risk Premium (VRP)**"):
    st.markdown(
        """
        **What it is.** `VRP = IV30 − RV21` (Yang-Zhang realised vol). The "insurance
        premium" baked into options. Persistently positive on equity indices because of
        structural hedging demand.

        **What the value means.**
        - **VRP ≈ +2 to +4 vol pts** is the modern (post-2023) normal range. Below the
          pre-2020 average because 0DTE supply has crushed premia.
        - **VRP > +5 vol pts** = vol is rich → favour short-premium structures.
        - **VRP < 0** = realised vol is *higher* than implied → vol is cheap → favour
          long-premium / long-vol structures. Rare but valuable.
        - **VRP turning negative in a market that's been trending up** is one of the
          best long-vol setups (e.g. early 2018, mid-2021).

        **How to compute (the dashboard handles this).** Realised vol uses **Yang-Zhang**
        (drift-independent and gap-aware) over a 21-day window. Compared to ATM IV at 30 days.

        **Pitfalls.**
        - Single-day VRP is noisy. Use the History page to look at 5- and 21-day averages.
        - After a vol spike, VRP can stay positive even as IV crashes — the realised has
          to catch up first.
        """
    )

with st.expander("**Open-Interest Walls (Gamma-weighted)**"):
    st.markdown(
        """
        **What it is.** The strikes where dealer gamma exposure is most concentrated.
        Ranked by `|gamma · OI|` rather than raw OI — because OI at far-OTM strikes barely
        affects dealer hedging.

        **What the value means.** Walls act as soft support/resistance:
        - **Call wall above spot:** strong resistance — dealers must sell delta as price
          approaches it.
        - **Put wall below spot:** strong support — dealers must buy delta as price
          approaches it.
        - The dashboard shows the top-N walls within a configurable band around spot.

        **How to act.**
        - **Range-trade between the dominant call wall and put wall** when GEX is positive
          (vol suppression).
        - **A break of a major wall** in negative-GEX regimes often triggers acceleration
          (dealers now have to chase rather than fade).
        - **Watch for fresh OI builds** on the History page — a *new* wall appearing is
          a stronger signal than a wall that's been there for weeks.
        """
    )

with st.expander("**Max Pain**"):
    st.markdown(
        """
        **What it is.** The strike at which the total payout to options writers is minimised
        (i.e. options buyers, in aggregate, lose the most). Computed for the soonest expiry
        on the dashboard.

        **Verdict.** Mostly folklore on its own. Academic studies show a weak pin effect on
        monthly OPEX days within ~0.5%. For weeklies and 0DTE, "pinning" comes from dealer
        gamma, not from max pain — they often coincide simply because OI builds at high-gamma
        strikes.

        **How to use it.** Treat max pain as a **confluence indicator**. When max pain ==
        zero-gamma flip == dominant gamma wall, the level is real. When max pain disagrees
        with the GEX profile, trust the GEX profile.
        """
    )

with st.expander("**Put/Call Ratio (PCR)**"):
    st.markdown(
        """
        **What it is.** `Σ put volume / Σ call volume` (and the equivalent for OI). Filtered
        to DTE ≥ 7 to remove the 0DTE retail-gambling distortion.

        **CRITICAL — index vs equity interpretation differs.**
        - **Equity-only PCR** is **contrarian** (extremes flag panic bottoms or euphoric tops).
        - **Index PCR (SPX/SPY)** is **NOT contrarian** — institutions buy index puts to hedge
          long stock positions. High index PCR usually means "long & hedged" (bullish
          positioning), not bearish.

        Since this dashboard tracks SPX/SPY, you're seeing **index PCR**. Read it as a
        **positioning indicator**, not a sentiment one:
        - Rising PCR + falling spot = real risk-off, hedges working.
        - Rising PCR + rising spot = institutions adding hedges into strength (typical).
        - Falling PCR into a top = hedges being lifted (bearish — the safety net is going away).

        **Don't chase the ratio in isolation.** Pair it with VRP and skew for context.
        """
    )

with st.expander("**Implied Move (weekly straddle)**"):
    st.markdown(
        """
        **What it is.** The 1-σ expected move into expiry, derived from the ATM straddle:
        `EM ≈ 0.85 · (ATM call mid + ATM put mid)`.

        **What it gives you.** A market-implied "expected range" — useful as Bollinger-style
        bands for swing trading.

        **How to act.**
        - **You expect a smaller move than implied** → sell the straddle / strangle / iron condor.
        - **You expect a larger move than implied** → buy the straddle / wide strangle.
        - **Spot trades through the upper or lower bound** mid-week → a meaningful regime
          event has occurred (don't fade it without other confirmation).
        """
    )

with st.expander("**Unusual Options Activity (UOA)**"):
    st.markdown(
        """
        **What this dashboard can detect** (yfinance EOD-snapshot constraints):
        - Strikes where today's volume exceeds open interest (`vol/OI > 0.5`)
        - Big absolute volume (default ≥ 500 contracts)
        - Notional dollar size (default ≥ $250k)
        - Out-of-the-money (default |moneyness| ≥ 2%)
        - DTE between 7 and 60 (filters expiry rolls and noise)

        **What this dashboard CANNOT detect** (needs trade tape, not yfinance):
        - Sweeps (a single buyer hitting multiple exchanges simultaneously)
        - Block prints (off-exchange large trades)
        - Aggressor classification (was it a buy or a sell?)

        **How to act on a UOA hit.**
        - A new big block at a strike you haven't seen before, *combined with* a fresh OI
          build (visible the next day), is the strongest signal.
        - Single-snapshot UOA in isolation is noise more often than signal — wait for
          repeat activity at the same strike to mean something.
        """
    )

with st.expander("**DT15 daily range (ES futures)**"):
    st.markdown(
        f"""
        **What it is.** A predictive estimate of today's intraday range for ES futures,
        derived from a blend of recent realised range and the VIX-implied move. Projects
        four anchored levels around the session open: **avg+**, **avg−**, **ext+**, **ext−**.

        **Computation.**
        - `RM5` = simple 5-day average of daily High − Low.
        - `range_vix` = `K_BM · σ_VIX · prior_close`, where `K_BM = √(8/π)` is the Brownian-
          motion expected absolute move and `σ_VIX = (VIX/100)/√252` is per-day vol.
        - `range_pred = max(RM5, 0.60 · range_vix)` — realised dominates unless VIX is bid.
        - `avg± = O_t ± 0.5 · range_pred`
        - `ext+ = O_t + 0.5 · range_pred · 2.27`
        - `ext− = O_t − 0.5 · range_pred · 2.97` (asymmetric — downside fatter, locked from study)

        **Anchor.** Defaults to yfinance's daily Open (= 6 PM ET ETH session start).
        Override with the actual 9:30 AM ET RTH first-trade for a tighter intraday read.

        **How to act.**
        - **avg+/avg−** are initial reaction targets — common turn levels in a normal session.
        - **ext+/ext−** are extension targets — *reaching them is a trend-day signal*. Fade
          with care; the market is in expansion mode.
        - **range_pred well below RM5** = market quieter than recent average. Confluence with
          high VRP (rich premium) = good iron-condor day.
        - **range_pred dominated by the VIX side** = market pricing more vol than has
          materialised. Watch for catch-up.
        """
    )

with st.expander("**DT15 methodologies — Baseline vs Enhancement B**"):
    st.markdown(
        """
        Two methodologies are tracked side-by-side; toggle between them on the
        **DT15 levels** and **DT15 backtest** pages.

        **Baseline (locked static M).** The original DT15 spec.
        - `M_up = 2.27`, `M_dn = 2.97` (calibrated on 2018–2022 IS for ~5%/5% breach rates)
        - Constants do NOT vary with market state
        - Simple, transparent — but poorly calibrated in trending regimes (ext-touches
          cluster on the trend side and become rare on the opposite side)

        **Enhancement B (PDV-adjusted, R1-dynamic M).** Tightened static base + dynamic
        widening from a Path-Dependent-Volatility indicator.
        - Tightened base: `M_up_base = 1.87`, `M_dn_base = 2.57`
        - Dynamic widening: `M_up = 1.87 · (1 + 1.59 · max(0, R1/σ_R1))`, mirror for `M_dn`
        - **R1** is a TSPL-weighted sum of the past 250 daily log returns
          (Guyon-Lekeufack VIX-style kernel: α=1.06, δ=0.020, σ_R1=0.00142)
        - **Intuition:** when R1 is positive (recent up-trend) the upside extension widens
          to absorb continuation; when R1 is negative (recent down-trend) the downside
          extension widens. Symmetric and mechanical — no discretion.
        - Calibrated 2018–2022 IS, validated 2023–2025 OOS for more stable breach rates
          across regimes (~5%/5% target on both sides)

        **Same size predictor for both.** Both methodologies use
        `range_pred = max(RM5, 0.60 · range_vix)`, so they produce **identical** avg± bands
        and identical range MAE/MAPE/bias/correlation. They differ only in the **M
        multipliers that produce ext±**, so the meaningful comparison is in the
        ext+/ext− touch rates — see the Backtest page's head-to-head table.

        **Which to use.** Enhancement B is the recommended default for breach-rate
        calibration. Baseline is useful as a sanity check, and is the simpler model to
        explain to anyone unfamiliar with PDV. Toggle between them and look at your own
        backtest to decide.
        """
    )

with st.expander("**DT15 Backtest — measuring the model**"):
    st.markdown(
        """
        Every DT15 prediction is recorded to the database the moment the **DT15 levels**
        page is opened (or by the daily scheduler — whichever fires first). The next time
        the page loads, any past-dated prediction is **settled** against the actual ES
        daily High/Low/Close pulled from yfinance.

        **Stats the Backtest page tracks:**

        | Metric | What it tells you |
        |---|---|
        | **In-band hit rate** | % of days price stayed inside `avg±`. Calibration target ~68%. |
        | **Touched ext+/ext− rate** | Frequency of tail-end touches. |
        | **Range MAE / MAPE** | How far off the range estimate is on average. |
        | **Bias** | Mean signed error — does the model systematically under- or over-predict? |
        | **Correlation** | Pearson ρ between predicted and realised range. |
        | **Calibration scatter** | Visual check of pred-vs-actual; perfect = points on y=x. |
        | **Error histogram** | Distribution of `actual − predicted`; should be roughly centred and symmetric. |

        **Bootstrap.** Tracking from forward-only data takes weeks. The Backtest page has a
        **"Backfill last N days"** button that reconstructs what DT15 *would have predicted*
        on each of the last N days (using only the data available at that time) and settles
        them against the actual outcomes — instantly seeds the analysis.
        """
    )

with st.expander("**Greeks (delta, gamma, vega, theta, charm, vanna)**"):
    st.markdown(
        """
        Computed per-strike using Black-Scholes with continuous dividend yield (1.3% for
        SPY/SPX). IV is *recomputed* from the mid quote (yfinance's own IV field is
        unreliable on illiquid wings).

        **The standard four:**
        - **Delta** — directional exposure. Roughly the probability the option ends ITM.
        - **Gamma** — second derivative. How fast delta changes with spot.
        - **Vega** — sensitivity to a 1.00 vol move.
        - **Theta** — time decay (per year — divide by 365 for per-calendar-day).

        **The two that drive intraday flows:**
        - **Charm** (`∂Δ/∂t`) — the rate at which delta decays as time passes. The mechanical
          driver of EOD pinning behaviour: as 0DTE options approach expiry, dealers' delta
          hedges decay rapidly, forcing flows that pin spot to the highest-OI strike.
        - **Vanna** (`∂Δ/∂σ` = `∂Vega/∂S`) — the cross-sensitivity. Drives "vol-crush rallies":
          when morning IV is bid then crushes by midday, dealers short-gamma/long-vega get
          squeezed into buying.
        """
    )

st.markdown("## Common regime patterns")

with st.expander("**Pattern A — Premium-seller's paradise**"):
    st.markdown(
        """
        - Total GEX strongly positive (>$5B / 1%)
        - Spot well above zero-gamma flip
        - Term structure in steep contango (slope > +5%)
        - VRP > +4 vol pts
        - Skew rich but not extreme

        **Trade idea:** sell premium. Iron condors, short strangles, calendars. Stay
        delta-neutral. The dealer hedging environment will fade extreme intraday moves
        for you.
        """
    )

with st.expander("**Pattern B — Long-vol setup**"):
    st.markdown(
        """
        - VRP turning negative or already negative
        - Term structure flattening or backwardated
        - Total GEX dropping toward zero or already negative
        - Skew expanding from already-elevated levels

        **Trade idea:** buy premium. Long straddles or VIX calls. The market is pricing
        vol cheaper than what's actually happening, AND dealer flows are about to amplify
        moves rather than dampen them.
        """
    )

with st.expander("**Pattern C — Capitulation washout**"):
    st.markdown(
        """
        - VIX spike, term structure deeply backwardated
        - GEX deeply negative
        - Skew **flattening during the selloff** (the giveaway — puts no longer bid)
        - PCR extremely high

        **Trade idea:** scale into long. The dealer-amplified selloff is exhausting itself.
        Use defined-risk structures (long call spreads) until vol crushes; don't sell naked
        puts into still-falling knives.
        """
    )

st.markdown("## Data caveats and maintenance")

with st.expander("**yfinance data quality — what to trust and what not to**"):
    st.markdown(
        """
        | Reliable | Unreliable / Not Available |
        |---|---|
        | EOD chains for SPX/SPY | Intraday tick data |
        | Strike, expiry, OI (yesterday's close) | Today's intraday OI |
        | Bid/ask mid for liquid strikes | Bid/ask for far-OTM wings (often stale) |
        | EOD volume per contract | Trade-by-trade tape, sweeps, blocks |
        | Last trade date (use to filter staleness) | Aggressor classification (buy vs sell) |

        The app:
        - Drops rows with bid/ask of zero
        - Recomputes IV from mid (Yahoo's own IV is inconsistent)
        - Excludes 0DTE from default GEX (because OI is yesterday's stale value)
        - Falls back to provider IV only when our own IV solver fails on illiquid wings
        """
    )

with st.expander("**Maintenance — disk usage, snapshots, Coolify**"):
    st.markdown(
        """
        - **Disk usage** is shown in the sidebar. The app auto-prunes the oldest snapshots
          when usage exceeds the configured cap (default 150 GB). Warning at 80%.
        - **Snapshot schedule:** the in-container scheduler runs at `15 21 * * 1-5` UTC by
          default = ~4:15 PM ET on US trading days. Override with the
          `OPTIONSMINER_SCHEDULE_CRON` env var.
        - **Manual snapshot:** Admin page → "Take snapshot now". Use this whenever you want
          a mid-day reading (e.g. into FOMC, into earnings).
        - **History accumulates over time.** Day-of-week patterns become visible after
          ~3 weeks. Regime shifts are visible within days.
        """
    )

st.markdown("---")
st.caption(
    "Most of the signal interpretations on this page come from practitioner research "
    "(SqueezeMetrics, Menthor Q, SpotGamma, Bennett's *Trading Volatility*) and recent "
    "academic work on 0DTE flow (Brogaard et al. 2024). When in doubt, check the History "
    "page — most of these signals are best read as deviations from their own recent norms, "
    "not as absolute thresholds."
)
