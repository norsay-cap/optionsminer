# DT15 methodology — R1, the M multipliers, and the σ_R1 investigation

This document is the canonical reference for how DT15 daily levels are computed
in `optionsminer`. It explains the Enhancement-B (PDV-adjusted) variant in
detail, lists every parameter, distinguishes locked vs dynamic inputs, and
documents the September 2026 investigation into σ_R1 calibration.

---

## 1. The big picture

DT15 produces four anchored intraday levels for ES futures, projected around
the session open `O_t`:

```
avg+ = O_t + 0.5 · range_pred
avg- = O_t - 0.5 · range_pred
ext+ = O_t + 0.5 · range_pred · M_up
ext- = O_t - 0.5 · range_pred · M_dn
```

Two methodologies share the same `range_pred` (size predictor) but differ in
the M multipliers:

| Variant | M_up | M_dn |
|---|---|---|
| **Baseline** | 2.27 (locked) | 2.97 (locked) |
| **Enhancement B** | `1.87 · (1 + 1.59 · max(0, +R1/σ_R1))` | `2.57 · (1 + 1.93 · max(0, −R1/σ_R1))` |

Enhancement B is the recommended default. Its dynamic widening makes the
extension multipliers regime-aware: when a path indicator (R1) detects a
recent up-trend, the upside extension widens; when a down-trend, the downside
widens. Symmetric and mechanical — no discretion.

The rest of this doc explains R1, σ_R1, and the parameter set.

---

## 2. Computing R1

R1 is a single weighted sum of the past 250 daily log returns of ES.

### 2.1 The TSPL kernel

The weights come from the Guyon–Lekeufack Time-Shifted Power-Law (TSPL)
kernel:

```
w(τ) ∝ (τ + δ)^(−α)        with α = 1.06,  δ = 0.020
```

Properties:

- **Slow long-memory decay** (power law, not exponential). A 30-day exponential
  weighting forgets what happened 6 months ago entirely; this kernel keeps a
  small but non-zero weight on every day going back a year.
- **Recent days weigh more** than old days — `w(τ)` is decreasing in τ.
- The weights are normalised so `Σ w(τ) · dt = 1` (proper density).

### 2.2 The R1 sum

After normalisation, R1 is the dot product of the kernel weights with the past
250 daily log returns of ES:

```
R1(T) = Σᵢ  w(τᵢ) · log(C_{T-i} / C_{T-i-1})    for i = 1..250
```

Note `i` starts at 1 — today's return is **excluded** to prevent look-ahead.

**Sign meaning:**

- `R1 > 0` → recent past has been net up — bullish path
- `R1 < 0` → recent past has been net down — bearish path
- `R1 ≈ 0` → mean-reverting or sideways

R1 is in units of "log return per day" (very small magnitude). It needs to be
normalised to be interpretable.

### 2.3 σ-normalisation

We divide R1 by `σ_R1`, the standard deviation of R1 across a reference
sample, to convert into "standard deviations":

```
R1_norm = R1 / σ_R1
```

`R1_norm` is unitless. **|R1_norm| > 1** means today's path indicator is more
than one standard deviation away from its historical mean — meaningfully
large.

The choice of `σ_R1` is consequential — see §5 for the investigation.

---

## 3. Computing M_up and M_dn

The widening happens **only on the side the path is biased toward**. We use a
rectified linear unit (ReLU) to gate:

```
upside_widening_signal   = max(0, +R1_norm)    # 0 if R1 is negative
downside_widening_signal = max(0, -R1_norm)    # 0 if R1 is positive
```

So one of the two signals is always zero (or both are zero when R1_norm ≈ 0).

The two sides have separate widening coefficients (`λ_up`, `λ_dn`) and
separate tight bases (`M_up_tight`, `M_dn_tight`):

```
M_up = M_up_tight · (1 + λ_up · upside_widening_signal)
M_dn = M_dn_tight · (1 + λ_dn · downside_widening_signal)
```

### 3.1 Worked example (live snapshot 2026-05-04)

```
R1               = 0.00172
σ_R1 (rolling)   = 0.00096
R1_norm          = 0.00172 / 0.00096 = +1.79
upside_signal    = max(0, +1.79) = 1.79
downside_signal  = max(0, -1.79) = 0

M_up = 1.87 · (1 + 1.59 · 1.79) = 1.87 · 3.85 = 7.20
M_dn = 2.57 · (1 + 1.93 · 0)    = 2.57

# Compared to baseline:
# M_up baseline = 2.27 → today's enh_b is 3.17× wider on the upside
# M_dn baseline = 2.97 → today's enh_b is 0.87× the baseline (narrower)
```

### 3.2 Sensitivity table

| `R1_norm` | M_up | M_dn | Interpretation |
|---|---|---|---|
| **+3.0σ** | 1.87·(1+1.59·3) = **10.79** | 2.57·1 = **2.57** | Extreme up-trend → very wide upside, tight downside |
| **+1.79σ** *(today)* | **7.20** | **2.57** | Strong up-trend |
| **+0.5σ** | **3.36** | **2.57** | Mild up-bias |
| **0** | **1.87** | **2.57** | No bias → BOTH at tight bases (narrower than baseline) |
| **−0.5σ** | **1.87** | **5.05** | Mild down-bias |
| **−1.79σ** | **1.87** | 2.57·(1+1.93·1.79) = **11.45** | Strong down-trend → very wide downside |
| **−3.0σ** | **1.87** | **17.45** | Extreme down-trend |

Things to note:

1. **At R1_norm = 0, both multipliers are SMALLER than baseline** (1.87/2.57
   vs 2.27/2.97). Design intent: in calm markets, *tighten* the bands; only
   widen when the path indicator demands it.
2. **λ_dn (1.93) > λ_up (1.59)**. A 1σ down-move widens the downside slightly
   more than a 1σ up-move widens the upside — reflects calibrated equity-index
   downside fat tails.
3. **No saturation**. Widening grows linearly with R1_norm. At R1_norm = 5σ
   the upside multiplier would be 14.1.

---

## 4. Parameter inventory

### 4.1 LOCKED parameters (do not change unless you edit the source)

| Parameter | Symbol | Value | Source |
|---|---|---|---|
| TSPL kernel exponent | α | **1.06** | Guyon–Lekeufack TSPL paper, VIX-style Table 3 |
| TSPL kernel offset | δ | **0.020** | Guyon–Lekeufack TSPL paper |
| Lookback window | n_lags | **250** | Guyon–Lekeufack TSPL paper (~1 trading year) |
| Tight base, upside | M_up_tight | **1.87** | DT15 Enhancement B study (2018–2022 IS) |
| Tight base, downside | M_dn_tight | **2.57** | DT15 Enhancement B study |
| Widening coefficient, upside | λ_up | **1.59** | DT15 Enhancement B study |
| Widening coefficient, downside | λ_dn | **1.93** | DT15 Enhancement B study |
| Baseline static M_up | M_up_baseline | **2.27** | Original DT15 study (2018–2022) |
| Baseline static M_dn | M_dn_baseline | **2.97** | Original DT15 study |
| Brownian motion factor | K_BM | **√(8/π) ≈ 1.5957** | Definition (mean abs. deviation) |
| VIX blend weight | VIX_BLEND_K | **0.60** | DT15 size-predictor study |
| σ_R1 fallback | SIGMA_R1_FALLBACK | **0.00142** | Original IS calibration (2018–2022) |
| σ_R1 rolling window length | SIGMA_R1_WINDOW | **252** | 1y, this implementation |
| σ_R1 minimum sample for rolling | SIGMA_R1_MIN_SAMPLE | **60** | this implementation — below this we fall back |

### 4.2 DYNAMIC inputs (recomputed every run)

| Quantity | Refreshed when | Depends on |
|---|---|---|
| `range_pred` (size) | every compute | RM5 (5-day mean H–L), prior VIX close |
| **R1** | every compute | past 250 daily log returns of ES |
| **σ_R1 (rolling)** | every compute | past 252 R1 values (rolling std) |
| **R1_norm** | every compute | R1 / σ_R1_rolling |
| **M_up_used, M_dn_used** | every compute | R1_norm via the formulas above |
| Anchor `O_t` | every compute | yfinance daily Open of latest bar (or user override) |
| `avg±, ext±` | every compute | O_t, range_pred, M_up, M_dn |

**Key takeaway:** every quantity that goes into the levels updates daily. The
parameters listed in §4.1 are the only things that don't.

---

## 5. The σ_R1 investigation (2026-05)

### 5.1 The original claim

The DT15 Enhancement B study set `σ_R1 = 0.00142` based on the 2018–2022
in-sample distribution and asserted that this value is "stable across
regimes" — meaning we could keep it locked indefinitely without compromising
calibration.

### 5.2 What we found

We ran `scripts/sigma_r1_stability_check.py` against 4 years of ES data
(2022-05 to 2026-05), computing R1 daily for the last 3 years (755 daily
values) and comparing the realised σ_R1 against the locked 0.00142 across
multiple stratifications.

**The original claim does not hold OOS.** Realised σ_R1 in 2023–2026 is
substantially smaller than 0.00142 AND varies materially with VIX regime.

#### Headline (3-year sample)

| Statistic | Value |
|---|---|
| Realised σ_R1 (full 3y) | **0.000958** |
| Locked σ_R1 | 0.00142 |
| Ratio (realised / locked) | **0.67×** |

#### Per-year

| Year | n | σ_R1 | Ratio | avg VIX |
|---|---|---|---|---|
| 2023 | 168 | 0.000887 | 0.62× | 15.33 |
| 2024 | 252 | 0.000731 | 0.51× | 15.61 |
| 2025 | 252 | 0.001124 | 0.79× | 18.95 |
| 2026 YTD | 83 | 0.000953 | 0.67× | 20.27 |

Yearly ratios spread from 0.51× to 0.79× — well above any reasonable
stability threshold.

#### By VIX regime (tercile of prior-day VIX close)

| Regime | σ_R1 | Ratio | avg VIX |
|---|---|---|---|
| Low (<14.9) | 0.000470 | **0.33×** | 13.56 |
| Mid (14.9–17.6) | 0.000659 | 0.46× | 16.26 |
| High (>17.6) | 0.001185 | **0.83×** | 21.69 |

The high-VIX bucket's σ_R1 is **2.5× the low-VIX bucket's**. σ_R1 scales with
VIX — a property the original "stable" claim missed.

### 5.3 Implication for the live model

Dividing R1 by 0.00142 (too high) **systematically understates R1_norm by
~33%**, which causes M_up/M_dn to under-widen. This is the root cause of the
9.5% ext+ touch rate observed in the head-to-head backfill (vs 5% target).

Today's snapshot:
- With locked σ = 0.00142: R1_norm = +1.21σ → M_up = 5.47
- With realised σ ≈ 0.00096: R1_norm = +1.79σ → M_up = 7.20

The widening should be ~32% larger than what the locked σ produces.

### 5.4 Options considered

| Option | Description | Pros | Cons |
|---|---|---|---|
| **(1) One-line update** | Hard-code `σ_R1 = 0.00096` (recent 3y value) | One line, simple, IS-calibrated to recent data | Will drift again over time; doesn't handle VIX-regime variance |
| **(2) Rolling σ_R1** | Compute σ_R1 dynamically from the last 252 past R1 values | Self-correcting; never goes stale; uses data we already pull; mechanical | Slight added noise in the multipliers (~5% from sample-size error); larger data requirement (3y vs 2y) |
| **(3) VIX-conditional σ_R1** | Stratify σ_R1 by current VIX level (e.g. piecewise low/mid/high VIX) | Most accurate calibration | Three more parameters to estimate; bigger departure from original study; harder to explain |

### 5.5 Decision: **Option 2 (rolling σ_R1)**

Implemented in `analytics/dt15.py` as of v2 (2026-05). Reasons:

1. **The data clearly shows σ_R1 varies** — both over time (year to year) and
   across VIX regimes. A rolling estimator captures both implicitly without
   adding new model logic.
2. **No new parameters to choose** beyond the window length (252 days = 1y,
   matching the n_lags choice for symmetry).
3. **Self-correcting.** Never goes stale. If the 2027 regime is different
   from 2026, σ_R1 will adapt automatically.
4. **Already pull the data.** We bumped `compute_live` from 2y → 3y of ES
   history so we have ~750 trading days, enough for both the 250-day TSPL
   kernel AND the 252-day rolling σ_R1 estimator with margin.
5. **Falls back gracefully.** When fewer than 60 past R1 values are
   available (only happens during the first ~250 days of a fresh backfill),
   we use the locked 0.00142 rather than estimating σ from a tiny sample.
   Recorded transparently as `sigma_r1_source = 'fallback'`.

### 5.6 Implementation details

```python
SIGMA_R1_WINDOW = 252       # 1y of past R1 values
SIGMA_R1_MIN_SAMPLE = 60    # below this, fall back to locked
SIGMA_R1_FALLBACK = 0.00142 # only used when not enough history
```

For each compute, after deriving today's R1, we:

1. Compute the past `SIGMA_R1_WINDOW` R1 values, **excluding today's R1** (no
   look-ahead) — each one uses its own 250-return window.
2. If we have at least `SIGMA_R1_MIN_SAMPLE` of those, take their sample
   standard deviation as σ_R1. Mark `sigma_r1_source = 'rolling'`.
3. Otherwise, use `SIGMA_R1_FALLBACK`. Mark `sigma_r1_source = 'fallback'`.

The dashboard surfaces both `sigma_r1_used` (the actual number) and
`sigma_r1_source` so it's obvious which mode was active. Stored to the DB
on every prediction so we can audit historical decisions.

### 5.7 What to monitor going forward

- **Is the in-band rate moving toward 68%?** It was 23.8% in the 2026-05
  60-day backfill — but this is sensitive to drift, not just range accuracy.
  Re-check after a few months of forward-only data.
- **Is the ext+ touch rate moving toward 5%?** It was 9.5% with the old
  static σ. With rolling σ producing ~32% wider multipliers in the current
  trending regime, we expect this to drop materially. Re-run the
  comparison after the new backfill.
- **Re-run `scripts/sigma_r1_stability_check.py`** every 3–6 months to track
  whether σ_R1 has stabilised or kept drifting.

---

## 6. Reference: the full size-predictor pipeline

For completeness, the size predictor (the part that's identical across both
DT15 variants):

```
RM5         = mean(H_t-i - L_t-i)              for i = 1..5  (5-day H-L mean)
σ_VIX       = (VIX_prior_close / 100) / √252    (per-day vol, log-return units)
range_VIX   = K_BM · σ_VIX · prior_close        with K_BM = √(8/π)
range_pred  = max(RM5, 0.60 · range_VIX)        (realised wins unless VIX is bid)
```

That gives `range_pred` in ES points (the predicted total H–L width). The
levels then project around the open as shown in §1.

---

## 7. References

- **Guyon, J. and Lekeufack, J.** *Volatility Is (Mostly) Path-Dependent*.
  Quantitative Finance, 2023. — origin of the TSPL kernel and the PDV
  framework.
- **DT15 Enhancement B study notes** (user-supplied, 2018–2022 IS / 2023–2025
  OOS calibration). Source of `M_up_tight=1.87, M_dn_tight=2.57, λ_up=1.59,
  λ_dn=1.93`, and the original `σ_R1 = 0.00142`.
- **`scripts/sigma_r1_stability_check.py`** — reproduces the §5
  investigation. Re-run when you want to verify σ_R1 calibration is still
  stable.
- **Implementation:** [`src/optionsminer/analytics/dt15.py`](src/optionsminer/analytics/dt15.py),
  [`src/optionsminer/storage/dt15_storage.py`](src/optionsminer/storage/dt15_storage.py),
  [`src/optionsminer/ui/pages/7_DT15_Levels.py`](src/optionsminer/ui/pages/7_DT15_Levels.py),
  [`src/optionsminer/ui/pages/8_DT15_Backtest.py`](src/optionsminer/ui/pages/8_DT15_Backtest.py),
  [`scripts/sigma_r1_stability_check.py`](scripts/sigma_r1_stability_check.py).
