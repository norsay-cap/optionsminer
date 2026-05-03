"""DT15 backtest — calibration + hit-rate stats per methodology, plus a
head-to-head comparison view of baseline vs Enhancement B (PDV-adjusted).
"""

from __future__ import annotations

import numpy as np
import plotly.graph_objects as go
import streamlit as st

from optionsminer.analytics import dt15
from optionsminer.storage import dt15_storage
from optionsminer.storage.db import init_db
from optionsminer.ui.common import DT15_VARIANT_LABELS, dt15_variant_picker

st.set_page_config(page_title="DT15 backtest", layout="wide")
init_db()

st.markdown("## DT15 backtest — prediction vs realised")

with st.expander("**How to read this page**"):
    st.markdown(
        """
        Two methodologies are stored side-by-side:

        - **Baseline** — locked static M_up=2.27, M_dn=2.97. Original DT15 spec.
        - **Enhancement B (PDV-adjusted)** — tightened static base (1.87 / 2.57)
          plus an R1-driven dynamic widening term derived from a TSPL-weighted
          sum of the past 250 daily log returns.

        The size predictor (`range_pred`, hence `avg±`) is identical between the
        two; they differ only in the M multipliers that produce ext±. So the
        **range-prediction stats** (MAE, MAPE, bias, correlation, in-band rate)
        are essentially identical between variants — what differs is the
        **ext+/ext− touch rates**.

        Toggle the variant for the per-methodology view, or scroll to the bottom
        for a **side-by-side comparison** of both.

        **Hit-rate metrics:**
        - **In-band rate** — % of days where H≤avg+ AND L≥avg−. Should hover
          near ~68% (1σ band) over a long enough sample.
        - **Touched ext+/ext− rate** — % of days where price reached the
          extension targets. Calibration target was ~5%/5% in the original
          study; Enhancement B specifically aims to keep this ratio more stable
          across regimes by widening on trending markets.

        **Range-prediction quality (variant-independent):**
        - **MAE** — mean absolute error in points
        - **MAPE** — same as %
        - **Bias** — `mean(actual − predicted)` (positive = under-predicting)
        - **Correlation** — Pearson ρ pred vs actual

        **Bootstrap.** Use the Backfill tool below to reconstruct what each
        methodology *would have predicted* for each of the last N days. Run it
        for **both variants** to seed the comparison.
        """
    )

# ---- Variant toggle ----
variant = dt15_variant_picker()
st.caption(f"Showing: **{DT15_VARIANT_LABELS[variant]}**")

# ---- Backfill control ----
with st.expander("Bootstrap / backfill"):
    n_days = st.slider("Backfill last N trading days", 5, 90, 60, key="dt15_bf_days")
    bf_col1, bf_col2 = st.columns(2)
    with bf_col1:
        if st.button(f"Run backfill · **{DT15_VARIANT_LABELS[variant]}**"):
            with st.spinner(f"Reconstructing {n_days} days for {variant}…"):
                n = dt15_storage.backfill_from_history(days=n_days, variant=variant)
            st.success(f"Backfilled {n} historical predictions for {variant}.")
            st.rerun()
    with bf_col2:
        if st.button("Run backfill · **BOTH variants**"):
            with st.spinner(f"Reconstructing {n_days} days for both variants…"):
                n_base = dt15_storage.backfill_from_history(days=n_days, variant="baseline")
                n_eb = dt15_storage.backfill_from_history(days=n_days, variant="enh_b")
            st.success(f"Backfilled baseline={n_base} and enh_b={n_eb} predictions.")
            st.rerun()

    if st.button("Re-run settlement pass (all variants)"):
        n = dt15_storage.settle_pending()
        st.info(f"Settled {n} pending prediction(s).")
        st.rerun()

st.divider()

summary = dt15_storage.summary(variant=variant)
df = dt15_storage.to_dataframe(variant=variant)

if summary.n_total == 0:
    st.info(
        f"No **{variant}** predictions yet. Use the Backfill tool above to seed "
        f"history, or open the **DT15 levels** page to record today's prediction."
    )
    st.stop()

# ---- Top-line summary ----
st.markdown("### Summary")

c1, c2, c3, c4 = st.columns(4)
c1.metric(
    "Predictions recorded",
    f"{summary.n_total}",
    delta=f"{summary.n_settled} settled",
    help="Total rows for this variant. Settled = outcome filled.",
)
c2.metric(
    "In-band hit rate",
    f"{summary.in_band_rate*100:.1f}%" if summary.in_band_rate is not None else "—",
    help="Share of days where H–L stayed inside avg±. Calibration target ~68%.",
)
c3.metric(
    "Range MAE",
    f"{summary.range_mae:.2f}" if summary.range_mae is not None else "—",
    help="Mean absolute error of the range prediction (ES points).",
)
c4.metric(
    "Range MAPE",
    f"{summary.range_mape*100:.1f}%" if summary.range_mape is not None else "—",
    help="Mean absolute percentage error.",
)

c5, c6, c7, c8 = st.columns(4)
c5.metric(
    "Bias",
    f"{summary.range_bias:+.2f}" if summary.range_bias is not None else "—",
    help="Mean signed error (actual − predicted). Positive = under-predicting.",
)
c6.metric(
    "Correlation (pred vs actual)",
    f"{summary.range_correlation:.2f}" if summary.range_correlation is not None else "—",
    help="Pearson ρ. >0.5 = useful day-to-day variation captured.",
)
c7.metric(
    "Touched ext+",
    f"{summary.touched_ext_plus_rate*100:.1f}%" if summary.touched_ext_plus_rate is not None else "—",
    help="Share of days where High ≥ ext+. Target ~5–10%.",
)
c8.metric(
    "Touched ext−",
    f"{summary.touched_ext_minus_rate*100:.1f}%" if summary.touched_ext_minus_rate is not None else "—",
    help="Share of days where Low ≤ ext−.",
)

# ---- Time series chart ----
st.divider()
settled = df.dropna(subset=["actual_range"]).sort_values("pred_date")

if settled.empty:
    st.info("No settled predictions yet for this variant.")
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

    st.markdown("#### Where did price end up vs the predicted band?")
    counts = {
        "Above ext+": int(settled["touched_ext_plus"].fillna(0).sum()),
        "Above avg+ (not ext)": int(
            settled["high_above_avg_plus"].fillna(0).sum()
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
    st.plotly_chart(bars, width="stretch")
    st.caption(
        "Note: a single day can both 'go above avg+' and 'go below avg−' — the bars "
        "count days by their *furthest-touched* level on each side."
    )

st.divider()

# ---- Side-by-side comparison ----
st.markdown("### Head-to-head comparison · baseline vs Enhancement B")

s_baseline = dt15_storage.summary(variant="baseline")
s_enh = dt15_storage.summary(variant="enh_b")

if s_baseline.n_settled == 0 and s_enh.n_settled == 0:
    st.info(
        "No settled predictions for either variant yet. Run the **Backfill · BOTH variants** "
        "button above to seed both methodologies and unlock this comparison."
    )
else:
    def _row(label, b_val, e_val, fmt="{:.2f}"):
        bv = fmt.format(b_val) if b_val is not None else "—"
        ev = fmt.format(e_val) if e_val is not None else "—"
        return {"Metric": label, "Baseline": bv, "Enhancement B": ev}

    rows = [
        _row("Predictions settled", s_baseline.n_settled, s_enh.n_settled, "{:d}"),
        _row("In-band hit rate", s_baseline.in_band_rate, s_enh.in_band_rate, "{:.1%}"),
        _row("Touched ext+ rate", s_baseline.touched_ext_plus_rate,
             s_enh.touched_ext_plus_rate, "{:.1%}"),
        _row("Touched ext− rate", s_baseline.touched_ext_minus_rate,
             s_enh.touched_ext_minus_rate, "{:.1%}"),
        _row("Range MAE (pts)", s_baseline.range_mae, s_enh.range_mae, "{:.2f}"),
        _row("Range MAPE", s_baseline.range_mape, s_enh.range_mape, "{:.1%}"),
        _row("Range bias (pts)", s_baseline.range_bias, s_enh.range_bias, "{:+.2f}"),
        _row("Range correlation", s_baseline.range_correlation,
             s_enh.range_correlation, "{:.2f}"),
    ]
    st.dataframe(rows, width="stretch", hide_index=True)

    # Comparison ext-touch chart
    if s_baseline.touched_ext_plus_rate is not None and s_enh.touched_ext_plus_rate is not None:
        comp = go.Figure()
        comp.add_bar(
            x=["ext+", "ext−"],
            y=[s_baseline.touched_ext_plus_rate * 100,
               s_baseline.touched_ext_minus_rate * 100 if s_baseline.touched_ext_minus_rate else 0],
            name="Baseline",
            marker=dict(color="#FFD166"),
        )
        comp.add_bar(
            x=["ext+", "ext−"],
            y=[s_enh.touched_ext_plus_rate * 100,
               s_enh.touched_ext_minus_rate * 100 if s_enh.touched_ext_minus_rate else 0],
            name="Enhancement B",
            marker=dict(color="#00C49A"),
        )
        comp.add_hline(y=5, line_color="#888", line_dash="dot",
                       annotation_text="calibration target ~5%")
        comp.update_layout(
            height=320, template="plotly_dark", barmode="group",
            margin=dict(l=10, r=10, t=10, b=10),
            yaxis_title="Touch rate (%)",
            title="Extension touch-rate comparison",
        )
        st.plotly_chart(comp, width="stretch")

    st.caption(
        "Both methodologies share the same range_pred (size predictor), so MAE/MAPE/bias/"
        "correlation will be identical. The meaningful differences are in the **ext+/ext− "
        "touch rates** — Enhancement B aims for ~5% on each side regardless of regime by "
        "widening dynamically when path indicators warn of trending markets."
    )

st.divider()
st.markdown("### Recent predictions")

show_cols = [
    "pred_date", "variant", "anchor", "rm5", "range_vix", "range_pred", "pred_source",
    "m_up_used", "m_dn_used", "r1_normalized",
    "actual_range", "range_error", "inside_avg_band",
    "touched_ext_plus", "touched_ext_minus",
]
table = df[[c for c in show_cols if c in df.columns]].head(60).copy()
st.dataframe(
    table,
    width="stretch",
    hide_index=True,
    column_config={
        "anchor": st.column_config.NumberColumn(format="%.2f"),
        "rm5": st.column_config.NumberColumn(format="%.2f"),
        "range_vix": st.column_config.NumberColumn(format="%.2f"),
        "range_pred": st.column_config.NumberColumn(format="%.2f"),
        "m_up_used": st.column_config.NumberColumn(format="%.3f"),
        "m_dn_used": st.column_config.NumberColumn(format="%.3f"),
        "r1_normalized": st.column_config.NumberColumn(format="%+.2f"),
        "actual_range": st.column_config.NumberColumn(format="%.2f"),
        "range_error": st.column_config.NumberColumn(format="%+.2f"),
    },
)

# Reference dt15 module so its constants (M_UP_BASELINE, M_DN_BASELINE) appear referenced
_ = dt15.M_UP_BASELINE
