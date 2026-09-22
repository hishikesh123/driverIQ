import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text

from . import config as cfg

# Every read is scoped to the user's current export. The uploads table is
# append-only, so without this filter a second import would silently double
# every aggregate.
_CURRENT_UPLOAD = """
    SELECT id FROM uploads WHERE is_current ORDER BY uploaded_at DESC LIMIT 1
"""


def _engine():
    return create_engine(cfg.DB_DSN)


def _read_sql(query: str, params: dict | None = None) -> pd.DataFrame:
    with _engine().connect() as conn:
        return pd.read_sql(text(query), conn, params=params or {})


def _to_local(ts: pd.Series) -> pd.Series:
    """Convert stored instants to the driver's wall-clock, then drop the offset."""
    return ts.dt.tz_convert(cfg.TZ).dt.tz_localize(None)


def assign_time_window(hour: pd.Series) -> pd.Series:
    out = pd.Series("unknown", index=hour.index, dtype="object")
    for name, start, end in cfg.TIME_WINDOWS:
        if start < end:
            mask = (hour >= start) & (hour < end)
        else:
            mask = (hour >= start) | (hour < end)
        out[mask] = name
    return out


def _add_calendar_features(df: pd.DataFrame, ts_col: str) -> pd.DataFrame:
    ts = df[ts_col]
    df["date"] = ts.dt.date
    df["hour"] = ts.dt.hour
    df["day_of_week"] = ts.dt.day_name()
    df["is_weekend"] = ts.dt.dayofweek >= 5
    df["time_window"] = assign_time_window(ts.dt.hour)
    return df


def load_payments() -> pd.DataFrame:
    """Payment lines, one row per fare component."""
    df = _read_sql(f"""
        SELECT city_name AS city,
               trip_uuid::text AS trip_uuid,
               local_amount AS amount,
               currency_code AS currency,
               classification,
               category,
               local_timestamp AS ts_local
        FROM driver_payments
        WHERE upload_id = ({_CURRENT_UPLOAD})
        ORDER BY local_timestamp
    """)
    df["ts_local"] = _to_local(df["ts_local"])
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce")
    df["is_tip"] = df["classification"].isin(cfg.TIP_CLASSIFICATIONS)

    df = df.dropna(subset=["ts_local", "amount", "trip_uuid"])
    return _add_calendar_features(df, "ts_local").sort_values("ts_local").reset_index(drop=True)


def build_trips(payments: pd.DataFrame) -> pd.DataFrame:
    """Collapse payment lines into one row per trip.

    A trip's timestamp is its earliest payment line: tips and adjustments can
    land hours later and would otherwise misdate the trip.
    """
    grouped = payments.groupby("trip_uuid", as_index=False).agg(
        ts_local=("ts_local", "min"),
        earnings=("amount", "sum"),
        tips=("amount", lambda s: s[payments.loc[s.index, "is_tip"]].sum()),
        n_payment_lines=("amount", "size"),
        city=("city", "first"),
        currency=("currency", "first"),
    )
    grouped["base_earnings"] = grouped["earnings"] - grouped["tips"]
    return _add_calendar_features(grouped, "ts_local").sort_values("ts_local").reset_index(drop=True)


def load_gps(source: str = "driver") -> pd.DataFrame:
    """App GPS pings for one source ('driver', 'eats' or 'rider'), in local time."""
    df = _read_sql(f"""
        SELECT city,
               is_driver_online AS is_online,
               event_time_utc AS ts_local,
               latitude AS lat,
               longitude AS lon,
               speed_gps,
               analytics_event_type AS event_type
        FROM app_analytics_events
        WHERE upload_id = ({_CURRENT_UPLOAD}) AND source = :source
        ORDER BY event_time_utc
    """, {"source": source})
    df["ts_local"] = _to_local(df["ts_local"])
    df["is_online"] = df["is_online"].fillna(False).astype(bool)
    for col in ("lat", "lon", "speed_gps"):
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=["ts_local", "lat", "lon"])
    return _add_calendar_features(df, "ts_local").sort_values("ts_local").reset_index(drop=True)


def load_driver_profile() -> pd.Series:
    """Uber's own lifetime totals, used to sanity-check the derived figures."""
    df = _read_sql(f"""
        SELECT rating, lifetime_completed_trips, operating_city,
               raw->>'Driver Profile' AS driver_profile,
               signup_date
        FROM driver_profile WHERE upload_id = ({_CURRENT_UPLOAD})
    """)
    return df.iloc[0] if len(df) else pd.Series(dtype="object")


def load_saved_locations() -> pd.DataFrame:
    """Named places, the only human-readable location labels in the export."""
    return _read_sql(f"""
        SELECT label, city, state, latitude AS lat, longitude AS lon
        FROM saved_locations WHERE upload_id = ({_CURRENT_UPLOAD})
    """)


def driver_trips_coverage() -> tuple[int, int]:
    """Rows Uber actually exported vs the trip counter's high-water mark."""
    df = _read_sql(f"""
        SELECT count(*) AS n_rows,
               max((raw->>'driver_trip_number')::numeric) AS max_trip_no
        FROM driver_trips WHERE upload_id = ({_CURRENT_UPLOAD})
    """)
    row = df.iloc[0]
    return int(row["n_rows"]), int(row["max_trip_no"] or 0)


def assign_session_ids(gps: pd.DataFrame) -> pd.DataFrame:
    """Label online pings with the session they belong to.

    Session building and location attribution both depend on where a session
    starts and ends, so that boundary is defined once, here. Segmenting over a
    different subset of pings in either place silently shifts every id.

    Only online pings count: offline pings are the app running in the
    background and would inflate every utilisation figure built on top.
    """
    online = gps[gps["is_online"]].sort_values("ts_local").reset_index(drop=True)

    gap = online["ts_local"].diff()
    raw_id = (gap.isna() | (gap > pd.Timedelta(minutes=cfg.SESSION_GAP_MINUTES))).cumsum()

    span_minutes = online.groupby(raw_id)["ts_local"].agg(
        lambda s: (s.max() - s.min()).total_seconds() / 60.0
    )
    keep = span_minutes[span_minutes >= cfg.MIN_SESSION_MINUTES].index
    renumbered = {old: new for new, old in enumerate(sorted(keep), start=1)}

    online["session_id"] = raw_id.map(renumbered)
    return online.dropna(subset=["session_id"]).astype({"session_id": "int64"})


def build_sessions(gps: pd.DataFrame) -> pd.DataFrame:
    """Aggregate online pings into one row per session."""
    sessions = assign_session_ids(gps).groupby("session_id", as_index=False).agg(
        started_at=("ts_local", "min"),
        ended_at=("ts_local", "max"),
        n_pings=("ts_local", "size"),
        lat_mean=("lat", "mean"),
        lon_mean=("lon", "mean"),
        lat_min=("lat", "min"),
        lat_max=("lat", "max"),
        lon_min=("lon", "min"),
        lon_max=("lon", "max"),
        speed_mean=("speed_gps", "mean"),
        city=("city", "first"),
    )
    sessions["online_minutes"] = (
        sessions["ended_at"] - sessions["started_at"]
    ).dt.total_seconds() / 60.0
    return _add_calendar_features(sessions, "started_at").reset_index(drop=True)


def attach_trips_to_sessions(trips: pd.DataFrame, sessions: pd.DataFrame) -> pd.DataFrame:
    """Label each trip with the online session containing it, if any.

    This timestamp join is the only bridge between earnings (no coordinates)
    and location (no earnings), so it decides how much of the history can be
    analysed spatially at all.
    """
    trips = trips.sort_values("ts_local").reset_index(drop=True)
    sessions = sessions.sort_values("started_at").reset_index(drop=True)

    idx = np.searchsorted(sessions["started_at"].to_numpy(), trips["ts_local"].to_numpy(), side="right") - 1
    matched = pd.Series(pd.NA, index=trips.index, dtype="Int64")

    valid = idx >= 0
    cand = idx[valid]
    within = trips.loc[valid, "ts_local"].to_numpy() <= sessions["ended_at"].to_numpy()[cand]
    matched.loc[trips.index[valid][within]] = sessions["session_id"].to_numpy()[cand][within]

    trips["session_id"] = matched
    trips["has_location"] = trips["session_id"].notna()
    return trips
