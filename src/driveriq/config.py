import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
REPORTS_DIR = PROJECT_ROOT / "reports"

# Postgres is the system of record; this layer only reads from it.
DB_DSN = os.environ.get("UBER_DB_DSN", "postgresql://uber:uber@localhost:5432/uber_data")

# All driver activity in this export is Melbourne. Postgres stores true instants,
# so every timestamp is converted to the driver's own clock exactly once, here.
TZ = "Australia/Melbourne"

# Payment lines are per-component (base fare, tip, adjustment), so trip earnings
# only make sense after summing every line sharing a Trip UUID.
TIP_CLASSIFICATIONS = {"transport.misc.tip"}

# A gap this long between GPS pings means the driver closed the app or stopped
# working; it separates one online session from the next.
SESSION_GAP_MINUTES = 30

# Sessions shorter than this are app-open noise rather than real driving.
MIN_SESSION_MINUTES = 5

# Below this the driver is parked, not driving. Offline pings report negative
# speed as a "no fix" sentinel, which this also excludes.
MOVING_SPEED_MIN = 0.5

# ~1.1km of latitude at this longitude. Coarse enough that a single GPS jump
# does not invent a new location, fine enough to separate suburbs.
GRID_DECIMALS = 2

# A trip is evidence; a location claim resting on a handful of them is not.
# Reported alongside every aggregate so thin cells cannot masquerade as signal.
CONFIDENCE_BANDS = [(30, "high"), (10, "moderate"), (3, "low")]

TIME_WINDOWS = [
    ("morning", 6, 9),
    ("late_morning", 9, 12),
    ("lunch", 12, 14),
    ("afternoon", 14, 17),
    ("evening_peak", 17, 20),
    ("night", 20, 23),
    ("overnight", 23, 6),
]
