"""Phase 4 — expected earnings for a day-and-time-window worth working.

The README asks for earnings per hour. That is not computable here: online time
exists only for the one month of GPS, which is 34 sessions -- far too few to
train on. What two years of data does support is earnings per worked window,
which is also closer to the decision a driver actually makes ("is Friday evening
worth going out for?").

Earnings per trip is near-constant for this driver ($6.97-$7.93 across every
busy hour), so this target is really predicting trip volume; the two correlate
at 0.93. Predicting the dollar figure keeps the output in units the driver uses.

Everything is evaluated against the historical group mean -- the number a driver
could work out with a pen. A model that cannot beat that has not earned its place.
"""

import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

CATEGORICAL = ["day_of_week", "time_window", "month"]
NUMERIC = ["days_since_start", "is_weekend", "window_history_mean", "recent_form"]
TARGET = "earnings"

# Held back by date, never at random: shuffling would let the model learn from
# days that had not happened yet.
TEST_FRACTION = 0.2


def build_dataset(trips: pd.DataFrame) -> pd.DataFrame:
    """One row per (date, time window) the driver actually worked.

    Windows never worked are absent by construction -- there is no exposure to
    measure and no counterfactual in the data. The model therefore answers
    "given that I go out then, what should I expect?", not "should this window
    exist at all?".
    """
    df = (
        trips.groupby(["date", "time_window"], observed=True)
        .agg(earnings=("earnings", "sum"), trips=("earnings", "size"))
        .reset_index()
    )
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(["date", "time_window"]).reset_index(drop=True)

    df["day_of_week"] = df["date"].dt.day_name()
    df["month"] = df["date"].dt.month.astype(str)
    df["is_weekend"] = (df["date"].dt.dayofweek >= 5).astype(int)
    df["days_since_start"] = (df["date"] - df["date"].min()).dt.days
    return df


def add_history_features(df: pd.DataFrame) -> pd.DataFrame:
    """Past-only features: what this window has paid before, and recent form.

    Both are shifted by one occurrence so a row never sees its own outcome.
    These are what a driver carries in their head, so a fair model should have
    them too.
    """
    df = df.sort_values("date").reset_index(drop=True)

    grouped = df.groupby(["day_of_week", "time_window"], observed=True)["earnings"]
    df["window_history_mean"] = grouped.transform(
        lambda s: s.shift(1).expanding().mean()
    )

    daily = df.groupby("date")["earnings"].sum().sort_index()
    recent = daily.shift(1).rolling(14, min_periods=3).mean()
    df["recent_form"] = df["date"].map(recent)

    return df


def chronological_split(df: pd.DataFrame, test_fraction: float = TEST_FRACTION):
    """Split on a date boundary so training never sees the future."""
    cutoff = df["date"].quantile(1 - test_fraction)
    train = df[df["date"] <= cutoff].copy()
    test = df[df["date"] > cutoff].copy()
    return train, test, cutoff


def _fill_history(train: pd.DataFrame, test: pd.DataFrame):
    """Fill the cold-start gaps using training data only."""
    train, test = train.copy(), test.copy()
    for col in ("window_history_mean", "recent_form"):
        fallback = train[col].mean()
        if np.isnan(fallback):
            fallback = train[TARGET].mean()
        train[col] = train[col].fillna(fallback)
        test[col] = test[col].fillna(fallback)
    return train, test


def baseline_prediction(train: pd.DataFrame, test: pd.DataFrame) -> pd.Series:
    """The pen-and-paper benchmark: this day and window's historical average."""
    means = train.groupby(["day_of_week", "time_window"], observed=True)[TARGET].mean()
    overall = train[TARGET].mean()
    keys = list(zip(test["day_of_week"], test["time_window"]))
    return pd.Series([means.get(k, overall) for k in keys], index=test.index)


def _serial(estimator):
    """Pin an estimator to one thread where bit-for-bit repeatability matters."""
    if "n_jobs" in estimator.get_params():
        estimator.set_params(n_jobs=1)
    return estimator


def _pipeline(estimator) -> Pipeline:
    return Pipeline([
        ("prep", ColumnTransformer([
            ("cat", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL),
        ], remainder="passthrough")),
        ("est", estimator),
    ])


def candidate_models() -> dict:
    return {
        "ridge": Ridge(alpha=1.0),
        "random_forest": RandomForestRegressor(
            n_estimators=400, min_samples_leaf=4, random_state=0, n_jobs=-1
        ),
        "gradient_boosting": GradientBoostingRegressor(
            n_estimators=300, max_depth=3, learning_rate=0.05, random_state=0
        ),
    }


def _scores(name: str, y_true, y_pred, baseline_mae: float) -> dict:
    mae = mean_absolute_error(y_true, y_pred)
    return {
        "model": name,
        "mae": mae,
        "rmse": float(np.sqrt(mean_squared_error(y_true, y_pred))),
        "r2": r2_score(y_true, y_pred),
        "vs_baseline_pct": 100 * (baseline_mae - mae) / baseline_mae,
    }


def evaluate(train: pd.DataFrame, test: pd.DataFrame) -> tuple:
    """Fit every candidate and score it against the historical-average baseline."""
    train, test = _fill_history(train, test)
    features = CATEGORICAL + NUMERIC
    x_train, y_train = train[features], train[TARGET]
    x_test, y_test = test[features], test[TARGET]

    base = baseline_prediction(train, test)
    base_mae = mean_absolute_error(y_test, base)

    rows = [_scores("baseline_group_mean", y_test, base, base_mae)]
    predictions = {"baseline_group_mean": base.to_numpy()}
    fitted = {}

    for name, estimator in candidate_models().items():
        pipe = _pipeline(estimator).fit(x_train, y_train)
        pred = pipe.predict(x_test)
        rows.append(_scores(name, y_test, pred, base_mae))
        predictions[name] = pred
        fitted[name] = pipe

    scores = pd.DataFrame(rows).sort_values("mae").reset_index(drop=True)
    return scores, predictions, fitted, train, test


# A floor on predicted spread, so a quiet window cannot be assigned a
# near-zero band and imply false precision.
SPREAD_FLOOR = 3.0


def conformal_interval(train: pd.DataFrame, test: pd.DataFrame, estimator,
                       coverage: float = 0.8, calibration_fraction: float = 0.3,
                       seed: int = 0) -> tuple:
    """An adaptive 80% band via normalised split-conformal prediction.

    Two earlier attempts were wrong in instructive ways. Plain quantile
    regression gave a nominal 80% band holding only 58% of outcomes. Fitting
    those quantiles on the earliest slice of training data over-corrected: the
    upward trend in the data dragged the lower bound to $10 for evening peak,
    where the true 10th percentile is $24.

    This version predicts the *size* of the error from the same features, then
    calibrates on held-out rows. The band widens where the driver's earnings
    genuinely vary (evening peak) and tightens where they do not (late morning),
    instead of applying one width everywhere.

    README section 25 forbids promising a number. A band that under-covers is
    that promise in disguise, so achieved coverage is measured and reported
    rather than assumed.
    """
    train, test = _fill_history(train, test)
    features = CATEGORICAL + NUMERIC

    rng = np.random.default_rng(seed)
    order = rng.permutation(len(train))
    cut = int(len(train) * (1 - calibration_fraction))
    fit_part, calib = train.iloc[order[:cut]], train.iloc[order[cut:]]

    # Single-threaded on purpose. Parallel tree averaging varies in the last
    # float bits, and that noise cascades: residuals shift, the spread model
    # splits differently, q moves, and the published bands changed by up to
    # $0.06 between identical runs. Bands people quote must be reproducible.
    point = _pipeline(_serial(clone(estimator))).fit(fit_part[features], fit_part[TARGET])
    residuals = np.abs(fit_part[TARGET].to_numpy() - point.predict(fit_part[features]))
    spread = _pipeline(RandomForestRegressor(
        n_estimators=300, min_samples_leaf=8, random_state=seed + 1, n_jobs=1
    )).fit(fit_part[features], residuals)

    sigma_calib = np.maximum(spread.predict(calib[features]), SPREAD_FLOOR)
    scores = np.abs(calib[TARGET].to_numpy() - point.predict(calib[features])) / sigma_calib
    n = len(scores)
    q = float(np.quantile(scores, min(np.ceil((n + 1) * coverage) / n, 1.0)))

    # Refit the centre on all training data: the band's validity is confirmed
    # by measured coverage on the test period, not assumed from theory.
    final = _pipeline(_serial(clone(estimator))).fit(train[features], train[TARGET])
    sigma = np.maximum(spread.predict(test[features]), SPREAD_FLOOR)
    prediction = final.predict(test[features])

    artifacts = {"point": final, "spread": spread, "q": q}
    return np.maximum(prediction - q * sigma, 0.0), prediction + q * sigma, artifacts


def expected_table(df: pd.DataFrame, artifacts: dict) -> pd.DataFrame:
    """Per day and window, what the model expects — the hand-off to Phase 5.

    Each row carries its band and the number of times that window has actually
    been worked, so the recommendation layer can refuse to answer where the
    evidence is thin rather than quoting a confident figure.
    """
    features = CATEGORICAL + NUMERIC
    latest = df.sort_values("date").groupby(
        ["day_of_week", "time_window"], observed=True
    ).last().reset_index()
    latest[NUMERIC] = latest[NUMERIC].fillna(df[NUMERIC].mean())

    counts = df.groupby(["day_of_week", "time_window"], observed=True).size()
    latest["observations"] = [
        int(counts.get((r.day_of_week, r.time_window), 0)) for r in latest.itertuples()
    ]
    prediction = artifacts["point"].predict(latest[features])
    sigma = np.maximum(artifacts["spread"].predict(latest[features]), SPREAD_FLOOR)
    latest["predicted_earnings"] = prediction
    latest["low"] = np.maximum(prediction - artifacts["q"] * sigma, 0.0)
    latest["high"] = prediction + artifacts["q"] * sigma
    return latest.sort_values("predicted_earnings", ascending=False).reset_index(drop=True)
