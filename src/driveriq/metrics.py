"""Analytical layers, ordered by how much evidence each one actually has.

Layer 1 spans two years and 4,881 trips. Layer 2 covers the 34 GPS sessions.
Layer 3 sees only the 257 trips that fall inside those sessions. Every
aggregate carries its sample size and a confidence band so the thin layers
cannot be read as though they were the strong one.

Note what is missing from Layer 1: online time only exists for the one month
the GPS export covers, so earnings per hour is not computable across the full
history. The backbone measures per trip and per active day instead.
"""

import pandas as pd

from . import config as cfg
from . import ingest

CUBE_KEYS = ["dominant_cell", "day_of_week", "time_window"]


def confidence(n: pd.Series) -> pd.Series:
    out = pd.Series("insufficient", index=n.index, dtype="object")
    for threshold, label in sorted(cfg.CONFIDENCE_BANDS):
        out[n >= threshold] = label
    return out


def _window_order(df: pd.DataFrame, col: str = "time_window") -> pd.DataFrame:
    order = [name for name, _, _ in cfg.TIME_WINDOWS]
    df[col] = pd.Categorical(df[col], categories=order, ordered=True)
    return df


def time_backbone(trips: pd.DataFrame) -> pd.DataFrame:
    """Layer 1 — earnings by day of week and time window, full history."""
    agg = trips.groupby(["day_of_week", "time_window"], as_index=False, observed=True).agg(
        trips=("earnings", "size"),
        earnings=("earnings", "sum"),
        earnings_per_trip=("earnings", "mean"),
        tips=("tips", "sum"),
        active_days=("date", "nunique"),
    )
    agg["earnings_per_active_day"] = agg["earnings"] / agg["active_days"]
    agg["trips_per_active_day"] = agg["trips"] / agg["active_days"]
    agg["confidence"] = confidence(agg["trips"])
    return _window_order(agg).sort_values(["day_of_week", "time_window"]).reset_index(drop=True)


def hourly_profile(trips: pd.DataFrame) -> pd.DataFrame:
    """Layer 1 — the same history at hourly resolution."""
    agg = trips.groupby("hour", as_index=False).agg(
        trips=("earnings", "size"),
        earnings=("earnings", "sum"),
        earnings_per_trip=("earnings", "mean"),
        active_days=("date", "nunique"),
    )
    agg["confidence"] = confidence(agg["trips"])
    return agg.sort_values("hour").reset_index(drop=True)


def session_metrics(sessions: pd.DataFrame, trips: pd.DataFrame) -> pd.DataFrame:
    """Layer 2 — per-session earnings rate, the only place $/hour is honest."""
    located = trips[trips["has_location"]]
    per_session = located.groupby("session_id", as_index=False).agg(
        trips=("earnings", "size"),
        earnings=("earnings", "sum"),
    )
    merged = sessions.merge(
        per_session, left_on="session_id", right_on="session_id", how="left"
    )
    merged[["trips", "earnings"]] = merged[["trips", "earnings"]].fillna(0)

    hours = merged["online_minutes"] / 60.0
    merged["earnings_per_hour"] = merged["earnings"] / hours
    merged["trips_per_hour"] = merged["trips"] / hours
    return merged


def stay_duration_curve(sessions: pd.DataFrame, trips: pd.DataFrame) -> pd.DataFrame:
    """Layer 2 — does staying out longer keep paying?

    Bucketing trips by how far into a session they occurred shows whether the
    later hours of a shift earn like the early ones. This is the defensible
    version of "how long should I stay", since it needs only time and earnings.
    """
    located = trips[trips["has_location"]].merge(
        sessions[["session_id", "started_at", "online_minutes"]],
        on="session_id",
        how="inner",
    )
    elapsed = (located["ts_local"] - located["started_at"]).dt.total_seconds() / 3600.0
    located = located.assign(hour_into_session=elapsed.astype(int).clip(lower=0))

    # A bucket only counts where sessions actually ran that long, otherwise the
    # tail measures shift length rather than falling productivity.
    exposure = sessions["online_minutes"].div(60.0)
    agg = located.groupby("hour_into_session", as_index=False).agg(
        trips=("earnings", "size"),
        earnings=("earnings", "sum"),
        earnings_per_trip=("earnings", "mean"),
    )
    agg["sessions_still_online"] = agg["hour_into_session"].map(
        lambda h: int((exposure > h).sum())
    )
    agg["trips_per_session_hour"] = agg["trips"] / agg["sessions_still_online"]
    agg["confidence"] = confidence(agg["trips"])
    return agg


def _online_minutes_by_window(sessions: pd.DataFrame) -> pd.DataFrame:
    """Split each session's online span into per-window minute counts.

    Sessions run about three hours, so one straddles several time windows.
    Charging all of its minutes to the window it began in would inflate that
    window's rate and starve the others.
    """
    spans = [
        pd.DataFrame({
            "dominant_cell": row.dominant_cell,
            "ts": pd.date_range(row.started_at, row.ended_at, freq="1min"),
        })
        for row in sessions.itertuples()
    ]
    if not spans:
        return pd.DataFrame(columns=CUBE_KEYS + ["online_minutes"])

    minutes = pd.concat(spans, ignore_index=True)
    minutes["day_of_week"] = minutes["ts"].dt.day_name()
    minutes["time_window"] = ingest.assign_time_window(minutes["ts"].dt.hour)
    return minutes.groupby(CUBE_KEYS, as_index=False).agg(online_minutes=("ts", "size"))


def _moving_share_by_window(gps: pd.DataFrame, sessions: pd.DataFrame) -> pd.DataFrame:
    """Movement-based stand-in for utilisation.

    The real metric is active time over online time, but Driver Status is blank
    in every row of this export, so on-trip time cannot be read. Share of online
    pings showing movement is the closest honest substitute -- it is a proxy,
    and is named like one so it never gets reported as utilisation.
    """
    labelled = ingest.assign_session_ids(gps).merge(
        sessions[["session_id", "dominant_cell"]], on="session_id", how="inner"
    )
    labelled = labelled.dropna(subset=["dominant_cell"])
    if labelled.empty:
        return pd.DataFrame(columns=CUBE_KEYS + ["moving_share_proxy"])

    agg = labelled.groupby(CUBE_KEYS, as_index=False, observed=True).agg(
        online_pings=("is_moving", "size"), moving_pings=("is_moving", "sum")
    )
    agg["moving_share_proxy"] = agg["moving_pings"] / agg["online_pings"]
    return agg.drop(columns=["online_pings", "moving_pings"])


def location_time_cube(
    sessions: pd.DataFrame, trips: pd.DataFrame, gps: pd.DataFrame
) -> pd.DataFrame:
    """Layer 3 — the README's Location x Day x Time Window unit.

    Built on the 257 located trips, which is all the overlap between earnings
    and GPS allows. Most cells hold single-digit trips, so the confidence column
    is not decoration here: it is the difference between reading this as a
    finding and reading it as noise.
    """
    placed = sessions.dropna(subset=["dominant_cell"])
    if placed.empty:
        return pd.DataFrame(columns=CUBE_KEYS)

    exposure = _online_minutes_by_window(placed)

    located = trips[trips["has_location"]].merge(
        placed[["session_id", "dominant_cell"]], on="session_id", how="inner"
    )
    earned = located.groupby(CUBE_KEYS, as_index=False, observed=True).agg(
        trips=("earnings", "size"),
        earnings=("earnings", "sum"),
        earnings_per_trip=("earnings", "mean"),
    )

    # Exposure leads: time spent somewhere that produced nothing is a finding,
    # not a gap, so those cells must survive the join.
    cube = exposure.merge(earned, on=CUBE_KEYS, how="left")
    cube[["trips", "earnings"]] = cube[["trips", "earnings"]].fillna(0)

    hours = cube["online_minutes"] / 60.0
    cube["earnings_per_hour"] = cube["earnings"] / hours
    cube["trips_per_hour"] = cube["trips"] / hours

    cube = cube.merge(_moving_share_by_window(gps, placed), on=CUBE_KEYS, how="left")
    cube["confidence"] = confidence(cube["trips"])
    return _window_order(cube).sort_values("earnings", ascending=False).reset_index(drop=True)


def micro_location(sessions: pd.DataFrame, trips: pd.DataFrame) -> pd.DataFrame:
    """Layer 3 — earnings by dominant work cell. Thin by construction.

    27 of 33 sessions share one dominant cell, so this cannot support
    "area A beats area B"; it reports what little variation exists, labelled.
    """
    located = trips[trips["has_location"]]
    per_session = located.groupby("session_id", as_index=False).agg(
        trips=("earnings", "size"),
        earnings=("earnings", "sum"),
    )
    joined = sessions.merge(per_session, on="session_id", how="left")
    joined[["trips", "earnings"]] = joined[["trips", "earnings"]].fillna(0)

    agg = joined.groupby("dominant_cell", as_index=False, dropna=True).agg(
        sessions=("session_id", "size"),
        trips=("trips", "sum"),
        earnings=("earnings", "sum"),
        online_minutes=("online_minutes", "sum"),
    )
    hours = agg["online_minutes"] / 60.0
    agg["earnings_per_hour"] = agg["earnings"] / hours
    agg["trips_per_hour"] = agg["trips"] / hours
    agg["confidence"] = confidence(agg["sessions"])
    return agg.sort_values("earnings", ascending=False).reset_index(drop=True)
