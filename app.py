"""DriverIQ — Streamlit front end over the Phase 1-6 layers.

Reads data/public/ when present (the deployment-safe marts, work-zone geography
only) and falls back to data/processed/ locally. No analysis happens here: every
figure comes from the marts, every chart from viz.py, every answer from
recommend.py or llm.py.
"""

import json
from pathlib import Path


import pandas as pd
import streamlit as st

from driveriq import llm, recommend, viz

ROOT = Path(__file__).resolve().parent
PUBLIC = ROOT / "data" / "public"
PROCESSED = ROOT / "data" / "processed"
DATA_DIR = PUBLIC if (PUBLIC / "trips.parquet").exists() else PROCESSED

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

st.set_page_config(page_title="DriverIQ", page_icon="•", layout="wide")

st.markdown("""
<style>
  .block-container { padding-top: 2.2rem; max-width: 1180px; }
  h1 { font-size: 1.7rem !important; letter-spacing: -0.02em; }
  [data-testid="stMetricValue"] { font-size: 1.55rem; }
  [data-testid="stMetric"] {
      background: #fcfcfb; border: 1px solid rgba(11,11,11,0.09);
      border-radius: 12px; padding: 14px 16px;
  }
  .stTabs [data-baseweb="tab"] { font-size: 0.95rem; }
  .caveat { color: #898781; font-size: 0.82rem; line-height: 1.6; }
  .pill { display:inline-block; font-size:0.72rem; color:#52514e;
          border:1px solid rgba(11,11,11,0.12); border-radius:99px;
          padding:2px 9px; margin-left:6px; }
</style>
""", unsafe_allow_html=True)


@st.cache_data
def load(name: str) -> pd.DataFrame:
    return pd.read_parquet(DATA_DIR / f"{name}.parquet")


@st.cache_data
def recorded_answers() -> dict:
    path = DATA_DIR / "recorded_answers.json"
    if not path.exists():
        return {}
    return {r["question"]: r for r in json.loads(path.read_text())}


@st.cache_resource
def model_online() -> bool:
    try:
        return llm.available()
    except Exception:
        return False


trips = load("trips")
expected = load("expected_earnings")
LIVE = model_online()

st.title("DriverIQ")
st.caption("Melbourne bike courier · Aug 2024 – Aug 2026 · GPS for one month of it")

backbone = load("time_backbone")
sessions = load("sessions")
best = backbone.nlargest(1, "earnings_per_active_day").iloc[0]
hours = sessions["online_minutes"].sum() / 60

cols = st.columns(5)
cols[0].metric("Total earned", f"${trips['earnings'].sum():,.0f}",
               help=f"{trips['date'].nunique()} active days")
cols[1].metric("Trips", f"{len(trips):,}")
cols[2].metric("Per active day", f"${trips['earnings'].sum() / trips['date'].nunique():,.2f}")
cols[3].metric("Best window", f"{best['day_of_week'][:3]} {best['time_window'].replace('_', ' ')}",
               help=f"${best['earnings_per_active_day']:.0f} per active day")
cols[4].metric("Per online hour", f"${sessions['earnings'].sum() / hours:.2f}",
               help=f"{len(sessions)} GPS sessions only — not the full history")

def _render_plan(plan: dict) -> None:
    if plan.get("expected_earnings") is None:
        st.warning("No history for that window, so there's no figure to give.", icon="⚠️")
    else:
        low, high = plan["band_80"]
        left, right = st.columns([1, 2])
        left.metric("Expected", f"${plan['expected_earnings']:.2f}")
        right.metric("80% range", f"${low:.2f} – ${high:.2f}",
                     help="Calibrated on held-out data; covers ~78% of real outcomes.")

    rows = [
        {
            "Window": w["window"].replace("_", " "),
            "Hours": w["hours_covered"],
            "Expected": f"${w['expected_earnings']:.2f}" if "expected_earnings" in w else "—",
            "Worked before": w.get("observations", 0),
            "Confidence": w.get("confidence", "no evidence"),
        }
        for w in plan["windows"]
    ]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width='stretch')

    stay = plan["stay_advice"]
    st.caption(
        f"**How long to stay:** about {stay['suggested_session_hours']} hours — "
        f"trips per hour peaks in hour {stay['peak_hour_into_session'] + 1} "
        f"({stay['peak_trips_per_hour']}) then falls away."
    )
    if plan.get("alternatives"):
        alts = " · ".join(f"{a['start_hour']}:00 → ${a['expected_earnings']:.0f}"
                          for a in plan["alternatives"])
        st.caption(f"**Better starts that day:** {alts}")


ask_tab, plan_tab, patterns_tab, model_tab = st.tabs(
    ["Ask", "Plan a session", "Patterns", "Model"]
)

# ---------------------------------------------------------------- Ask
with ask_tab:
    st.subheader("Ask in plain English")
    if LIVE:
        st.caption(f"Local model `{llm.MODEL}` is running — answers are generated live.")
    else:
        st.info(
            "The local Ollama model isn't running here, so answers below are **recorded "
            "from a local run**. Anything else you ask is still answered live by the "
            "analytics engine, just in plain figures instead of prose.",
            icon="ℹ️",
        )

    saved = recorded_answers()
    examples = list(saved) or [
        "I have 4 hours free on Friday evening, is it worth going out?",
        "When is the best time to drive this week?",
        "Which area should I drive in tonight?",
    ]
    picked = st.selectbox("Try one", ["—"] + examples)
    typed = st.text_input("Or ask your own", placeholder="Is Saturday lunch worth it?")
    question = typed.strip() or (picked if picked != "—" else "")

    if question:
        if not LIVE and question in saved:
            st.markdown(f"> {saved[question]['answer']}")
            st.caption("Recorded from a local run with Ollama.")
        else:
            with st.spinner("Thinking…"):
                result = llm.answer(question, fallback_formatter=None)
            answer = result.get("answer") or ""
            if result.get("source") in {"llm", "canned"} and answer:
                st.markdown(f"> {answer}")
            else:
                st.markdown("**Answered from the engine directly:**")
                payload = result.get("result", {})
                if "query" in payload:
                    _render_plan(payload)
                else:
                    st.json(llm.trim(payload))
            if result.get("invented_figures"):
                st.warning(
                    f"The model produced figures not in the data "
                    f"({', '.join(result['invented_figures'])}), so its answer was "
                    "discarded and the verified numbers shown instead."
                )
            if result.get("result"):
                with st.expander("The data behind that answer"):
                    st.json(llm.trim(result["result"]), expanded=False)


with plan_tab:
    st.subheader("Plan a session")
    a, b, c = st.columns(3)
    day = a.selectbox("Day", DAYS, index=4)
    start = b.slider("Start", 6, 22, 17, format="%d:00")
    length = c.slider("Hours available", 1, 8, 4)
    _render_plan(recommend.plan_session(day, float(start), float(length)))

    st.divider()
    st.caption("Every window, ranked by what the model expects.")
    table = expected[["day_of_week", "time_window", "predicted_earnings",
                      "low", "high", "observations", "confidence"]].copy()
    table.columns = ["Day", "Window", "Expected", "Low", "High", "Worked", "Confidence"]
    st.dataframe(table.sort_values("Expected", ascending=False),
                 hide_index=True, width='stretch', height=320)

# ---------------------------------------------------------------- Patterns
with patterns_tab:
    st.subheader("Earnings by time of day")
    st.caption("Two years, 4,881 trips. Bimodal — and earnings per trip stays near $7 "
               "all day, so the peaks are volume, not better-paid work.")
    st.plotly_chart(viz.earnings_by_hour(load("hourly_profile")),
                    width='stretch', config={"displayModeBar": False})

    st.subheader("Location × day × time window")
    st.caption("Colour only where at least 10 trips support it; grey tiles were worked "
               "but are too thin to measure. Just 1 of 42 cells reaches high confidence.")
    st.plotly_chart(viz.location_time_heatmap(load("location_time_cube")),
                    width='stretch', config={"displayModeBar": False})

    st.subheader("Where the driving happened")
    st.caption("Circles sized by moving pings, not total pings. Home is excluded from "
               "this published view. 99% of real driving falls within 3 km of one point, "
               "which is why comparing areas isn't supportable.")
    st.html(viz.performance_folium(load("cell_activity"), home_cell=None))

# ---------------------------------------------------------------- Model
with model_tab:
    st.subheader("How well it predicts")
    st.caption("Benchmarked against the historical average for that day and window — "
               "the number you could work out with a pen. Chronological split, so the "
               "model never sees the future.")
    scores = load("model_scores").copy()
    scores.columns = ["Model", "MAE", "RMSE", "R²", "vs baseline %"]
    st.dataframe(scores.round(3), hide_index=True, width='stretch')

    importance = load("model_feature_importance")
    history = importance[importance["feature"].str.contains("history|recent")]
    st.caption(
        f"The driver's own track record accounts for "
        f"**{history['importance'].sum():.0%}** of the signal — this model has learned "
        "this driver's pattern, not the Melbourne market."
    )
    st.plotly_chart(
        viz.earnings_by_location(load("micro_location")),
        width='stretch', config={"displayModeBar": False},
    )

st.divider()
st.markdown(
    '<p class="caveat">Historical estimates from one driver\'s own records. They '
    "describe what happened — not current demand, driver supply, incentives or surge. "
    "Location analysis covers a single month of GPS; timing analysis covers two years. "
    "Home location is excluded from this published view.</p>",
    unsafe_allow_html=True,
)
