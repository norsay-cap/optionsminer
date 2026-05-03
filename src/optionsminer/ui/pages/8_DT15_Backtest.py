"""DT15 backtest — calibration + hit-rate stats over the recorded predictions."""

from __future__ import annotations

import numpy as np
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from optionsminer.storage import dt15_storage
from optionsminer.storage.db import init_db

st.set_page_config(page_title="DT15 backtest", layout="wide")
init_db()

st.markdown("## DT15 backtest — prediction vs realised")

with st.expander("**How to read this page**"):
    st.markdown(
        """
        DT15 predictions are recorded automatically every time the **DT15 levels** page is
        opened (one row per day). The next time the page loads, any past-dated prediction
        is **settled** against the actual ES daily High/Low/Close.

        **Hit-rate metrics:**
        - **In-band rate** — % of days where the entire daily range stayed inside `avg±`.
          DT15 is calibrated so this should hover near ~68% (1σ band) over a long enough
          sample. Persistently lower = `range_pred` is under-estimating.
        - **Touched ext+/ext− rate** — % of days where price reached the extension targets.
          `M_dn = 2.97` > `M_up = 2.27` reflects the index downside fat-tail; expect ext−
          touches to be slightly more frequent than ext+.

        **Range-prediction quality:**
        - **MAE** (mean absolute error, in points) — how far off the range estimate is on average.
        - **MAPE** (% error) — same as MAE but normalised.
        - **Bias** — mean signed error (`actual − predicted`). Positive = model under-predicts,
          negative = over-predicts. Should be close to 0 over a stable regime.
        - **Correlation** — Pearson ρ of predicted vs actual range. >0.5 = useful;
          <0.3 = the model is mostly capturing the regime mean, not day-to-day variation.

        **Bootstrap historical data.** Tracking from live forward-only data takes weeks.
        Use the "Backfill last N days" tool below to reconstruct what the model would have
        predicted on each of the last N days using only the data available at the time —
        instantly seeds the backtest.
        """
    )

# ---- Backfill control ----
with st.expander("Bootstrap / backfill"):
    n_days = st.slider("Backfill last N trading days", 5, 90, 30, key="dt15_bf_days")
    if st.button("Run backfill"):
        with st.spinner(f"Reconstructing {n_days} days of DT15 predictions…"):
            n = dt15_storage.backfill_from_history(days=n_days)
        st.success(f"Backfilled {n} historical predictions and settled them.")
        st.rerun()

    if st.button("Re-run settlement pass"):
        n = dt15_storage.settle_pending()
        st.info(f"Settled {n} pending prediction(s).")
        st.rerun()

st.divider()

summary = dt15_storage.summary()
df = dt15_storage.to_dataframe()

if summary.n_total == 0:
    st.info(
        "No predictions recorded yet. Open the **DT15 levels** page to record today's "
        "prediction, or use the Backfill tool above to bootstrap history."
    )
    st.stop()

# ---- Top-line summary ----
st.markdown("### Summary")

c1, c2, c3, c4 = st.columns(4)
c1.metric(
    "Predictions recorded",
    f"{summary.n_total}",
    delta=f"{summary.n_settled} settled",
    help="Total rows in the DT15 prediction table. Settled = outcome filled in.",
)
c2.metric(
    "In-band hit rate",
    f"{summary.in_band_rate*100:.1f}%" if summary.in_band_rate is not None else "—",
    help="Share of settled days where the entire H–L stayed inside avg±. "
    "Calibration target: ~68% over a stable regime.",
)
c3.metric(
    "Range MAE",
    f"{summary.range_mae:.2f}" if summary.range_mae is not None else "—",
    help="Mean absolute error of the range prediction (ES points).",
)
c4.metric(
    "Range MAPE",
    f"{summary.range_mape*100:.1f}%" if summary.range_mape is not None else "—",
    help="Mean absolute percentage error of the range prediction.",
)

c5, c6, c7, c8 = st.columns(4)
c5.metric(
    "Bias",
    f"{summary.range_bias:+.2f}" if summary.range_bias is not None else "—",
    help="Mean signed error (actual − predicted). Positive = under-predicting; "
    "negative = over-predicting. Should be ~0 in a stable regime.",
)
c6.metric(
    "Correlation (pred vs actual)",
    f"{summary.range_correlation:.2f}" if summary.range_correlation is not None else "—",
    help="Pearson ρ. >0.5 = useful day-to-day variation captured.",
)
c7.metric(
    "Touched ext+",
    f"{summary.touched_ext_plus_rate*100:.1f}%" if summary.touched_ext_plus_rate is not None else "—",
    help="Share of settled days where High >= ext+. Expected to be small (~5-10%).",
)
c8.metric(
    "Touched ext−",
    f"{summary.touched_ext_minus_rate*100:.1f}%" if summary.touched_ext_minus_rate is not None else "—",
    help="Share of settled days where Low <= ext−. Typically slightly higher than ext+ "
    "due to M_dn > M_up.",
)

# ---- Time series chart ----
st.divider()
settled = df.dropna(subset=["actual_range"]).sort_values("pred_date")

if settled.empty:
    st.info("No settled predictions yet. Outcomes will fill in once historical days have closed.")
else:
    st.markdown("### Predicted vs realised range")
    fig = go.Figure()
    fig.add_scatter(x=settled["pred_date"], y=settled["range_pred"], name="Predicted",
                    line=dict(color="#FFD166"))
    fig.add_scatter(x=settled["pred_date"], y=settled["actual_range"], name="Realised",
                    line=dict(color="#00C49A"))
    fig.update_layout(
        height=320, template="plotly_dark", margin=dict(l=10, r=10, t=10, b=10),
        xaxis_title="Date", yaxis_title="ES range (points)",
    )
    st.plotly_chart(fig, width="stretch")

    # ---- Calibration scatter + error histogram ----
    left, right = st.columns(2)
    with left:
        st.markdown("#### Calibration scatter")
        max_v = float(max(settled["range_pred"].max(), settled["actual_range"].max()))
        cal = go.Figure()
        cal.add_scatter(
            x=settled["range_pred"], y=settled["actual_range"], mode="markers",
            marker=dict(color="#00C49A", size=8),
            text=[d.isoformat() for d in settled["pred_date"]],
            hovertemplate="<b>%{text}</b><br>pred=%{x:.2f}<br>actual=%{y:.2f}<extra></extra>",
            name="Days",
        )
        cal.add_scatter(x=[0, max_v], y=[0, max_v], mode="lines",
                        line=dict(color="#888", dash="dash"), name="Perfect (y=x)")
        cal.update_layout(
            height=380, template="plotly_dark", margin=dict(l=10, r=10, t=10, b=10),
            xaxis_title="Predicted range", yaxis_title="Actual range",
        )
        st.plotly_chart(cal, width="stretch")

    with right:
        st.markdown("#### Range error distribution")
        errs = settled["range_error"].dropna().tolist()
        if errs:
            hist = go.Figure()
            hist.add_histogram(x=errs, marker=dict(color="#118AB2"), nbinsx=20)
            hist.add_vline(x=0, line_color="#FFFFFF", line_dash="dash",
                           annotation_text="zero error")
            hist.add_vline(x=float(np.mean(errs)), line_color="#FFD166",
                           annotation_text=f"mean {np.mean(errs):+.2f}")
            hist.update_layout(
                height=380, template="plotly_dark", margin=dict(l=10, r=10, t=10, b=10),
                xaxis_title="Actual − Predicted (points)", yaxis_title="Count",
            )
            st.plotly_chart(hist, width="stretch")

    # ---- Hit-rate breakdown ----
    st.markdown("#### Where did price end up vs the predicted band?")
    counts = {
        "Above ext+": int(settled["touched_ext_plus"].fillna(0).sum()),
        "Above avg+ (not ext)": int(
            (settled["high_above_avg_plus"].fillna(0).sum())
            - settled["touched_ext_plus"].fillna(0).sum()
        ),
        "Inside avg band": int(settled["inside_avg_band"].fillna(0).sum()),
        "Below avg− (not ext)": int(
            settled["low_below_avg_minus"].fillna(0).sum()
            - settled["touched_ext_minus"].fillna(0).sum()
        ),
        "Below ext−": int(settled["touched_ext_minus"].fillna(0).sum()),
    }
    total = sum(counts.values())
    bars = go.Figure()
    bars.add_bar(
        x=list(counts.keys()),
        y=list(counts.values()),
        marker=dict(color=["#FFD166", "#00C49A", "#118AB2", "#FF8A5C", "#FF6B6B"]),
        text=[f"{v} ({v/max(total,1)*100:.0f}%)" for v in counts.values()],
        textposition="auto",
    )
    bars.update_layout(
        height=320, template="plotly_dark", margin=dict(l=10, r=10, t=10, b=10),
        yaxis_title="Days", showlegend=False,
    )
    # Note that the "above avg+" / "below avg-" bars include their respective ext touches
    # too — the breakdown above subtracts them out for a clean partition.
    st.plotly_chart(bars, width="stretch")
    st.caption(
        "Note: a single day can both 'go above avg+' and 'go below avg−' — the above bars "
        "count days by their *furthest-touched* level on each side; pure inside-band "
        "days have neither boundary breached."
    )

st.divider()
st.markdown("### Recent predictions")

show_cols = [
    "pred_date", "anchor", "anchor_source", "rm5", "range_vix", "range_pred", "pred_source",
    "actual_range", "range_error", "inside_avg_band",
    "touched_ext_plus", "touched_ext_minus",
]
table = df[show_cols].head(60).copy()
st.dataframe(
    table,
    width="stretch",
    hide_index=True,
    column_config={
        "anchor": st.column_config.NumberColumn(format="%.2f"),
        "rm5": st.column_config.NumberColumn(format="%.2f"),
        "range_vix": st.column_config.NumberColumn(format="%.2f"),
        "range_pred": st.column_config.NumberColumn(format="%.2f"),
        "actual_range": st.column_config.NumberColumn(format="%.2f"),
        "range_error": st.column_config.NumberColumn(format="%+.2f"),
    },
)
