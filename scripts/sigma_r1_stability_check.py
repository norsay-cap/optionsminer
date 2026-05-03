"""One-off diagnostic: is sigma_R1 = 0.00142 stable across 2023-2026 regimes?

Runs locally (or anywhere with internet + the project's Python deps). Pulls
4 years of ES=F + ^VIX from yfinance, computes R1 daily for the last 3 years
using the same TSPL kernel as the app, then reports sigma broken down by year,
half-year, and VIX regime.

Not committed as part of the app — pure analysis. Run with:
    uv run python scripts/sigma_r1_stability_check.py
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import yfinance as yf

# Same constants as the live app (analytics/dt15.py)
TSPL_ALPHA = 1.06
TSPL_DELTA = 0.020
TSPL_NLAGS = 250
LOCKED_SIGMA_R1 = 0.00142


def tspl_weights(alpha: float, delta: float, n_lags: int, dt: float = 1.0 / 252) -> np.ndarray:
    z = (delta ** (1 - alpha)) / (alpha - 1)
    taus = np.arange(n_lags) * dt
    w = ((taus + delta) ** (-alpha)) / z
    return (w / (w.sum() * dt)) * dt


def main() -> None:
    print("Pulling 4y of ES=F + 4y of ^VIX from yfinance ...")
    es = yf.download("ES=F", period="4y", progress=False, auto_adjust=False)
    vix = yf.download("^VIX", period="4y", progress=False, auto_adjust=False)
    if isinstance(es.columns, pd.MultiIndex):
        es.columns = es.columns.get_level_values(0)
    if isinstance(vix.columns, pd.MultiIndex):
        vix.columns = vix.columns.get_level_values(0)

    print(f"ES bars: {len(es)} ({es.index[0].date()} -> {es.index[-1].date()})")
    print(f"VIX bars: {len(vix)} ({vix.index[0].date()} -> {vix.index[-1].date()})")

    # Daily log returns
    log_rets = np.log(es["Close"] / es["Close"].shift(1)).dropna()
    print(f"Log returns: {len(log_rets)}")

    # TSPL kernel weights (reversed: most-recent return gets the largest weight,
    # matching dt15.py's `w1[::-1]` convention)
    w = tspl_weights(TSPL_ALPHA, TSPL_DELTA, TSPL_NLAGS)[::-1]

    # Compute R1 for every date with >= 250 prior returns
    r1_vals: list[float] = []
    r1_dates: list = []
    for i in range(TSPL_NLAGS, len(log_rets)):
        past = log_rets.iloc[i - TSPL_NLAGS : i].values
        r1_vals.append(float(np.dot(w, past)))
        r1_dates.append(log_rets.index[i])

    r1 = pd.Series(r1_vals, index=pd.DatetimeIndex(r1_dates), name="r1")
    print(f"\nR1 series: {len(r1)} daily values "
          f"({r1.index[0].date()} -> {r1.index[-1].date()})")

    # Align VIX (use prior close — same convention as the model)
    vix_close = vix["Close"].reindex(r1.index, method="ffill")

    # --- Full-sample stats ---
    sigma_full = float(r1.std(ddof=1))
    mean_full = float(r1.mean())
    print("\n" + "=" * 76)
    print("FULL SAMPLE")
    print("=" * 76)
    print(f"  n              : {len(r1)} days")
    print(f"  sigma_R1 realised  : {sigma_full:.6f}")
    print(f"  sigma_R1 locked    : {LOCKED_SIGMA_R1:.6f}")
    print(f"  ratio (real/lock): {sigma_full / LOCKED_SIGMA_R1:.3f}x")
    print(f"  mean R1        : {mean_full:+.6f}")
    print(f"  R1 percentiles : p5={np.percentile(r1, 5):+.6f}  "
          f"p50={np.percentile(r1, 50):+.6f}  p95={np.percentile(r1, 95):+.6f}")

    # --- Per-year ---
    print("\n" + "=" * 76)
    print("PER YEAR")
    print("=" * 76)
    print(f"  {'year':<6} {'n':>5} {'sigma_R1':>10} {'ratio vs locked':>17} "
          f"{'mean R1':>12} {'avg VIX':>10}")
    for year, grp in r1.groupby(r1.index.year):
        s = float(grp.std(ddof=1)) if len(grp) > 1 else float("nan")
        m = float(grp.mean())
        v = float(vix_close.loc[grp.index].mean())
        print(f"  {year:<6} {len(grp):>5} {s:>10.6f} {s / LOCKED_SIGMA_R1:>15.3f}x "
              f"{m:>+12.6f} {v:>10.2f}")

    # --- Per half-year ---
    print("\n" + "=" * 76)
    print("PER HALF-YEAR")
    print("=" * 76)
    half_label = (
        r1.index.year.astype(str)
        + "-H"
        + ((r1.index.month > 6).astype(int) + 1).astype(str)
    )
    print(f"  {'half':<8} {'n':>5} {'sigma_R1':>10} {'ratio vs locked':>17} "
          f"{'mean R1':>12} {'avg VIX':>10}")
    for half, grp in r1.groupby(half_label):
        if len(grp) < 5:
            continue
        s = float(grp.std(ddof=1))
        m = float(grp.mean())
        v = float(vix_close.loc[grp.index].mean())
        print(f"  {half:<8} {len(grp):>5} {s:>10.6f} {s / LOCKED_SIGMA_R1:>15.3f}x "
              f"{m:>+12.6f} {v:>10.2f}")

    # --- By VIX regime ---
    print("\n" + "=" * 76)
    print("BY VIX REGIME (low/mid/high tercile of prior-day VIX close)")
    print("=" * 76)
    q_lo, q_hi = vix_close.quantile([1/3, 2/3])
    regime = pd.cut(
        vix_close,
        bins=[-np.inf, q_lo, q_hi, np.inf],
        labels=["low (<{:.1f})".format(q_lo),
                "mid ({:.1f}-{:.1f})".format(q_lo, q_hi),
                "high (>{:.1f})".format(q_hi)],
    )
    print(f"  {'regime':<22} {'n':>5} {'sigma_R1':>10} {'ratio vs locked':>17} "
          f"{'mean R1':>12} {'avg VIX':>10}")
    for label, grp in r1.groupby(regime):
        if len(grp) < 5:
            continue
        s = float(grp.std(ddof=1))
        m = float(grp.mean())
        v = float(vix_close.loc[grp.index].mean())
        print(f"  {str(label):<22} {len(grp):>5} {s:>10.6f} {s / LOCKED_SIGMA_R1:>15.3f}x "
              f"{m:>+12.6f} {v:>10.2f}")

    # --- Rolling 6-month sigma_R1 to spot drift ---
    print("\n" + "=" * 76)
    print("ROLLING 6-MONTH sigma_R1 (every ~3 months)")
    print("=" * 76)
    rolling = r1.rolling(126, min_periods=60).std(ddof=1)
    sample = rolling.iloc[::63].dropna()  # ~3-month stride
    print(f"  {'date':<12} {'rolling sigma':>12} {'ratio vs locked':>17}")
    for d, val in sample.items():
        print(f"  {d.date()!s:<12} {val:>12.6f} {val / LOCKED_SIGMA_R1:>15.3f}x")

    # --- Verdict ---
    yearly_sigmas = r1.groupby(r1.index.year).std(ddof=1)
    yearly_ratios = yearly_sigmas / LOCKED_SIGMA_R1
    spread = float(yearly_ratios.max() - yearly_ratios.min())
    overall_ratio = sigma_full / LOCKED_SIGMA_R1

    print("\n" + "=" * 76)
    print("VERDICT")
    print("=" * 76)
    print(f"  Overall realised/locked ratio   : {overall_ratio:.3f}x")
    print(f"  Yearly-ratio spread (max - min) : {spread:.3f}")
    print(f"  Per-year ratios                 : "
          f"{', '.join(f'{y}={r:.2f}x' for y, r in yearly_ratios.items())}")
    if 0.85 <= overall_ratio <= 1.15 and spread <= 0.40:
        print("  -> sigma_R1 = 0.00142 looks reasonable. Locked value is fine.")
    elif overall_ratio > 1.15 or overall_ratio < 0.85:
        print("  -> sigma_R1 has DRIFTED meaningfully from the IS calibration.")
        print(f"     Suggest updating SIGMA_R1 to ~{sigma_full:.5f} (or whatever "
              "rolling window you trust).")
    else:
        print("  -> sigma_R1 is roughly in range overall but volatile across regimes. "
              "May want a rolling estimator instead of a static value.")


if __name__ == "__main__":
    main()
