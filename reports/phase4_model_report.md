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
- Achieved coverage on the test period: **77.8%** (nominal 80%)
- Mean band width: $26.55

The band now adapts instead of applying one width everywhere:

| Window | Mean band | Width |
|---|---|---|
| afternoon | $3.85–$30.48 | $26.63 |
| evening_peak | $32.06–$73.49 | $41.43 |
| late_morning | $6.81–$24.28 | $17.47 |
| lunch | $20.27–$41.83 | $21.56 |
| night | $5.12–$24.22 | $19.10 |

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
| Thursday | evening_peak | $49.16 | $24.67–$73.65 | 50 | high |
| Sunday | evening_peak | $47.67 | $25.23–$70.11 | 42 | high |
| Friday | evening_peak | $46.79 | $20.60–$72.99 | 54 | high |
| Saturday | evening_peak | $44.78 | $20.60–$68.96 | 46 | high |
| Wednesday | evening_peak | $43.03 | $26.26–$59.80 | 45 | high |
| Monday | evening_peak | $40.87 | $21.29–$60.45 | 38 | high |
| Tuesday | evening_peak | $39.70 | $18.97–$60.43 | 36 | high |
| Tuesday | lunch | $31.70 | $22.38–$41.02 | 30 | high |
| Sunday | lunch | $31.47 | $10.16–$52.78 | 40 | high |
| Thursday | lunch | $28.75 | $18.05–$39.45 | 39 | high |

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
