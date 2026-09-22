"""Phase 3 figures.

Two of these charts rest on two years of data and two rest on one month, so the
main design problem is stopping the thin ones from looking as authoritative as
the strong ones. Sample size is therefore drawn, not just recorded: cells the
evidence cannot support are left uncoloured rather than shaded a confident blue.
"""

import math

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from . import config as cfg

LIGHT = {
    "surface": "#fcfcfb",
    "ink": "#0b0b0b",
    "ink2": "#52514e",
    "muted": "#898781",
    "grid": "#e1e0d9",
    "axis": "#c3c2b7",
    "series1": "#2a78d6",
    "series2": "#eb6834",
    "unmeasured": "#e6e5e0",
}
DARK = {
    "surface": "#1a1a19",
    "ink": "#ffffff",
    "ink2": "#c3c2b7",
    "muted": "#898781",
    "grid": "#2c2c2a",
    "axis": "#383835",
    "series1": "#3987e5",
    "series2": "#d95926",
    "unmeasured": "#2c2c2a",
}

# One hue, light to dark. A rainbow would imply category breaks that magnitude
# does not have.
SEQUENTIAL = [
    "#cde2fb", "#b7d3f6", "#9ec5f4", "#86b6ef", "#6da7ec", "#5598e7",
    "#3987e5", "#2a78d6", "#256abf", "#1c5cab", "#184f95", "#104281", "#0d366b",
]

DAY_ORDER = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
WINDOW_ORDER = [name for name, _, _ in cfg.TIME_WINDOWS]

# Below this a cell's rate is noise. Drawing it in the same ramp as a
# well-evidenced cell would be the chart telling a lie the data cannot back.
MIN_TRIPS_FOR_COLOUR = 10

FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif'


def _colorscale() -> list:
    n = len(SEQUENTIAL) - 1
    return [[i / n, c] for i, c in enumerate(SEQUENTIAL)]


def _base_layout(fig: go.Figure, height: int = 380, top: int = 8) -> go.Figure:
    """Recessive chrome, transparent surface so the page theme shows through."""
    fig.update_layout(
        height=height,
        font=dict(family=FONT, size=12, color=LIGHT["ink2"]),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=8, r=8, t=top, b=8),
        hoverlabel=dict(font_family=FONT, font_size=12),
        showlegend=False,
    )
    fig.update_xaxes(
        showgrid=False, zeroline=False,
        linecolor=LIGHT["axis"], linewidth=1,
        tickfont=dict(color=LIGHT["muted"]),
    )
    fig.update_yaxes(
        gridcolor=LIGHT["grid"], gridwidth=1, zeroline=False, showline=False,
        tickfont=dict(color=LIGHT["muted"]),
    )
    return fig


def earnings_by_hour(hourly: pd.DataFrame) -> go.Figure:
    """README chart 1 — earnings by time, on the full two years.

    One series, so one colour: shading each bar by its own height would spend
    the only free channel restating the bar length.
    """
    df = hourly.sort_values("hour")
    peak = df["earnings"].idxmax()
    labels = [
        f"${v:,.0f}" if i == peak or v == df.loc[df["hour"] < 15, "earnings"].max() else ""
        for i, v in df["earnings"].items()
    ]

    fig = go.Figure(
        go.Bar(
            x=df["hour"], y=df["earnings"],
            marker=dict(color=LIGHT["series1"], line=dict(width=0)),
            text=labels, textposition="outside",
            textfont=dict(color=LIGHT["ink2"], size=11),
            customdata=df[["trips", "earnings_per_trip", "active_days"]],
            hovertemplate=(
                "<b>%{x}:00</b><br>Earnings $%{y:,.2f}<br>"
                "Trips %{customdata[0]}<br>Per trip $%{customdata[1]:.2f}<br>"
                "Active days %{customdata[2]}<extra></extra>"
            ),
        )
    )
    fig.update_layout(bargap=0.3)
    fig.update_xaxes(title_text="Hour of day", dtick=1, tickformat="d")
    fig.update_yaxes(title_text="Earnings (AUD)", tickprefix="$", separatethousands=True)
    return _base_layout(fig)


def earnings_by_location(micro: pd.DataFrame) -> go.Figure:
    """README chart 2 — earnings by location.

    Plots the rate rather than the total: total earnings mostly measures how
    long the driver happened to stand somewhere. Trip counts ride along as
    direct labels so a tall bar built on 24 trips cannot pass for a solid one.
    """
    df = micro.sort_values("earnings_per_hour")
    # Sessions, not trips, because confidence is graded on sessions: trips
    # inside one shift are correlated, so a visit is the independent evidence.
    labels = [
        f"  ${r.earnings_per_hour:.2f}/h · {int(r.sessions)} sessions"
        f" · {int(r.trips)} trips · {r.confidence}"
        for r in df.itertuples()
    ]

    fig = go.Figure(
        go.Bar(
            y=df["dominant_cell"], x=df["earnings_per_hour"], orientation="h",
            marker=dict(color=LIGHT["series1"], line=dict(width=0)),
            text=labels, textposition="outside",
            textfont=dict(color=LIGHT["ink2"], size=11),
            customdata=df[["sessions", "trips", "earnings", "confidence"]],
            hovertemplate=(
                "<b>%{y}</b><br>$%{x:.2f}/hour<br>"
                "Sessions %{customdata[0]}<br>Trips %{customdata[1]}<br>"
                "Earnings $%{customdata[2]:,.2f}<br>"
                "Confidence %{customdata[3]}<extra></extra>"
            ),
        )
    )
    fig.update_layout(bargap=0.45)
    fig.update_xaxes(
        title_text="Earnings per online hour (AUD)", tickprefix="$",
        range=[0, df["earnings_per_hour"].max() * 2.1],
    )
    fig.update_yaxes(title_text="", showgrid=False, tickfont=dict(size=11))
    return _base_layout(fig, height=260)


def location_time_heatmap(cube: pd.DataFrame) -> go.Figure:
    """README chart 3 — location x time window, faceted by location.

    Colour carries earnings per hour only where at least MIN_TRIPS_FOR_COLOUR
    trips support it. Everything thinner is drawn as a flat "seen, not measured"
    tile with its trip count, so the eye reads absence of evidence as absence of
    colour instead of as a low value.
    """
    cells = list(cube["dominant_cell"].dropna().unique())
    fig = make_subplots(
        rows=1, cols=len(cells), subplot_titles=cells,
        shared_yaxes=True, horizontal_spacing=0.04,
    )
    # Styled here, before the per-cell counts are added: update_annotations is
    # global and would otherwise flatten their size and white-on-dark contrast.
    fig.update_annotations(font=dict(size=11, color=LIGHT["ink2"]))

    measured = cube[cube["trips"] >= MIN_TRIPS_FOR_COLOUR]
    zmin = measured["earnings_per_hour"].min() if len(measured) else 0
    zmax = measured["earnings_per_hour"].max() if len(measured) else 1

    for i, cell in enumerate(cells, start=1):
        sub = cube[cube["dominant_cell"] == cell]
        pivot_rate = sub.pivot_table(
            index="day_of_week", columns="time_window",
            values="earnings_per_hour", observed=False,
        ).reindex(index=DAY_ORDER, columns=WINDOW_ORDER)
        pivot_trips = sub.pivot_table(
            index="day_of_week", columns="time_window", values="trips", observed=False,
        ).reindex(index=DAY_ORDER, columns=WINDOW_ORDER)

        thin = pivot_trips.notna() & (pivot_trips < MIN_TRIPS_FOR_COLOUR)

        # Flat tiles for cells we visited but cannot measure.
        fig.add_trace(
            go.Heatmap(
                z=thin.astype(float).where(thin), x=WINDOW_ORDER, y=DAY_ORDER,
                colorscale=[[0, LIGHT["unmeasured"]], [1, LIGHT["unmeasured"]]],
                showscale=False, hoverinfo="skip", xgap=2, ygap=2,
                # Tagged so the theme switcher can recolour these and only
                # these; showscale is false on most coloured facets too.
                meta="unmeasured",
            ),
            row=1, col=i,
        )
        fig.add_trace(
            go.Heatmap(
                z=pivot_rate.where(~thin), x=WINDOW_ORDER, y=DAY_ORDER,
                customdata=pivot_trips.values,
                colorscale=_colorscale(), zmin=zmin, zmax=zmax,
                showscale=(i == len(cells)), xgap=2, ygap=2,
                colorbar=dict(
                    title=dict(text="$/hour", font=dict(size=11)),
                    thickness=10, len=0.75, outlinewidth=0,
                    tickfont=dict(color=LIGHT["muted"], size=10), tickprefix="$",
                ),
                hovertemplate=(
                    "<b>%{y} · %{x}</b><br>$%{z:.2f}/hour<br>"
                    "%{customdata:.0f} trips<extra></extra>"
                ),
            ),
            row=1, col=i,
        )

        for day in DAY_ORDER:
            for window in WINDOW_ORDER:
                n = pivot_trips.loc[day, window]
                if pd.isna(n):
                    continue
                enough = n >= MIN_TRIPS_FOR_COLOUR
                rate = pivot_rate.loc[day, window]
                shade = (rate - zmin) / (zmax - zmin) if enough and zmax > zmin else 0
                fig.add_annotation(
                    x=window, y=day, row=1, col=i, showarrow=False,
                    text=f"{int(n)}",
                    font=dict(
                        size=9,
                        color="#ffffff" if enough and shade > 0.55 else LIGHT["ink2"],
                    ),
                )

    fig.update_xaxes(tickangle=-40, tickfont=dict(size=9, color=LIGHT["muted"]), showline=False)
    fig.update_yaxes(tickfont=dict(size=10, color=LIGHT["muted"]), autorange="reversed")
    return _base_layout(fig, height=360, top=34)


def movement_concentration(cells: pd.DataFrame, radius_km: float = 3.0) -> float:
    """Share of real driving within radius_km of the movement-weighted centre.

    Raw bounding-box extent overstates the footprint badly: a couple of cells
    the driver merely passed through stretch it to tens of kilometres while
    holding almost no movement. Weighting by moving pings answers the question
    the chart is actually making -- how concentrated the driving is.
    """
    work = cells[cells["moving_pings"] > 0]
    if work.empty:
        return 0.0

    weight = work["moving_pings"]
    centre_lat = (work["lat"] * weight).sum() / weight.sum()
    centre_lon = (work["lon"] * weight).sum() / weight.sum()

    km_lat = (work["lat"] - centre_lat) * 110.574
    km_lon = (work["lon"] - centre_lon) * 111.320 * math.cos(math.radians(centre_lat))
    within = (km_lat**2 + km_lon**2) ** 0.5 <= radius_km
    return float(weight[within].sum() / weight.sum())


def _ramp_colour(t: float) -> str:
    """Pick a step from the sequential ramp for a 0-1 position."""
    idx = min(int(max(t, 0.0) * (len(SEQUENTIAL) - 1)), len(SEQUENTIAL) - 1)
    return SEQUENTIAL[idx]


def performance_folium(cells: pd.DataFrame, home_cell: str | None) -> str:
    """README chart 4 — the real map, as embeddable HTML.

    Leaflet rather than Plotly: plotly.js 4.1.1 never adds its scattermap
    layers to the map, so the markers exist and stay hoverable but are never
    drawn. Leaflet renders tiles as plain images and markers as SVG, so it
    needs no WebGL and actually appears.
    """
    import folium

    work = cells[(cells["moving_pings"] > 0) & (~cells["at_home"])]
    home = cells[cells["at_home"]]
    centre = [work["lat"].mean(), work["lon"].mean()]

    # Plain OpenStreetMap: CartoDB's basemaps now require an API key.
    fmap = folium.Map(location=centre, zoom_start=13, tiles="OpenStreetMap",
                      control_scale=True)

    peak = max(work["moving_pings"].max(), 1) ** 0.5
    span = max(work["moving_share"].max(), 0.6)
    for r in work.itertuples():
        folium.CircleMarker(
            location=[r.lat, r.lon],
            radius=4 + (r.moving_pings**0.5) / peak * 26,
            color=LIGHT["surface"], weight=2,
            fill=True, fill_color=_ramp_colour(r.moving_share / span), fill_opacity=0.85,
            tooltip=(
                f"<b>{r.cell}</b><br>Online pings {r.online_pings:,}<br>"
                f"Moving pings {r.moving_pings:,}<br>Moving share {r.moving_share:.0%}"
            ),
        ).add_to(fmap)

    for r in home.itertuples():
        folium.CircleMarker(
            location=[r.lat, r.lon], radius=9,
            color=LIGHT["surface"], weight=2,
            fill=True, fill_color=LIGHT["series2"], fill_opacity=1,
            tooltip=(
                f"<b>Home — {r.cell}</b><br>Online pings {r.online_pings:,}<br>"
                f"Moving share {r.moving_share:.0%}<br><i>excluded from productive time</i>"
            ),
        ).add_to(fmap)
        folium.Marker(
            location=[r.lat, r.lon],
            icon=folium.DivIcon(
                html=(
                    f'<div style="font:600 12px {FONT};color:{LIGHT["series2"]};'
                    'transform:translate(12px,-9px);white-space:nowrap">Home</div>'
                )
            ),
        ).add_to(fmap)

    fmap.fit_bounds([[work["lat"].min(), work["lon"].min()],
                     [work["lat"].max(), work["lon"].max()]], padding=(25, 25))
    return fmap.get_root()._repr_html_()
