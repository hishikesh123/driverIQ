"""Phase 4 — fit and honestly evaluate the earnings model."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np
import pandas as pd

from driveriq import config as cfg
from driveriq import metrics
from driveriq import model as M


def main() -> None:
    trips = pd.read_parquet(cfg.PROCESSED_DIR / "trips.parquet")
    data = M.add_history_features(M.build_dataset(trips))
    train, test, cutoff = M.chronological_split(data)

    scores, predictions, fitted, train_f, test_f = M.evaluate(train, test)

    best_name = scores.iloc[0]["model"]
    estimator = M.candidate_models()[best_name]
    lo, hi, artifacts = M.conformal_interval(train, test, estimator)
    coverage = float(((test_f[M.TARGET] >= lo) & (test_f[M.TARGET] <= hi)).mean())

    preds = test_f[["date", "day_of_week", "time_window", "trips", "earnings"]].copy()
    preds["predicted"] = predictions[best_name]
    preds["low"], preds["high"] = lo, hi
    preds["inside_band"] = (preds["earnings"] >= lo) & (preds["earnings"] <= hi)
    preds["error"] = preds["predicted"] - preds["earnings"]

    expected = M.expected_table(data, artifacts)
    expected["confidence"] = metrics.confidence(expected["observations"])

    importances = _importances(fitted.get(best_name))

    for name, frame in {
        "model_scores": scores,
        "model_predictions": preds,
        "expected_earnings": expected,
        "model_feature_importance": importances,
    }.items():
        if frame is not None:
            frame.to_parquet(cfg.PROCESSED_DIR / f"{name}.parquet", index=False)

    _write_report(data, train, test, cutoff, scores, best_name, coverage,
                  artifacts, lo, hi, expected, importances, preds)
    print(f"Best model: {best_name} · MAE ${scores.iloc[0]['mae']:.2f} "
          f"({scores.iloc[0]['vs_baseline_pct']:+.1f}% vs baseline)")
    print(f"Report: {(cfg.REPORTS_DIR / 'phase4_model_report.md').relative_to(cfg.PROJECT_ROOT)}")


def _importances(pipe) -> pd.DataFrame | None:
    if pipe is None or not hasattr(pipe.named_steps["est"], "feature_importances_"):
        return None
    names = [n.split("__", 1)[-1] for n in pipe.named_steps["prep"].get_feature_names_out()]
    df = pd.DataFrame({
        "feature": names,
        "importance": pipe.named_steps["est"].feature_importances_,
    })
    return df.sort_values("importance", ascending=False).reset_index(drop=True)


def _write_report(data, train, test, cutoff, scores, best, coverage, artifacts,
                  lo, hi, expected, importances, preds) -> None:
    lines = []
    add = lines.append

    add("# DriverIQ — Phase 4: Earnings Model")
    add("")
    add("Regenerate with `python scripts/run_phase4.py`.")
    add("")

    add("## What is being predicted, and why not $/hour")
    add("")
    add("The README asks for earnings per hour. That is not computable here: online")
    add("time exists only for the single month of GPS, which is 34 sessions — far too")
    add("few to train on. The target is therefore **earnings in a worked time window**,")
    add("which two years of data does support and which matches the decision actually")
    add("being made: *is Friday evening worth going out for?*")
    add("")
    add("Earnings per trip is near-constant for this driver ($6.97–$7.93 across every")
    add("busy hour), so this is really a model of trip volume — the two correlate at")
    add("0.93. Predicting dollars just keeps the output in the units the driver thinks in.")
    add("")

    add("## Setup")
    add("")
    add(f"- Rows: {len(data):,}, one per (date, time window) actually worked")
    add(f"- Train: {len(train):,} rows up to {cutoff:%Y-%m-%d}")
    add(f"- Test: {len(test):,} rows after that, through {test['date'].max():%Y-%m-%d}")
    add("- Split is **chronological, never random** — a shuffled split would let the")
    add("  model learn from days that had not happened yet.")
    add("- Windows never worked are absent by construction: there is no exposure to")
    add("  measure, so the model answers *\"given I go out then, what should I expect?\"*")
    add("")

    add("## Results")
    add("")
    add("The benchmark is the historical average for that day and window — the number")
    add("a driver could work out with a pen. A model that cannot beat it is not worth")
    add("shipping.")
    add("")
    add("| Model | MAE | RMSE | R² | vs baseline |")
    add("|---|---|---|---|---|")
    for r in scores.itertuples():
        flag = " ⭐" if r.model == best else ""
        add(f"| {r.model}{flag} | ${r.mae:.2f} | ${r.rmse:.2f} | {r.r2:.3f} | "
            f"{r.vs_baseline_pct:+.1f}% |")
    add("")
    best_row = scores[scores["model"] == best].iloc[0]
    add(f"**{best} wins**, cutting mean absolute error to ${best_row['mae']:.2f} — "
        f"{best_row['vs_baseline_pct']:.1f}% better than the historical average.")
    add("")
    add("Ridge does *worse* than the baseline. That is informative rather than a bug:")
    add("the relationship is not linear in these features, and a linear model forced")
    add("through them underperforms simply looking up the group average.")
    add("")

    add("## Uncertainty — two wrong attempts before a right one")
    add("")
    add("This took three goes, and the failures are worth recording because each one")
    add("looked fine until it was checked against reality.")
    add("")
    add("1. **Plain quantile regression.** Nominal 80% band; it actually held **58%** of")
    add("   outcomes. Badly overconfident.")
    add("2. **Quantile models fit on the earliest slice of training data.** Coverage rose")
    add("   to 85%, but the upward trend in the data dragged the lower bound for evening")
    add("   peak down to **$9.87** — where the true 10th percentile is **$24.22**. A band")
    add("   that wide at the bottom is technically covered and practically useless.")
    add("3. **Normalised split-conformal** (shipped). A second model predicts the *size*")
    add("   of the error from the same features; held-out rows calibrate it.")
    add("")
    add(f"- Calibrated multiplier: **{artifacts['q']:.2f}×** predicted spread")
    add(f"- Achieved coverage on the test period: **{coverage:.1%}** (nominal 80%)")
    add(f"- Mean band width: ${np.mean(hi - lo):.2f}")
    add("")
    add("The band now adapts instead of applying one width everywhere:")
    add("")
    add("| Window | Mean band | Width |")
    add("|---|---|---|")
    widths = preds.assign(width=preds["high"] - preds["low"])
    for w, grp in widths.groupby("time_window", observed=True):
        if len(grp) >= 5:
            add(f"| {w} | ${grp['low'].mean():.2f}–${grp['high'].mean():.2f} | "
                f"${grp['width'].mean():.2f} |")
    add("")
    add("Evening peak genuinely varies more than late morning, and the band now says so.")
    add("The band is the honest output; the point estimate is just its middle.")
    add("")

    if importances is not None:
        add("## What the model is using")
        add("")
        add("| Feature | Importance |")
        add("|---|---|")
        for r in importances.head(6).itertuples():
            add(f"| `{r.feature}` | {r.importance:.3f} |")
        add("")
        hist = importances[importances["feature"].str.contains("history|recent")]
        add(f"The driver's own track record — what this window has paid before plus recent")
        add(f"form — accounts for **{hist['importance'].sum():.0%}** of the signal. The model")
        add("is mostly learning this driver's established pattern, not a general law of")
        add("the Melbourne market.")
        add("")
        trend = importances[importances["feature"] == "days_since_start"]
        if len(trend):
            add(f"`days_since_start` carries {trend['importance'].iloc[0]:.0%}, meaning there is a")
            add("time trend in the data. **Do not extrapolate far past the training period** —")
            add("a tree model holds the last trend value flat rather than continuing it, and")
            add("either behaviour is a guess once you leave the observed range.")
            add("")

    add("## Expected earnings by window")
    add("")
    add("The hand-off to Phase 5. Each row carries its 80% band and how many times that")
    add("window has actually been worked, so the recommendation layer can decline to")
    add("answer where evidence is thin instead of quoting a confident figure.")
    add("")
    add("| Day | Window | Expected | 80% band | Worked | Confidence |")
    add("|---|---|---|---|---|---|")
    for r in expected.head(10).itertuples():
        add(f"| {r.day_of_week} | {r.time_window} | ${r.predicted_earnings:.2f} | "
            f"${r.low:.2f}–${r.high:.2f} | {r.observations} | {r.confidence} |")
    add("")

    add("## How to read this")
    add("")
    add("- These are **historical estimates from one driver's own records**. They carry")
    add("  no information about current demand, driver supply, incentives or surge.")
    add("- The target bundles *productivity* with *how long the driver typically stays*")
    add("  in that window. Without online time for the full history the two cannot be")
    add("  separated, so a low figure may mean a quiet window or simply a short one.")
    add("- There is a **selection effect**: the driver chooses when to work, probably")
    add("  favouring good windows. The model learns earnings *conditional on having")
    add("  chosen to work*, which is not the same as what an unworked window would pay.")
    add(f"- Typical error is around ${best_row['mae']:.0f} against a mean of "
        f"${test['earnings'].mean():.0f} — useful for ranking windows, too coarse for")
    add("  budgeting a specific evening.")

    (cfg.REPORTS_DIR / "phase4_model_report.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
