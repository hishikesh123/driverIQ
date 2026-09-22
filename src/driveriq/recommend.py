"""Phase 5 — turn the model's numbers into an answer, or into a refusal.

The README frames this as "where should I go?", ranking candidate locations.
That question is not answerable from this export: 27 of 33 located sessions
share one cell and 99% of the driving falls within 3 km, so there is no second
area to recommend. The engine keeps the shape of the README's design but ranks
**time windows**, which two years of data does support, and carries location
through as context rather than as the thing being chosen.

Everything here returns structured data, never prose. README section 13 puts
Python in charge of the numbers and the LLM in charge of the words, so Phase 6
narrates these dictionaries instead of recomputing anything.
"""

import math

import pandas as pd

from . import config as cfg
from . import metrics

# Fine enough that a session boundary is never missed, coarse enough to stay
# cheap. Walking the clock avoids interval arithmetic and its off-by-one bugs.
STEP_HOURS = 0.25

# A window seen fewer times than this gets a number but no ranking; absent
# windows get no number at all.
MIN_OBSERVATIONS_TO_RANK = 10

CAVEATS = [
    "Historical estimates from this driver's own records — they carry no "
    "information about current demand, driver supply, incentives or surge.",
    "Figures describe earnings in a window on days the driver chose to work it, "
    "so they bundle productivity with how long they typically stay.",
    "The driver selects when to work, so genuinely bad windows are "
    "under-represented: treat a low figure as 'rarely worth it', not as a forecast.",
]


def window_for_hour(hour: float) -> str:
    """Which time window a moment of the day falls in."""
    hour = hour % 24
    for name, start, end in cfg.TIME_WINDOWS:
        if start < end:
            if start <= hour < end:
                return name
        elif hour >= start or hour < end:
            return name
    return "unknown"


def window_span(name: str) -> float:
    for window, start, end in cfg.TIME_WINDOWS:
        if window == name:
            return float(end - start) if start < end else float(24 - start + end)
    return 0.0


def expand_coverage(start_hour: float, hours: float) -> list[dict]:
    """Split an availability block into the windows it actually touches."""
    covered: dict[str, float] = {}
    steps = int(round(hours / STEP_HOURS))
    for step in range(steps):
        window = window_for_hour(start_hour + step * STEP_HOURS)
        covered[window] = covered.get(window, 0.0) + STEP_HOURS

    out = []
    for window, hours_covered in covered.items():
        span = window_span(window)
        out.append({
            "window": window,
            "hours_covered": round(hours_covered, 2),
            "window_span_hours": span,
            "coverage": min(hours_covered / span, 1.0) if span else 0.0,
        })
    return sorted(out, key=lambda r: -r["hours_covered"])


def load_expectations() -> pd.DataFrame:
    """Phase 4's output. Nothing is refitted here."""
    return pd.read_parquet(cfg.PROCESSED_DIR / "expected_earnings.parquet")


def stay_advice() -> dict:
    """How long a session stays productive, from the measured decay curve."""
    curve = pd.read_parquet(cfg.PROCESSED_DIR / "stay_duration_curve.parquet")
    trusted = curve[curve["confidence"] != "insufficient"]
    best = trusted.loc[trusted["trips_per_session_hour"].idxmax()]

    falls_off = None
    peak_rate = best["trips_per_session_hour"]
    for row in curve.sort_values("hour_into_session").itertuples():
        if row.hour_into_session > best["hour_into_session"] and \
                row.trips_per_session_hour < peak_rate * 0.6:
            falls_off = int(row.hour_into_session)
            break

    return {
        "peak_hour_into_session": int(best["hour_into_session"]),
        "peak_trips_per_hour": round(float(peak_rate), 2),
        "falls_off_after_hour": falls_off,
        "suggested_session_hours": falls_off if falls_off else int(curve["hour_into_session"].max()),
        "evidence_sessions": int(best["sessions_still_online"]),
        "note": (
            "Trips per hour peaks in the second hour out and holds through the "
            "third. The fourth-hour figure rests on 9 trips, so treat it as a "
            "hint rather than a rule."
        ),
    }


def _reference_rates(expectations: pd.DataFrame) -> pd.Series:
    """Earnings per window-hour across all known windows, for ranking context."""
    spans = expectations["time_window"].map(window_span).replace(0, pd.NA)
    return (expectations["predicted_earnings"] / spans).dropna()


def plan_session(day: str, start_hour: float, hours: float,
                 expectations: pd.DataFrame | None = None,
                 with_alternatives: bool = True) -> dict:
    """Answer "I am free then — is it worth it, and how long should I stay?"."""
    expectations = load_expectations() if expectations is None else expectations
    day_rows = expectations[expectations["day_of_week"] == day]

    windows, total, var_lo, var_hi = [], 0.0, 0.0, 0.0
    for block in expand_coverage(start_hour, hours):
        match = day_rows[day_rows["time_window"] == block["window"]]
        if match.empty:
            windows.append({
                **block,
                "status": "no_evidence",
                "observations": 0,
                "note": f"{day} {block['window']} has never been worked in this history.",
            })
            continue

        row = match.iloc[0]
        observations = int(row["observations"])
        # Partial coverage is pro-rated, and says so: the model predicts a
        # typical full presence in the window, not an hourly rate.
        factor = block["coverage"]
        expected = float(row["predicted_earnings"]) * factor
        low = float(row["low"]) * factor
        high = float(row["high"]) * factor

        total += expected
        var_lo += (expected - low) ** 2
        var_hi += (high - expected) ** 2

        windows.append({
            **block,
            "status": "ok" if observations >= MIN_OBSERVATIONS_TO_RANK else "thin",
            "expected_earnings": round(expected, 2),
            "band_80": [round(low, 2), round(high, 2)],
            "observations": observations,
            "confidence": row["confidence"],
            "pro_rated": factor < 1.0,
        })

    usable = [w for w in windows if w.get("status") == "ok"]
    if not usable:
        return {
            "query": {"day": day, "start_hour": start_hour, "available_hours": hours},
            "verdict": "not_enough_evidence",
            "expected_earnings": None,
            "windows": windows,
            "stay_advice": stay_advice(),
            "caveats": CAVEATS,
        }

    # Bands are combined in quadrature, not added: both windows landing on
    # their worst case at once is far less likely than summing implies.
    rates = _reference_rates(expectations)
    per_hour = total / hours if hours else 0.0
    percentile = float((rates < per_hour).mean())

    return {
        "query": {"day": day, "start_hour": start_hour, "available_hours": hours},
        "verdict": "worth_going" if percentile >= 0.6 else
                   ("reasonable" if percentile >= 0.3 else "marginal"),
        "expected_earnings": round(total, 2),
        "band_80": [round(max(total - math.sqrt(var_lo), 0.0), 2),
                    round(total + math.sqrt(var_hi), 2)],
        "band_note": "combined across windows in quadrature; approximate",
        "expected_per_available_hour": round(per_hour, 2),
        "percentile_vs_all_windows": round(percentile, 2),
        "windows": windows,
        "stay_advice": stay_advice(),
        "alternatives": _alternatives(expectations, day, hours, exclude=start_hour)
                        if with_alternatives else [],
        "caveats": CAVEATS,
    }


def _alternatives(expectations: pd.DataFrame, day: str, hours: float,
                  exclude: float, top_n: int = 3) -> list[dict]:
    """Better start times on the same day, if any exist."""
    out = []
    for start in range(6, 22):
        if abs(start - exclude) < 1:
            continue
        # Alternatives are scored without their own alternatives, or the
        # recursion never terminates.
        plan = plan_session(day, float(start), hours, expectations,
                            with_alternatives=False)
        if plan["expected_earnings"] is None:
            continue
        out.append({
            "start_hour": start,
            "expected_earnings": plan["expected_earnings"],
            "verdict": plan["verdict"],
        })
    out.sort(key=lambda r: -r["expected_earnings"])
    return out[:top_n]


def rank_windows(day: str | None = None, top_n: int = 10) -> dict:
    """Answer "when should I work?" across the whole week, or one day."""
    expectations = load_expectations()
    rows = expectations if day is None else expectations[expectations["day_of_week"] == day]

    ranked = []
    for row in rows.sort_values("predicted_earnings", ascending=False).itertuples():
        observations = int(row.observations)
        ranked.append({
            "day": row.day_of_week,
            "window": row.time_window,
            "expected_earnings": round(float(row.predicted_earnings), 2),
            "band_80": [round(float(row.low), 2), round(float(row.high), 2)],
            "observations": observations,
            "confidence": row.confidence,
            "rankable": observations >= MIN_OBSERVATIONS_TO_RANK,
        })

    never_worked = sorted(
        {name for name, _, _ in cfg.TIME_WINDOWS} - set(expectations["time_window"])
    )
    return {
        "scope": day or "all days",
        "ranked": [r for r in ranked if r["rankable"]][:top_n],
        "withheld_thin_evidence": [r for r in ranked if not r["rankable"]],
        "never_worked_windows": never_worked,
        "stay_advice": stay_advice(),
        "caveats": CAVEATS,
    }


def confidence_for(observations: int) -> str:
    return metrics.confidence(pd.Series([observations])).iloc[0]
