# DriverIQ — Data Audit

Source: Postgres (`uber_data`), current upload only. Regenerate with
`python scripts/run_phase1.py`.

## Earnings history — the backbone
- Trips: 4,881 (from 5,042 payment lines)
- Date span: 2024-08-08 -> 2026-08-24 (383 active days)
- Total earnings: $35,828.47 AUD
- Tips: $553.69 across 149 trips
- Median trip: $6.50
- Uber's own lifetime count: 4,683 completed, rating 5.0, profile Logistics (Melbourne)
  The 4,881 paid trips exceed the 4,683 completed ones because cancellations and adjustments are also paid.

## Location history — one month only
- Driver GPS pings: 144,951 (134,221 online)
- Date span: 2026-07-24 -> 2026-08-23 (28 days)
- Productive pings (online, moving, not at home): 46,981 — 35.0% of online time

## Home, and why it matters
- Home cell `-37.63,145.08`, identified from the Eats/Rider consumer apps (98.1% of Eats pings sit in it).
- In the *driver* app that same cell holds 6,756 online pings but only 16% moving. It sits #10 of 32 cells by real driving activity, yet #5 by raw online pings — the gap between those two ranks is the whole problem.
- Consequence: ping volume measures where the phone rested, not where work
  happened. Locations are therefore ranked by productive pings and by
  earnings, never by raw ping counts.
- Named anchor from saved locations: "work" — Melbourne CBD (-37.8090, 144.9651).

## Coverage limit — the constraint that shapes the project
- Trips with any location: 257 of 4,881 (5.3%)
- Earnings with location: $1,785.52 of $35,828.47
- Sessions: 34, 99.4 h online, median 184 min
- Dominant work cell `-37.65,145.07` accounts for 27 of 33 sessions.

Earnings carry no coordinates and GPS carries no earnings, so the two are joined
on time. That limits location-aware analysis to the single month the app-analytics
export covers, while time-of-day analysis uses the full two years. And because
almost every session shares one dominant cell, comparing one area against another
is not supportable — the project reports timing first and location as a
sample-size-flagged micro-layer.

Online time exists only inside the GPS month, so **earnings per hour is not
computable across the full history**. Layer 1 measures per trip and per active
day; per hour appears only in the session layer.

## Location x Day x Time Window (README section 6)

- Non-empty cells: 42, built from 257 located trips
- Median trips per cell: 4
- Confidence: 1 high, 8 moderate, 14 low, 19 insufficient

| Cell | Day | Window | Trips | Earnings | $/h | Confidence |
|---|---|---|---|---|---|---|
| `-37.65,145.07` | Thursday | evening_peak | 30 | $204.52 | $24.30 | high |
| `-37.65,145.07` | Wednesday | evening_peak | 25 | $179.26 | $20.60 | moderate |
| `-37.65,145.07` | Friday | lunch | 18 | $135.73 | $20.67 | moderate |

This is the unit the README treats as central, and it is the weakest thing
in the project. Most cells rest on single-digit trip counts, so the
confidence column is load-bearing rather than decorative. Read it as a
demonstration of the method, not as a basis for choosing where to drive.

### Utilisation is a proxy, not the real thing
`Driver Status` is blank in all 144,951 pings, so active-versus-idle time
cannot be read and true utilisation (active / online) is not computable.
`moving_share_proxy` reports the share of online pings showing movement
instead. It is named as a proxy so it is never mistaken for utilisation.

## Layers and what each can carry

| Layer | Evidence | Answers |
|---|---|---|
| 1 — time | 4,881 trips, 383 days, 2 years | when to drive |
| 2 — session | 34 sessions, 99 h | how long to stay |
| 3 — micro-location | 257 trips, 3 dominant cells, 1 month | which part of the zone |

## Unusable sources
- `driver_lifetime_trips`: 4 rows exported, but the trip counter reaches 2,898 — Uber omitted nearly all trip detail (distance, duration, surge, pickup/dropoff). This is the single biggest loss; it is why locations must be inferred from GPS pings at all.
- `Driver Status` in app analytics: blank in every row, so on-trip versus idle cannot be read directly. Utilisation is inferred from movement instead.
- Eats/Rider trips, orders, ratings, support tickets and communications describe this person as a customer, not a driver. The two consumer GPS streams are kept only to locate home, as above.
