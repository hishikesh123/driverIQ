"""Turn GPS pings into locations that mean something.

Raw ping counts measure where the phone sat, not where work happened: the
driver's second-busiest cell is home, and only about a third of online pings
show any movement. Anything ranking locations by ping volume would rank the
couch first, so this module separates productive pings from parked ones.
"""

import pandas as pd

from . import config as cfg
from . import ingest

# Uber writes (0, 0) when it has no fix.
_NULL_ISLAND = 0.01


def assign_cells(gps: pd.DataFrame) -> pd.DataFrame:
    gps = gps.copy()
    gps["cell_lat"] = gps["lat"].round(cfg.GRID_DECIMALS)
    gps["cell_lon"] = gps["lon"].round(cfg.GRID_DECIMALS)
    gps["cell"] = (
        gps["cell_lat"].map(lambda v: f"{v:.2f}") + "," + gps["cell_lon"].map(lambda v: f"{v:.2f}")
    )
    return gps


def _drop_null_island(gps: pd.DataFrame) -> pd.DataFrame:
    return gps[(gps["lat"].abs() > _NULL_ISLAND) | (gps["lon"].abs() > _NULL_ISLAND)]


def derive_home_cell(*consumer_gps: pd.DataFrame) -> str | None:
    """Locate home from the Eats/Rider apps.

    The driver app cannot reveal this on its own — time parked at home looks
    identical to time waiting for an order. Consumer app usage can, because it
    happens at home and almost never during a shift.
    """
    frames = [g for g in consumer_gps if len(g)]
    if not frames:
        return None

    pings = assign_cells(_drop_null_island(pd.concat(frames, ignore_index=True)))
    if pings.empty:
        return None
    return pings["cell"].value_counts().index[0]


def add_location_flags(gps: pd.DataFrame, home_cell: str | None) -> pd.DataFrame:
    """Flag each ping as moving, at home, and productive."""
    gps = assign_cells(gps)
    gps["is_moving"] = gps["speed_gps"].fillna(-1) >= cfg.MOVING_SPEED_MIN
    gps["at_home"] = gps["cell"].eq(home_cell) if home_cell else False
    gps["is_productive"] = gps["is_online"] & gps["is_moving"] & ~gps["at_home"]
    return gps


def cell_activity(gps: pd.DataFrame) -> pd.DataFrame:
    """Per-cell ping profile, contrasting all online time against real driving."""
    online = gps[gps["is_online"]]
    stats = online.groupby("cell", as_index=False).agg(
        online_pings=("is_online", "size"),
        moving_pings=("is_moving", "sum"),
        speed_mean=("speed_gps", "mean"),
        lat=("cell_lat", "first"),
        lon=("cell_lon", "first"),
        at_home=("at_home", "first"),
    )
    stats["moving_share"] = stats["moving_pings"] / stats["online_pings"]
    return stats.sort_values("moving_pings", ascending=False).reset_index(drop=True)


def session_locations(gps: pd.DataFrame, sessions: pd.DataFrame) -> pd.DataFrame:
    """Attach each session's dominant work cell, by productive pings only.

    Attribution is deliberately session-level. A payment timestamp marks
    completion, so a trip's pickup cell is unknowable, but the cell a driver
    actually moved around in during a shift is well evidenced.
    """
    labelled = ingest.assign_session_ids(gps)
    productive = labelled[labelled["is_productive"]]
    if productive.empty:
        return sessions.assign(dominant_cell=pd.NA, cells_visited=0, productive_pings=0)

    per_session = productive.groupby("session_id", as_index=False).agg(
        dominant_cell=("cell", lambda s: s.value_counts().index[0]),
        cells_visited=("cell", "nunique"),
        productive_pings=("cell", "size"),
    )
    return sessions.merge(per_session, on="session_id", how="left")
