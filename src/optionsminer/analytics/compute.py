"""Aggregator: compute every DerivedMetrics field from a snapshot's chain.

Called from the ingest pipeline after persist_snapshot, so the dashboard can
load a single row instead of recomputing everything per page render.
"""

from __future__ import annotations

import logging

from sqlalchemy import select

from optionsminer.analytics import gex as gex_mod
from optionsminer.analytics import implied_move as im_mod
from optionsminer.analytics import max_pain as mp_mod
from optionsminer.analytics import pcr as pcr_mod
from optionsminer.analytics import skew as skew_mod
from optionsminer.analytics import vrp as vrp_mod
from optionsminer.analytics.loader import load_bars, load_chain
from optionsminer.config import settings
from optionsminer.storage.db import session_scope
from optionsminer.storage.models import DerivedMetrics, Snapshot

log = logging.getLogger(__name__)


def compute_and_store(snapshot_id: int) -> DerivedMetrics:
    with session_scope() as s:
        snap = s.get(Snapshot, snapshot_id)
        if snap is None:
            raise ValueError(f"Snapshot {snapshot_id} not found")
        ticker, spot = snap.ticker, snap.spot

    chain = load_chain(snapshot_id)

    # GEX profile (with zero-gamma flip + walls)
    profile = gex_mod.compute_profile(
        chain,
        spot,
        r=settings.risk_free_rate,
        q=settings.div_yield_for(ticker),
    )

    # Skew @ 30D + term structure
    sk30 = skew_mod.skew_for_expiry(chain, spot, target_dte=30)
    term = skew_mod.term_structure(chain, spot)
    slope = skew_mod.term_slope(term, short_dte=7, long_dte=30) if not term.empty else None

    def atm_at(target: int) -> float | None:
        if term.empty:
            return None
        i = (term["dte"] - target).abs().idxmin()
        return float(term.iloc[i]["atm_iv"])

    # Max pain (soonest expiry)
    mp_strike, _ = mp_mod.max_pain(chain)

    # Put/call ratio
    pcr = pcr_mod.put_call_ratio(chain, min_dte=7)

    # Implied move (weekly)
    im = im_mod.implied_move(chain, spot, target_dte=7)

    # VRP
    bars = load_bars(ticker, lookback_days=90)
    iv30 = atm_at(30)
    vrp = vrp_mod.compute_vrp(bars, iv30)

    metrics = DerivedMetrics(
        snapshot_id=snapshot_id,
        total_gex=profile.total_gex,
        zero_gamma=profile.zero_gamma,
        call_wall=profile.call_wall,
        put_wall=profile.put_wall,
        max_pain_30d=mp_strike,
        rr25_30d=sk30.rr_25d if sk30 else None,
        skew_90_110_30d=sk30.skew_90_110 if sk30 else None,
        atm_iv_7=atm_at(7),
        atm_iv_30=iv30,
        atm_iv_90=atm_at(90),
        term_slope=slope,
        pcr_vol=pcr.pcr_volume,
        pcr_oi=pcr.pcr_oi,
        rv_yz_21=vrp.rv_yang_zhang,
        vrp_30=vrp.vrp,
        implied_move_weekly=im.em_pct_straddle if im else None,
    )

    with session_scope() as s:
        existing = s.get(DerivedMetrics, snapshot_id)
        if existing is not None:
            s.delete(existing)
            s.flush()
        s.add(metrics)

    return metrics
