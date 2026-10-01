"""Build the deployment-safe copy of the marts.

The full marts locate the driver: cell_activity carries their home cell, the
session table carries per-shift bounding boxes, and gps_pings is 145k exact
coordinates with timestamps. A public portfolio link must not publish any of
that. This writes data/public/ containing work-zone geography only, which is
what the deployed app reads.

Recorded LLM answers are written here too, so the hosted app can show what the
Phase 6 layer produces — Ollama does not exist on Streamlit Cloud.
"""

import json
import shutil
from pathlib import Path


import pandas as pd

from driveriq import config as cfg

PUBLIC_DIR = cfg.PROJECT_ROOT / "data" / "public"

# Safe as-is: no coordinates in any of these.
COPY_AS_IS = [
    "trips", "hourly_profile", "time_backbone", "location_time_cube",
    "micro_location", "stay_duration_curve", "expected_earnings",
    "model_scores", "model_feature_importance", "window_rankings",
]

# Never published: exact positions, and far too large besides.
EXCLUDED = ["gps_pings", "payments"]

# Session bounding boxes would re-expose the home cell a shift started in.
SESSION_DROP = ["lat_mean", "lon_mean", "lat_min", "lat_max", "lon_min", "lon_max"]


def main() -> None:
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    written = []

    for name in COPY_AS_IS:
        source = cfg.PROCESSED_DIR / f"{name}.parquet"
        if not source.exists():
            continue
        shutil.copy(source, PUBLIC_DIR / f"{name}.parquet")
        written.append(name)

    cells = pd.read_parquet(cfg.PROCESSED_DIR / "cell_activity.parquet")
    work_only = cells[~cells["at_home"]].drop(columns=["at_home"])
    work_only.to_parquet(PUBLIC_DIR / "cell_activity.parquet", index=False)
    written.append(f"cell_activity ({len(cells)} -> {len(work_only)} cells, home removed)")

    sessions = pd.read_parquet(cfg.PROCESSED_DIR / "sessions.parquet")
    sessions.drop(columns=[c for c in SESSION_DROP if c in sessions], errors="ignore") \
        .to_parquet(PUBLIC_DIR / "sessions.parquet", index=False)
    written.append("sessions (bounding boxes dropped)")

    _verify()
    for name in written:
        print(f"  {name}")
    print(f"\nWrote {len(written)} marts to {PUBLIC_DIR.relative_to(cfg.PROJECT_ROOT)}/")
    print(f"Excluded entirely: {', '.join(EXCLUDED)}")


def _verify() -> None:
    """Fail loudly rather than publish a coordinate that should not be public."""
    home = pd.read_parquet(cfg.PROCESSED_DIR / "cell_activity.parquet")
    home_cells = set(home.loc[home["at_home"], "cell"])

    for path in PUBLIC_DIR.glob("*.parquet"):
        frame = pd.read_parquet(path)
        if "cell" in frame.columns and home_cells & set(frame["cell"].dropna()):
            raise SystemExit(f"ABORT: {path.name} still contains the home cell")
        leaked = [c for c in frame.columns if c in SESSION_DROP]
        if leaked:
            raise SystemExit(f"ABORT: {path.name} still has coordinates {leaked}")

    for name in EXCLUDED:
        if (PUBLIC_DIR / f"{name}.parquet").exists():
            raise SystemExit(f"ABORT: {name} must never be published")


def save_recorded_answers(results: list[dict]) -> Path:
    """Persist locally-generated LLM answers for the hosted app to replay."""
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    payload = [
        {"question": r["question"], "answer": r["answer"], "source": r.get("source")}
        for r in results if r.get("source") in {"llm", "canned"}
    ]
    path = PUBLIC_DIR / "recorded_answers.json"
    path.write_text(json.dumps(payload, indent=2))
    return path


if __name__ == "__main__":
    main()
