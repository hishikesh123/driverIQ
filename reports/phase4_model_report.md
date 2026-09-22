# DriverIQ — Phase 4: Earnings Model

Regenerate with `python scripts/run_phase4.py`.

## What is being predicted, and why not $/hour

The README asks for earnings per hour. That is not computable here: online
time exists only for the single month of GPS, which is 34 sessions — far too
few to train on. The target is therefore **earnings in a worked time window**,
which two years of data does support and which matches the decision actually
being made: *is Friday evening worth going out for?*

Earnings per trip is near-constant for this driver ($6.97–$7.93 across every
busy hour), so this is really a model of trip volume — the two correlate at
0.93. Predicting dollars just keeps the output in the units the driver thinks in.

## Setup

- Rows: 1,113, one per (date, time window) actually worked
- Train: 892 rows up to 2026-05-06
- Test: 221 rows after that, through 2026-08-24
- Split is **chronological, never random** — a shuffled split would let the
  model learn from days that had not happened yet.
- Windows never worked are absent by construction: there is no exposure to
  measure, so the model answers *"given I go out then, what should I expect?"*

## Results

The benchmark is the historical average for that day and window — the number
a driver could work out with a pen. A model that cannot beat it is not worth
shipping.

| Model | MAE | RMSE | R² | vs baseline |
|---|---|---|---|---|
| random_forest ⭐ | $8.62 | $11.55 | 0.641 | +20.8% |
| gradient_boosting | $9.60 | $12.78 | 0.560 | +11.8% |
| baseline_group_mean | $10.89 | $13.90 | 0.480 | +0.0% |
| ridge | $11.89 | $14.72 | 0.417 | -9.2% |

**random_forest wins**, cutting mean absolute error to $8.62 — 20.8% better than the historical average.

Ridge does *worse* than the baseline. That is informative rather than a bug:
the relationship is not linear in these features, and a linear model forced
through them underperforms simply looking up the group average.

## Uncertainty — two wrong attempts before a right one

This took three goes, and the failures are worth recording because each one
looked fine until it was checked against reality.

1. **Plain quantile regression.** Nominal 80% band; it actually held **58%** of
   outcomes. Badly overconfident.
2. **Quantile models fit on the earliest slice of training data.** Coverage rose
   to 85%, but the upward trend in the data dragged the lower bound for evening
   peak down to **$9.87** — where the true 10th percentile is **$24.22**. A band
   that wide at the bottom is technically covered and practically useless.
3. **Normalised split-conformal** (shipped). A second model predicts the *size*
   of the error from the same features; held-out rows calibrate it.

- Calibrated multiplier: **2.22×** predicted spread
- Achieved coverage on the test period: **77.4%** (nominal 80%)
- Mean band width: $26.53

The band now adapts instead of applying one width everywhere:

| Window | Mean band | Width |
|---|---|---|
| afternoon | $3.88–$30.45 | $26.57 |
| evening_peak | $32.03–$73.51 | $41.48 |
| late_morning | $6.83–$24.26 | $17.44 |
| lunch | $20.30–$41.80 | $21.50 |
| night | $5.13–$24.21 | $19.08 |

Evening peak genuinely varies more than late morning, and the band now says so.
The band is the honest output; the point estimate is just its middle.

## What the model is using

| Feature | Importance |
|---|---|
| `window_history_mean` | 0.319 |
| `time_window_evening_peak` | 0.255 |
| `days_since_start` | 0.171 |
| `recent_form` | 0.107 |
| `month_8` | 0.021 |
| `time_window_lunch` | 0.020 |

The driver's own track record — what this window has paid before plus recent
form — accounts for **43%** of the signal. The model
is mostly learning this driver's established pattern, not a general law of
the Melbourne market.

`days_since_start` carries 17%, meaning there is a
time trend in the data. **Do not extrapolate far past the training period** —
a tree model holds the last trend value flat rather than continuing it, and
either behaviour is a guess once you leave the observed range.

## Expected earnings by window

The hand-off to Phase 5. Each row carries its 80% band and how many times that
window has actually been worked, so the recommendation layer can decline to
answer where evidence is thin instead of quoting a confident figure.

| Day | Window | Expected | 80% band | Worked | Confidence |
|---|---|---|---|---|---|
| Thursday | evening_peak | $49.16 | $24.68–$73.64 | 50 | high |
| Sunday | evening_peak | $47.67 | $25.19–$70.16 | 42 | high |
| Friday | evening_peak | $46.79 | $20.61–$72.98 | 54 | high |
| Saturday | evening_peak | $44.78 | $20.54–$69.02 | 46 | high |
| Wednesday | evening_peak | $43.03 | $26.24–$59.82 | 45 | high |
| Monday | evening_peak | $40.87 | $21.27–$60.47 | 38 | high |
| Tuesday | evening_peak | $39.70 | $18.95–$60.46 | 36 | high |
| Tuesday | lunch | $31.70 | $22.41–$40.98 | 30 | high |
| Sunday | lunch | $31.47 | $10.16–$52.78 | 40 | high |
| Thursday | lunch | $28.75 | $18.09–$39.41 | 39 | high |

## How to read this

- These are **historical estimates from one driver's own records**. They carry
  no information about current demand, driver supply, incentives or surge.
- The target bundles *productivity* with *how long the driver typically stays*
  in that window. Without online time for the full history the two cannot be
  separated, so a low figure may mean a quiet window or simply a short one.
- There is a **selection effect**: the driver chooses when to work, probably
  favouring good windows. The model learns earnings *conditional on having
  chosen to work*, which is not the same as what an unworked window would pay.
- Typical error is around $9 against a mean of $29 — useful for ranking windows, too coarse for
  budgeting a specific evening.
