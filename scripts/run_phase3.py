"""Phase 3 — render the visualisation report from the Phase 1/2 marts."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd

from driveriq import config as cfg
from driveriq import viz

OUT = "phase3_report.html"

STYLE = """
:root {
  color-scheme: light;
  --surface: #fcfcfb; --page: #f9f9f7; --ink: #0b0b0b; --ink2: #52514e;
  --muted: #898781; --grid: #e1e0d9; --border: rgba(11,11,11,0.10);
  --accent: #2a78d6;
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --surface: #1a1a19; --page: #0d0d0d; --ink: #ffffff; --ink2: #c3c2b7;
  --muted: #898781; --grid: #2c2c2a; --border: rgba(255,255,255,0.10);
  --accent: #3987e5;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
    --surface: #1a1a19; --page: #0d0d0d; --ink: #ffffff; --ink2: #c3c2b7;
    --muted: #898781; --grid: #2c2c2a; --border: rgba(255,255,255,0.10);
    --accent: #3987e5;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--page); color: var(--ink);
  font: 15px/1.6 system-ui, -apple-system, "Segoe UI", sans-serif;
  padding: 32px 16px 64px;
}
.wrap { max-width: 1060px; margin: 0 auto; }
header { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; }
h1 { font-size: 24px; margin: 0 0 4px; letter-spacing: -0.01em; }
.sub { color: var(--ink2); font-size: 14px; margin: 0 0 28px; }
#theme {
  background: var(--surface); color: var(--ink2); border: 1px solid var(--border);
  border-radius: 8px; padding: 7px 13px; font: inherit; font-size: 13px; cursor: pointer;
  white-space: nowrap;
}
.kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 12px; margin-bottom: 30px; }
.kpi { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 15px 17px; }
.kpi .v { font-size: 27px; font-weight: 600; letter-spacing: -0.02em; }
.kpi .v.text { font-size: 19px; line-height: 1.25; padding: 4px 0; }
.kpi .k { font-size: 12px; color: var(--muted); margin-top: 3px; }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 14px; padding: 20px 22px 16px; margin-bottom: 20px; }
.card h2 { font-size: 16px; margin: 0 0 3px; }
.card .note { font-size: 13px; color: var(--ink2); margin: 0 0 16px; }
.flag { display: inline-block; font-size: 11px; padding: 2px 8px; border-radius: 99px;
        border: 1px solid var(--border); color: var(--muted); margin-left: 8px; vertical-align: 2px; }
details { margin-top: 12px; border-top: 1px solid var(--border); padding-top: 10px; }
summary { cursor: pointer; font-size: 13px; color: var(--ink2); }
table { border-collapse: collapse; width: 100%; margin-top: 12px; font-size: 12px;
        font-variant-numeric: tabular-nums; }
th, td { text-align: right; padding: 5px 9px; border-bottom: 1px solid var(--grid); }
th:first-child, td:first-child { text-align: left; }
th { color: var(--muted); font-weight: 500; }
footer { color: var(--muted); font-size: 12px; margin-top: 28px; }
.maplegend { display: flex; align-items: center; gap: 7px; font-size: 12px;
             color: var(--muted); margin-bottom: 11px; flex-wrap: wrap; }
.maplegend i { display: inline-block; width: 104px; height: 9px; border-radius: 99px; }
.maplegend .sep { opacity: 0.5; }
.folium-map, .maplegend + div iframe { border-radius: 10px; }
@media (max-width: 640px) { body { padding: 20px 12px 48px; } .card { padding: 16px 14px 12px; } }
"""

SCRIPT = """
const root = document.documentElement;
const btn = document.getElementById('theme');
const DARK = { ink2:'#c3c2b7', muted:'#898781', grid:'#2c2c2a', axis:'#383835',
               unmeasured:'#2c2c2a', surface:'#1a1a19' };
const LIGHT = { ink2:'#52514e', muted:'#898781', grid:'#e1e0d9', axis:'#c3c2b7',
                unmeasured:'#e6e5e0', surface:'#fcfcfb' };

function isDark() {
  const stamp = root.getAttribute('data-theme');
  if (stamp) return stamp === 'dark';
  return window.matchMedia('(prefers-color-scheme: dark)').matches;
}

function paint() {
  const t = isDark() ? DARK : LIGHT;
  btn.textContent = isDark() ? 'Light' : 'Dark';
  document.querySelectorAll('.js-plotly-plot').forEach(function (d) {
    const up = {
      'font.color': t.ink2,
      'xaxis.linecolor': t.axis, 'xaxis.tickfont.color': t.muted,
      'yaxis.gridcolor': t.grid, 'yaxis.tickfont.color': t.muted
    };
    // Faceted figures carry axis2..axisN; mirror the same tokens onto each.
    Object.keys(d.layout || {}).forEach(function (k) {
      if (/^xaxis\\d+$/.test(k)) { up[k + '.linecolor'] = t.axis; up[k + '.tickfont.color'] = t.muted; }
      if (/^yaxis\\d+$/.test(k)) { up[k + '.gridcolor'] = t.grid; up[k + '.tickfont.color'] = t.muted; }
    });
    (d.layout.annotations || []).forEach(function (_, i) {
      up['annotations[' + i + '].font.color'] = t.ink2;
    });
    Plotly.relayout(d, up);
    (d.data || []).forEach(function (tr, i) {
      if (tr.meta === 'unmeasured') {
        Plotly.restyle(d, { colorscale: [[[0, t.unmeasured], [1, t.unmeasured]]] }, [i]);
      }
      // Separator rings are drawn in the surface colour, so they have to follow it.
      if (tr.marker && tr.marker.line && tr.marker.line.width) {
        Plotly.restyle(d, { 'marker.line.color': t.surface }, [i]);
      }
    });
  });
}

btn.addEventListener('click', function () {
  root.setAttribute('data-theme', isDark() ? 'light' : 'dark');
  paint();
});
window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', paint);
window.addEventListener('load', paint);
"""


def _table(df: pd.DataFrame, cols: dict, limit: int = 60) -> str:
    """Every chart gets a readable twin, so no value is reachable only by hover."""
    head = "".join(f"<th>{label}</th>" for label in cols.values())
    rows = []
    for r in df.head(limit)[list(cols)].itertuples(index=False):
        cells = "".join(
            f"<td>{v:,.2f}</td>" if isinstance(v, float) else f"<td>{v}</td>" for v in r
        )
        rows.append(f"<tr>{cells}</tr>")
    return (
        "<details><summary>Table view</summary><table><thead><tr>"
        f"{head}</tr></thead><tbody>{''.join(rows)}</tbody></table></details>"
    )


def _card(title: str, note: str, flag: str, fig_html: str, table_html: str) -> str:
    chip = f'<span class="flag">{flag}</span>' if flag else ""
    return (
        f'<section class="card"><h2>{title}{chip}</h2>'
        f'<p class="note">{note}</p>{fig_html}{table_html}</section>'
    )


def main() -> None:
    d = cfg.PROCESSED_DIR
    trips = pd.read_parquet(d / "trips.parquet")
    hourly = pd.read_parquet(d / "hourly_profile.parquet")
    sessions = pd.read_parquet(d / "sessions.parquet")
    micro = pd.read_parquet(d / "micro_location.parquet")
    cube = pd.read_parquet(d / "location_time_cube.parquet")
    cells = pd.read_parquet(d / "cell_activity.parquet")
    backbone = pd.read_parquet(d / "time_backbone.parquet")

    home_cell = cells.loc[cells["at_home"], "cell"]
    home_cell = home_cell.iloc[0] if len(home_cell) else None

    concentration = viz.movement_concentration(cells, radius_km=3.0)
    best = backbone.nlargest(1, "earnings_per_active_day").iloc[0]
    hours = sessions["online_minutes"].sum() / 60
    kpis = [
        (f"${trips['earnings'].sum():,.0f}", f"earned over {trips['date'].nunique()} active days"),
        (f"{len(trips):,}", "trips, Aug 2024 – Aug 2026"),
        (f"${trips['earnings'].sum() / trips['date'].nunique():,.2f}", "per active day"),
        (f"{best['day_of_week'][:3]} {best['time_window'].replace('_', ' ')}",
         f"best window · ${best['earnings_per_active_day']:.0f}/day"),
        (f"${sessions['earnings'].sum() / hours:.2f}", f"per hour · {len(sessions)} GPS sessions only"),
    ]
    kpi_html = "".join(
        f'<div class="kpi"><div class="v{"" if v.startswith("$") or v[0].isdigit() else " text"}">'
        f'{v}</div><div class="k">{k}</div></div>'
        for v, k in kpis
    )

    # Leaflet has no colourbar, so the ramp and the size channel are spelled out.
    ramp = ", ".join(viz.SEQUENTIAL)
    map_legend = (
        '<div class="maplegend">'
        '<span>Share moving</span><span>0%</span>'
        f'<i style="background:linear-gradient(90deg,{ramp})"></i><span>more</span>'
        '<span class="sep">·</span><span>circle size = moving pings</span></div>'
    )

    def fig_html(fig, first=False):
        return fig.to_html(
            full_html=False,
            include_plotlyjs="cdn" if first else False,
            config={"displayModeBar": False, "responsive": True},
        )

    cards = [
        _card(
            "Earnings by time of day",
            "Two years of trips. Earnings are bimodal — a lunch peak and a larger dinner "
            "peak — and the driver earns more at those hours by completing more trips, "
            "not better-paid ones: earnings per trip stays near $7 all day.",
            "4,881 trips · 2 years",
            fig_html(viz.earnings_by_hour(hourly), first=True),
            _table(hourly, {
                "hour": "Hour", "trips": "Trips", "earnings": "Earnings",
                "earnings_per_trip": "Per trip", "active_days": "Active days",
                "confidence": "Confidence",
            }),
        ),
        _card(
            "Earnings by location",
            "Rate, not total, so a location is not rewarded merely for being stood in "
            "longer. The two minor cells hint at a higher rate than the main one, but "
            "they rest on 24 and 29 trips — a hypothesis to test, not a finding.",
            "257 trips · 1 month",
            fig_html(viz.earnings_by_location(micro)),
            _table(micro, {
                "dominant_cell": "Cell", "sessions": "Sessions", "trips": "Trips",
                "earnings": "Earnings", "earnings_per_hour": "$/hour",
                "confidence": "Confidence",
            }),
        ),
        _card(
            "Location × day × time window",
            f"The README's core unit. Colour shows earnings per hour only where at least "
            f"{viz.MIN_TRIPS_FOR_COLOUR} trips support it; flat grey tiles are windows "
            "worked but too thin to measure. Numbers in each tile are trip counts. Just "
            "1 of 42 cells reaches high confidence — the emptiness is the finding.",
            "1 of 42 cells high confidence",
            fig_html(viz.location_time_heatmap(cube)),
            _table(
                cube.sort_values("trips", ascending=False),
                {
                    "dominant_cell": "Cell", "day_of_week": "Day", "time_window": "Window",
                    "trips": "Trips", "earnings": "Earnings",
                    "earnings_per_hour": "$/hour", "confidence": "Confidence",
                },
            ),
        ),
        _card(
            "Where the driving happened",
            f"Cells sized by moving pings, not total pings — total pings measure where the "
            f"phone rested. Home is the orange marker, excluded from productive time: it "
            f"ranks 5th by raw online pings but 10th by actual movement. "
            f"{concentration:.0%} of all real driving falls within 3 km of one point — "
            "which is why comparing one area against another is not possible.",
            f"{concentration:.0%} of driving within 3 km",
            map_legend + viz.performance_folium(cells, home_cell),
            _table(
                cells,
                {
                    "cell": "Cell", "online_pings": "Online pings",
                    "moving_pings": "Moving pings", "moving_share": "Moving share",
                    "at_home": "Home",
                },
            ),
        ),
    ]

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>DriverIQ — Phase 3</title>
<style>{STYLE}</style>
</head>
<body>
<div class="wrap">
<header>
  <div>
    <h1>DriverIQ — historical earnings</h1>
    <p class="sub">Melbourne bike courier · Aug 2024 – Aug 2026 · GPS for one month of it</p>
  </div>
  <button id="theme" type="button">Dark</button>
</header>
<div class="kpis">{kpi_html}</div>
{''.join(cards)}
<footer>
  Historical estimates from one driver's own records. They describe what happened,
  not current demand, driver supply, incentives or surge. Generated by
  <code>scripts/run_phase3.py</code>.
</footer>
</div>
<script>{SCRIPT}</script>
</body>
</html>"""

    out = cfg.REPORTS_DIR / OUT
    out.write_text(html)
    print(f"Wrote {out.relative_to(cfg.PROJECT_ROOT)} ({len(html) / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
