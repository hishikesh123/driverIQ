"""Build the DriverIQ marts from Postgres and report what the data supports.

Reads the current export out of Postgres, derives sessions and locations, writes
the analytical marts to data/processed/, and refreshes the data audit.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd

from driveriq import config as cfg
from driveriq import ingest, locations, metrics


def _span(ts: pd.Series) -> str:
    return f"{ts.min():%Y-%m-%d} -> {ts.max():%Y-%m-%d}"


def main() -> None:
    cfg.PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    cfg.REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    payments = ingest.load_payments()
    trips = ingest.build_trips(payments)

    driver_gps = ingest.load_gps("driver")
    eats_gps = ingest.load_gps("eats")
    rider_gps = ingest.load_gps("rider")

    home_cell = locations.derive_home_cell(eats_gps, rider_gps)
    driver_gps = locations.add_location_flags(driver_gps, home_cell)
    cells = locations.cell_activity(driver_gps)

    sessions = ingest.build_sessions(driver_gps)
    trips = ingest.attach_trips_to_sessions(trips, sessions)
    sessions = locations.session_locations(driver_gps, sessions)

    backbone = metrics.time_backbone(trips)
    hourly = metrics.hourly_profile(trips)
    session_stats = metrics.session_metrics(sessions, trips)
    stay_curve = metrics.stay_duration_curve(sessions, trips)
    micro = metrics.micro_location(sessions, trips)
    cube = metrics.location_time_cube(sessions, trips, driver_gps)

    marts = {
        "payments": payments,
        "trips": trips,
        "gps_pings": driver_gps,
        "sessions": session_stats,
        "cell_activity": cells,
        "time_backbone": backbone,
        "hourly_profile": hourly,
        "stay_duration_curve": stay_curve,
        "micro_location": micro,
        "location_time_cube": cube,
    }
    for name, df in marts.items():
        df.to_parquet(cfg.PROCESSED_DIR / f"{name}.parquet", index=False)

    _write_report(
        trips, driver_gps, eats_gps, session_stats, cells, micro, cube, home_cell
    )
    print(f"Wrote {len(marts)} marts to {cfg.PROCESSED_DIR.relative_to(cfg.PROJECT_ROOT)}/")
    print(f"Audit: {(cfg.REPORTS_DIR / 'phase1_data_audit.md').relative_to(cfg.PROJECT_ROOT)}")


def _write_report(trips, driver_gps, eats_gps, sessions, cells, micro, cube, home_cell):
    profile = ingest.load_driver_profile()
    anchors = ingest.load_saved_locations()
    trip_rows, max_trip_no = ingest.driver_trips_coverage()
    located = trips[trips["has_location"]]
    online = driver_gps[driver_gps["is_online"]]
    productive = driver_gps[driver_gps["is_productive"]]

    lines = []
    add = lines.append
    add("# DriverIQ — Data Audit")
    add("")
    add("Source: Postgres (`uber_data`), current upload only. Regenerate with")
    add("`python scripts/run_phase1.py`.")
    add("")

    add("## Earnings history — the backbone")
    add(f"- Trips: {len(trips):,} (from {int(trips['n_payment_lines'].sum()):,} payment lines)")
    add(f"- Date span: {_span(trips['ts_local'])} ({trips['date'].nunique():,} active days)")
    add(f"- Total earnings: ${trips['earnings'].sum():,.2f} {trips['currency'].iloc[0]}")
    add(f"- Tips: ${trips['tips'].sum():,.2f} across {int((trips['tips'] > 0).sum()):,} trips")
    add(f"- Median trip: ${trips['earnings'].median():.2f}")
    if len(profile):
        add(f"- Uber's own lifetime count: {int(profile['lifetime_completed_trips']):,} completed, "
            f"rating {profile['rating']}, profile {profile['driver_profile']} "
            f"({profile['operating_city']})")
        add(f"  The {len(trips):,} paid trips exceed the "
            f"{int(profile['lifetime_completed_trips']):,} completed ones because "
            "cancellations and adjustments are also paid.")
    add("")

    add("## Location history — one month only")
    add(f"- Driver GPS pings: {len(driver_gps):,} ({len(online):,} online)")
    add(f"- Date span: {_span(driver_gps['ts_local'])} "
        f"({driver_gps['date'].nunique():,} days)")
    add(f"- Productive pings (online, moving, not at home): {len(productive):,} "
        f"— {100 * len(productive) / len(online):.1f}% of online time")
    add("")

    add("## Home, and why it matters")
    if home_cell:
        eats_cells = locations.assign_cells(eats_gps)
        share = 100 * eats_cells["cell"].eq(home_cell).mean()
        add(f"- Home cell `{home_cell}`, identified from the Eats/Rider consumer apps "
            f"({share:.1f}% of Eats pings sit in it).")

        matches = cells.index[cells["cell"] == home_cell]
        if len(matches):
            home_row = cells.loc[matches[0]]
            add(f"- In the *driver* app that same cell holds "
                f"{int(home_row['online_pings']):,} online pings but only "
                f"{home_row['moving_share']:.0%} moving. It sits #"
                f"{cells.index.get_loc(matches[0]) + 1} of {len(cells)} cells by real "
                "driving activity, yet #"
                f"{cells.sort_values('online_pings', ascending=False).index.get_loc(matches[0]) + 1} "
                "by raw online pings — the gap between those two ranks is the whole problem.")
    add("- Consequence: ping volume measures where the phone rested, not where work")
    add("  happened. Locations are therefore ranked by productive pings and by")
    add("  earnings, never by raw ping counts.")
    if len(anchors):
        a = anchors.iloc[0]
        add(f"- Named anchor from saved locations: \"{a['label']}\" — {a['city']} "
            f"({a['lat']:.4f}, {a['lon']:.4f}).")
    add("")

    add("## Coverage limit — the constraint that shapes the project")
    add(f"- Trips with any location: {len(located):,} of {len(trips):,} "
        f"({100 * len(located) / len(trips):.1f}%)")
    add(f"- Earnings with location: ${located['earnings'].sum():,.2f} of "
        f"${trips['earnings'].sum():,.2f}")
    add(f"- Sessions: {len(sessions):,}, {sessions['online_minutes'].sum() / 60:,.1f} h online, "
        f"median {sessions['online_minutes'].median():.0f} min")
    if len(micro):
        top = micro.iloc[0]
        add(f"- Dominant work cell `{top['dominant_cell']}` accounts for "
            f"{int(top['sessions'])} of {int(micro['sessions'].sum())} sessions.")
    add("")
    add("Earnings carry no coordinates and GPS carries no earnings, so the two are joined")
    add("on time. That limits location-aware analysis to the single month the app-analytics")
    add("export covers, while time-of-day analysis uses the full two years. And because")
    add("almost every session shares one dominant cell, comparing one area against another")
    add("is not supportable — the project reports timing first and location as a")
    add("sample-size-flagged micro-layer.")
    add("")
    add("Online time exists only inside the GPS month, so **earnings per hour is not")
    add("computable across the full history**. Layer 1 measures per trip and per active")
    add("day; per hour appears only in the session layer.")
    add("")

    add("## Location x Day x Time Window (README section 6)")
    add("")
    if len(cube):
        counts = cube["confidence"].value_counts()
        add(f"- Non-empty cells: {len(cube)}, built from {len(located)} located trips")
        add(f"- Median trips per cell: {cube['trips'].median():.0f}")
        add("- Confidence: " + ", ".join(
            f"{counts.get(band, 0)} {band}"
            for band in ("high", "moderate", "low", "insufficient")
        ))
        best = cube.nlargest(3, "trips")
        add("")
        add("| Cell | Day | Window | Trips | Earnings | $/h | Confidence |")
        add("|---|---|---|---|---|---|---|")
        for r in best.itertuples():
            add(f"| `{r.dominant_cell}` | {r.day_of_week} | {r.time_window} | "
                f"{int(r.trips)} | ${r.earnings:,.2f} | ${r.earnings_per_hour:.2f} | "
                f"{r.confidence} |")
        add("")
        add("This is the unit the README treats as central, and it is the weakest thing")
        add("in the project. Most cells rest on single-digit trip counts, so the")
        add("confidence column is load-bearing rather than decorative. Read it as a")
        add("demonstration of the method, not as a basis for choosing where to drive.")
    add("")
    add("### Utilisation is a proxy, not the real thing")
    add("`Driver Status` is blank in all 144,951 pings, so active-versus-idle time")
    add("cannot be read and true utilisation (active / online) is not computable.")
    add("`moving_share_proxy` reports the share of online pings showing movement")
    add("instead. It is named as a proxy so it is never mistaken for utilisation.")
    add("")

    add("## Layers and what each can carry")
    add("")
    add("| Layer | Evidence | Answers |")
    add("|---|---|---|")
    add(f"| 1 — time | {len(trips):,} trips, {trips['date'].nunique()} days, 2 years | when to drive |")
    add(f"| 2 — session | {len(sessions)} sessions, {sessions['online_minutes'].sum() / 60:.0f} h | how long to stay |")
    add(f"| 3 — micro-location | {len(located)} trips, {len(micro)} dominant cells, 1 month | which part of the zone |")
    add("")

    add("## Unusable sources")
    add(f"- `driver_lifetime_trips`: {trip_rows} rows exported, but the trip counter reaches "
        f"{max_trip_no:,} — Uber omitted nearly all trip detail (distance, duration, surge, "
        "pickup/dropoff). This is the single biggest loss; it is why locations must be "
        "inferred from GPS pings at all.")
    add("- `Driver Status` in app analytics: blank in every row, so on-trip versus idle "
        "cannot be read directly. Utilisation is inferred from movement instead.")
    add("- Eats/Rider trips, orders, ratings, support tickets and communications describe "
        "this person as a customer, not a driver. The two consumer GPS streams are kept "
        "only to locate home, as above.")

    (cfg.REPORTS_DIR / "phase1_data_audit.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
