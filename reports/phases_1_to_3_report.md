# DriverIQ — Phases 1–3 Report

**What this covers:** the data foundation (Phase 1), the analytical layers (Phase 2)
and the visualisations (Phase 3), plus what the data did and did not turn out to
support. Written for someone opening this repo without having seen the raw export.

**Source data:** one Melbourne bike-courier's personal Uber "Download Your Data"
export, Aug 2024 – Aug 2026.

---

## 1. Summary

The project set out to answer *"where should I drive, when, and what can I expect
to earn?"* After auditing the export, only the **when** is answerable with
confidence. The **where** is not, for two reasons that no amount of modelling can
fix: earnings records carry no coordinates, and the GPS that does carry them covers
only one month — during which the driver worked essentially one location.

The project was therefore reordered **time-first**, with location demoted to a
sample-size-flagged micro-layer. That is a finding about the data, not a failure of
the analysis, and the reporting is built so the thin layers cannot be mistaken for
the strong one.

**Headline numbers**

| Metric | Value |
|---|---|
| Trips | 4,881 |
| Total earnings | $35,828.47 AUD |
| Period | 2024-08-08 → 2026-08-24 (383 active days) |
| Earnings per active day | $93.55 |
| Median trip | $6.50 |
| Tips | $553.69 across 149 trips (3.1% of trips) |
| Trips with any location | 257 (5.3%) |
| Reconstructed GPS sessions | 34, totalling 99.4 online hours |
| Earnings per online hour (GPS month only) | $17.96 |

---

## 2. What Uber actually provided

The export contains 16 CSVs. Six carry analytical weight; ten do not.

### Files that matter

| File | Rows | What it gives |
|---|---|---|
| `Driver/driver_payments-0.csv` | 5,042 lines → 4,881 trips | Earnings spine. Timestamp, amount, tip flag — **city only, no coordinates** |
| `Driver/driver_app_analytics-0.csv` | 144,951 pings | The only driving location source. Lat/lon, online flag, speed — **no earnings** |
| `Eats/eats_app_analytics-0.csv` | 22,665 pings | 98.1% in one cell → identifies **home** |
| `Rider/rider_app_analytics-0.csv` | 3,411 pings | 0% overlap with driving sessions → corroborates home |
| `Account and Profile/rider_eater_saved_locations.csv` | 1 | Named anchor ("work" = La Trobe St, Melbourne CBD) |
| `Account and Profile/driver_profile-0.csv` | 1 | Validation baseline: 4,683 lifetime trips, rating 5.0, profile *Logistics* |

The two consumer-app files deserve emphasis. They look irrelevant — this person as a
*customer*, not a driver — and were nearly discarded. They turned out to be the only
way to locate home, which is load-bearing (§4.2).

### Files that do not

- **`driver_lifetime_trips-0.csv` — the single biggest loss.** Uber exported **4 rows**
  while the file's own `driver_trip_number` column reaches **2,898**. Trip distance,
  duration, surge, pickup and dropoff are therefore unavailable for essentially every
  trip. This is *why* location has to be inferred from raw GPS pings at all.
- **`Driver Status`** — present as a column, blank in all 144,951 rows. On-trip versus
  idle cannot be read, so true utilisation is not computable (§5.3).
- Eats orders, rider trips, ratings, support tickets, communications, payment methods —
  all describe consumer activity. `communications_sent` was checked specifically in case
  it held earnings incentives; it holds chat messages from couriers.

---

## 3. Phase 1 — Data foundation

Postgres is the system of record; pandas reads from it into Parquet marts
(`data/processed/`). All 16 CSVs load, including the ones only used for validation.

### 3.1 A timezone defect that had corrupted every earnings figure

The pre-existing loader parsed `driver_payments."Local Timestamp"` with `utc=True`.
That column is naive **Melbourne wall-clock**, so every payment was relabelled as UTC
and shifted forward 10–11 hours.

The effect was not subtle. Hour-of-day earnings peaked at **3–5 am** — nonsense for a
food courier. After the fix the same data peaks at **12:00 and 18:00**, the expected
bimodal lunch/dinner shape.

| | Before | After |
|---|---|---|
| Last payment in export | 23:18 | **13:18** |
| Busiest hour | 04:00 | **18:00** |

This is worth recording because it would have silently invalidated the entire
time-based analysis — the layer the project now rests on — while looking like clean
data throughout. Timestamp parsing is now split: `to_ts` for genuinely-UTC columns,
`to_ts_local` for naive local ones, with DST edges resolved by keeping the row.

### 3.2 Other Phase 1 work

- **Typed columns.** `Is Driver Online?` and `Speed (GPS)` were reachable only inside a
  `raw` JSONB blob. Both are central — one drives session reconstruction, the other
  separates driving from a parked phone — so both were promoted to typed columns.
- **Idempotency.** The loader duplicated all 171k rows on every run. `uploads` gained
  `UNIQUE (user_id, source_label)` and an `is_current` marker; re-importing now reuses
  the same `upload_id` and replaces its rows via scoped deletes. The multi-tenant
  `users`/`uploads` layer was kept deliberately, to leave the multi-driver path open.
- **Indexes** for the real access patterns: geo, BRIN over event time, `trip_uuid`,
  `category`.

### 3.3 Derived structures

- **Trips** — payment lines summed per `trip_uuid`. A trip is dated by its *earliest*
  line, because tips and adjustments can land hours later and would otherwise misdate it.
- **Sessions** — online pings segmented on a 30-minute gap, with a 5-minute floor.
  Offline pings are excluded: they are the app running in the background and would
  inflate every utilisation figure built on top. 34 sessions, 99.4 hours.
- **The time join** — earnings have no coordinates and GPS has no earnings, so trips are
  matched to sessions by timestamp. This bridge is what caps location coverage at 5.3%.

---

## 4. Phase 2 — Analytical layers

Three layers, ordered by how much evidence each carries. Every aggregate ships with a
sample size and a confidence band.

| Layer | Evidence | Answers |
|---|---|---|
| 1 — Time | 4,881 trips, 383 days, 2 years | when to drive |
| 2 — Session | 34 sessions, 99.4 h | how long to stay out |
| 3 — Micro-location | 257 trips, 42 cells, 1 month | which part of the zone |

### 4.1 Attribution is session-level, not trip-level

A payment timestamp marks trip *completion*, so the pickup location of any individual
trip is unknowable. A session, by contrast, has a well-evidenced dominant work cell.
Location is therefore attributed per session.

Relatedly, location confidence is graded on **sessions, not trips**: trips within one
shift are correlated, so an independent visit is the real unit of evidence.

### 4.2 Home had to be excluded, and only the consumer apps could find it

Raw ping volume measures where the *phone* sat, not where work happened. Only **35% of
online pings show any movement** (46,981 of 134,221).

The driver's own home sits at cell `-37.63,145.08`. In the driver app it holds 6,756
online pings at just **16% moving** — ranking **5th by raw online pings but 10th by
actual driving**. Ranking locations by ping count would have put the driver's couch
near the top of the list.

The driver app cannot distinguish home from a legitimate waiting spot; both look like a
stationary phone. The consumer apps can, because that usage happens at home and almost
never during a shift — 98.1% of Eats pings fall in that one cell, and 0% of rider pings
fall inside a driving session.

### 4.3 Time splitting

Sessions average about three hours and straddle several time windows, so each session's
online span is split minute-by-minute across windows. Charging a whole session to the
window it began in would have inflated evening peak with time that belonged to lunch
and afternoon.

---

## 5. Findings

### 5.1 Earnings come from volume, not from better-paid trips

Earnings per trip is remarkably flat across the working day — **$6.97 to $7.93** across
every hour with meaningful volume. The peaks are peaks because more trips happen, not
because trips pay more.

| Hour | Trips | Earnings | Per trip |
|---|---|---|---|
| 18:00 | 844 | $6,077.10 | $7.20 |
| 17:00 | 706 | $5,150.66 | $7.30 |
| 12:00 | 630 | $4,678.48 | $7.43 |

**Implication:** any earnings model should target **trips per hour**, not dollars per
trip. Dollars per trip is close to a constant for this driver and has little to predict.

### 5.2 The best windows, on two years of evidence

34 of 35 day × window cells reach high confidence, so this is the solid ground.

| Day | Window | Trips | Earnings | Per active day |
|---|---|---|---|---|
| Friday | evening peak | 397 | $2,850.15 | **$52.78** |
| Thursday | evening peak | 377 | $2,634.92 | $52.70 |
| Saturday | evening peak | 313 | $2,271.92 | $49.39 |

Evening peak leads on every day of the week. Afternoon is consistently the weakest
working window.

### 5.3 Productivity falls off after about three hours out

Bucketing trips by how far into a session they occurred, against how many sessions were
still online at that point:

| Hour into session | Trips | Trips per session-hour | Sessions still online | Confidence |
|---|---|---|---|---|
| 0 | 74 | 2.18 | 34 | high |
| 1 | 104 | **3.15** | 33 | high |
| 2 | 70 | 2.33 | 30 | high |
| 3 | 9 | 0.50 | 18 | low |

Productivity peaks in the *second* hour, holds through the third, then drops sharply.
The fourth-hour figure rests on 9 trips and should be treated as a hint.

Note this is a rate of trips, not true utilisation. Because `Driver Status` is blank in
every row, active-versus-idle time cannot be read at all; the marts report a
movement-based `moving_share_proxy` instead, named so it cannot be mistaken for the
real metric.

### 5.4 The location comparison the project was designed around is not answerable

- Only **257 of 4,881 trips (5.3%)** have any location — $1,785.52 of $35,828.47.
- **27 of 33** located sessions share one dominant cell.
- **99% of all real driving falls within 3 km of a single point**; the cells holding 95%
  of movement span roughly 4.4 × 4.4 km.

There is no second area to compare the first against. "Area A beats Area B on Friday
evening" cannot be supported, and the project does not claim it.

### 5.5 The Location × Day × Time Window cube is thin by construction

Built anyway, because it is the README's stated core unit — and reported with its
weakness visible:

| Confidence | Cells |
|---|---|
| high | **1** |
| moderate | 8 |
| low | 14 |
| insufficient | 19 |

42 cells, median 4 trips each. Only 9 (21%) reach moderate or better. The single
high-confidence cell is Thursday evening peak in the main zone: 30 trips, $24.30/hour.

### 5.6 An untestable hint worth recording

The two minor cells show *higher* earnings per hour than the main working zone:

| Cell | Sessions | Trips | $/hour | Confidence |
|---|---|---|---|---|
| `-37.66,145.08` | 2 | 24 | **$22.15** | insufficient |
| `-37.65,145.07` (main) | 27 | 204 | $18.27 | moderate |
| `-37.65,145.08` | 4 | 29 | $14.63 | low |

They also show higher movement share (0.45–0.48 versus 0.33–0.42). This is exactly the
kind of thing the project was meant to surface — but on 2 and 4 sessions it is a
**hypothesis to test by driving there**, not a finding to act on.

### 5.7 Three hours of online time earned nothing

Nine cube cells hold online time and zero trips — 3.1 hours total, concentrated in
afternoon and night windows. Consistent with afternoon being the weakest window across
the full two years.

---

## 6. Phase 3 — Visualisation

`reports/phase3_report.html`, generated by `scripts/run_phase3.py`. Four charts, each
labelled with the evidence behind it, plus a KPI row.

1. **Earnings by time of day** — 2 years. The bimodal shape, and the flat per-trip rate.
2. **Earnings by location** — plots the *rate*, not the total, so a location is not
   rewarded merely for being stood in longer. Labelled with sessions and trips.
3. **Location × day × time window** — colour carries earnings per hour **only where at
   least 10 trips support it**; thinner windows are flat grey tiles showing their trip
   count. Absence of evidence reads as absence of colour rather than as a low value.
4. **Where the driving happened** — Leaflet map, cells sized by *moving* pings, home
   marked and excluded.

Design notes: single sequential blue hue for magnitude (no rainbow, no value-ramp on
categories), palette validated for colour-blind separation in both light and dark modes,
every chart has a table-view twin so no value is reachable only by hover, and the home
marker carries a text label so identity never rests on colour alone.

Two implementation notes for whoever maintains this:

- **plotly.js 4.1.1 silently fails to render `scattermap` markers.** The traces exist
  and stay hoverable, but the MapLibre instance reports only the tile layer — the scatter
  layers are never added. Chart 4 therefore uses Folium/Leaflet, which renders tiles as
  images and markers as SVG and needs no WebGL.
- **CartoDB basemaps now require an API key**, so the map uses plain OpenStreetMap.
  That card needs an internet connection; the other three charts are self-contained.

---

## 7. How to read these numbers

- These are **historical estimates from one driver's own records**. They describe what
  happened; they say nothing about current demand, driver supply, incentives or surge.
- **Earnings per hour is not computable before the GPS month.** Online time only exists
  for those 28 days, so the two-year layer reports per trip and per active day. Any
  $/hour figure in this report comes from the 34-session window.
- **Utilisation is a proxy.** See §5.3.
- **Sample size is not a footnote here.** The difference between the Layer 1 numbers
  (thousands of trips) and the Layer 3 numbers (single digits per cell) is roughly three
  orders of magnitude. The confidence column exists to stop them being read alike.
- The 4,881 paid trips exceed Uber's own count of 4,683 completed trips because
  cancellations and adjustments are also paid.

---

## 8. Reproducing

```bash
docker compose up -d                                  # in "Uber Data/"
python "Uber Data/db/load_data.py" \
    --email <you> --data-dir "Uber Data" --label "Sep 2026 export"
python scripts/run_phase1.py     # marts + reports/phase1_data_audit.md
python scripts/run_phase3.py     # reports/phase3_report.html
```

The loader is idempotent — re-running replaces the export in place rather than
duplicating it. Key reconciliation checks: `SUM(local_amount)` must equal **35828.47**,
and trips must peak in `evening_peak` (2,145 trips). If that peak moves, the timezone
handling has regressed.

---

## 9. What comes next

Phase 4 is the earnings model. Given §5.1, the target should be **trips per hour** for a
location-time window rather than dollars per trip — the latter is close to constant and
has little signal to offer. Phases 5–7 (recommendation engine, local LLM via Ollama,
Streamlit) follow from there.

The honest framing for the finished product is a **timing** decision-support tool with
location as supporting context — not the location-comparison engine originally
envisioned, which this export cannot support.
