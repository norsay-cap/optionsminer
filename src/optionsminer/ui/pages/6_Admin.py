"""Admin: storage report, manual snapshot trigger, manual prune."""

from __future__ import annotations

import streamlit as st
from sqlalchemy import func, select

from optionsminer.config import settings
from optionsminer.providers.ingest import run_snapshot
from optionsminer.providers.yahoo import YahooProvider
from optionsminer.storage import disk_guard
from optionsminer.storage.db import session_scope
from optionsminer.storage.models import OptionQuote, Snapshot, UnderlyingBar
from optionsminer.ui.common import page_header

st.set_page_config(page_title="Admin", layout="wide")
page_header("Admin", "Storage, snapshots, maintenance")

with st.expander("**What this page does**"):
    st.markdown(
        """
        - **Storage panel:** real-time disk usage of the SQLite DB vs your configured cap
          (default 150 GB). Auto-prune triggers when usage exceeds the cap.
        - **By ticker:** how many snapshots you've collected per ticker, and the date range.
        - **Manual snapshot:** force a fresh chain pull right now. Use this when you want a
          mid-day reading (e.g. into an FOMC release or a major earnings event), or to
          backfill a missed scheduled run.
        - **Disk maintenance:** force a prune of the oldest snapshots if the auto-prune
          hasn't kicked in or you want to free space proactively.

        **Daily auto-snapshots** run inside the container at 21:15 UTC weekdays
        (~4:15 PM ET) via the in-process scheduler — no manual action needed for the
        regular cadence.
        """
    )

rep = disk_guard.report()
state_color = {"OK": "#00C49A", "WARN": "#FFD166", "OVER": "#FF6B6B"}[rep.state]

c1, c2, c3, c4 = st.columns(4)
c1.metric("DB usage", f"{rep.used_gb:.3f} GB")
c2.metric("Cap", f"{rep.cap_gb:.0f} GB")
c3.metric("Used %", f"{rep.used_pct*100:.1f}%")
c4.markdown(f"### State <span style='color:{state_color}'>{rep.state}</span>",
            unsafe_allow_html=True)

with session_scope() as s:
    n_snap = s.scalar(select(func.count(Snapshot.snapshot_id)))
    n_q = s.scalar(select(func.count()).select_from(OptionQuote))
    n_bars = s.scalar(select(func.count()).select_from(UnderlyingBar))
    by_ticker = s.execute(
        select(Snapshot.ticker, func.count(Snapshot.snapshot_id),
               func.min(Snapshot.snapshot_ts), func.max(Snapshot.snapshot_ts))
        .group_by(Snapshot.ticker)
    ).all()

c5, c6, c7 = st.columns(3)
c5.metric("Snapshots", f"{n_snap:,}")
c6.metric("Option quotes", f"{n_q:,}")
c7.metric("Underlying bars", f"{n_bars:,}")

if by_ticker:
    st.markdown("#### By ticker")
    st.dataframe(
        [{"ticker": t, "snapshots": c, "first": str(a), "last": str(b)}
         for t, c, a, b in by_ticker],
        width='stretch',
        hide_index=True,
    )

st.divider()
st.markdown("#### Manual snapshot")
sel_tickers = st.multiselect("Tickers", options=settings.tickers, default=settings.tickers)
max_dte = st.number_input("Max DTE", min_value=7, max_value=365, value=settings.snapshot_max_dte)

if st.button("Take snapshot now", type="primary"):
    if not sel_tickers:
        st.error("Choose at least one ticker.")
    else:
        prog = st.empty()
        provider = YahooProvider()
        for tk in sel_tickers:
            prog.info(f"Fetching {tk} chain (max DTE={max_dte})…")
            try:
                res = run_snapshot(provider, tk)
                st.success(
                    f"{tk}: snapshot_id={res['snapshot_id']} spot={res['spot']:.2f} "
                    f"quotes={res['n_quotes']} bars={res['n_bars_upserted']}"
                )
            except Exception as e:  # noqa: BLE001
                st.error(f"{tk} failed: {e}")
        prog.empty()
        st.rerun()

st.divider()
st.markdown("#### Disk maintenance")
if rep.state == "OVER":
    st.error(
        f"Usage {rep.used_gb:.2f} GB exceeds cap {rep.cap_gb:.0f} GB. "
        "Run a prune to drop oldest snapshots."
    )
elif rep.state == "WARN":
    st.warning(
        f"Usage {rep.used_gb:.2f} GB at {rep.used_pct*100:.0f}% of cap. "
        "Plan to prune soon or raise the cap."
    )
else:
    st.success("Plenty of headroom.")

if st.button("Prune oldest now"):
    n_deleted = disk_guard.prune_oldest()
    st.info(f"Deleted {n_deleted} oldest snapshot(s).")
    st.rerun()
