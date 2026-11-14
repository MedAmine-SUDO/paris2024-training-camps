"""Interactive explorer for the Paris 2024 training camps dataset.

Run:  uv run streamlit run app/explorer.py
"""

import json
from pathlib import Path

import altair as alt
import pandas as pd
import pydeck as pdk
import streamlit as st

DATA = Path(__file__).resolve().parent.parent / "data" / "processed"
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
TEAL, CORAL = [20, 184, 166], [249, 115, 22]

st.set_page_config(page_title="Paris 2024 Training Camps", page_icon="🏅", layout="wide")


@st.cache_data
def load() -> tuple[pd.DataFrame, pd.DataFrame]:
    camps = pd.DataFrame(json.loads((DATA / "camps.json").read_text(encoding="utf-8")))
    facilities = pd.read_csv(DATA / "facilities.csv")
    return camps, facilities


camps, facilities = load()
all_disciplines = sorted({d for ds in camps.disciplines for d in ds})
all_types = sorted(facilities.type.dropna().unique())

# ---------------------------------------------------------------- sidebar filters
st.sidebar.title("🏅 Filters")
chosen_disciplines = st.sidebar.multiselect("Disciplines", all_disciplines, placeholder="Any discipline")
chosen_regions = st.sidebar.multiselect("Regions", sorted(camps.region.unique()), placeholder="All regions")
max_alt = int(camps.altitude_m.max())
alt_range = st.sidebar.slider("Altitude (m)", 0, max_alt, (0, max_alt), step=50)
chosen_types = st.sidebar.multiselect("Has a facility of type", all_types, placeholder="Any facility")
para_only = st.sidebar.toggle("Para-sport camps only")
show_facilities = st.sidebar.toggle("Show individual facilities on the map")

mask = camps.altitude_m.fillna(0).between(*alt_range)
if chosen_disciplines:
    mask &= camps.disciplines.apply(lambda ds: bool(set(ds) & set(chosen_disciplines)))
if chosen_regions:
    mask &= camps.region.isin(chosen_regions)
if chosen_types:
    mask &= camps.facility_counts.apply(lambda fc: any(t in fc for t in chosen_types))
if para_only:
    mask &= camps.para_disciplines.str.len() > 0
view = camps[mask]
view_facilities = facilities[facilities.camp_id.isin(view.camp_id)]

# ---------------------------------------------------------------- header + KPIs
st.title("Paris 2024 Training Camps")
st.caption(
    "The ~1,000 sites certified to host national teams before the Paris 2024 Olympic & Paralympic Games. "
    "Facts-only snapshot built from the official directory (now offline)."
)
k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Camps", f"{len(view):,}")
k2.metric("Regions", view.region.nunique())
k3.metric("Disciplines", len({d for ds in view.disciplines for d in ds}))
k4.metric("Facilities", f"{int(view.n_facilities.sum()):,}")
k5.metric("Para-sport camps", int((view.para_disciplines.str.len() > 0).sum()))

if view.empty:
    st.warning("No camp matches these filters.")
    st.stop()

# ---------------------------------------------------------------- map
camp_points = view.dropna(subset=["lat", "lon"]).assign(
    disciplines_text=lambda d: d.disciplines.apply(lambda ds: ", ".join(ds[:6]) + (" …" if len(ds) > 6 else "")),
    radius=lambda d: 1500 + d.n_facilities * 600,
)
layers = [
    pdk.Layer(
        "ScatterplotLayer", camp_points, get_position="[lon, lat]", get_radius="radius",
        get_fill_color=TEAL + [170], get_line_color=[255, 255, 255], line_width_min_pixels=1,
        stroked=True, pickable=True, radius_min_pixels=3, radius_max_pixels=28,
    )
]
if show_facilities:
    layers.append(pdk.Layer(
        "ScatterplotLayer", view_facilities.dropna(subset=["lat", "lon"]), get_position="[lon, lat]",
        get_radius=250, get_fill_color=CORAL + [200], pickable=True, radius_min_pixels=2,
    ))
st.pydeck_chart(pdk.Deck(
    layers=layers,
    initial_view_state=pdk.ViewState(latitude=46.6, longitude=2.4, zoom=4.6),
    map_style=None,
    tooltip={"html": "<b>{name}</b><br/>{city} · {region}<br/>{disciplines_text}{type}"},
), height=520)
st.caption("Bubble size = number of facilities. Overseas camps (Guyane, Martinique, Nouvelle-Calédonie…) are off-screen: zoom out to see them.")

# ---------------------------------------------------------------- analysis tabs
overview, climate, table = st.tabs(["📊 Overview", "🌦️ Climate", "📋 Data"])

with overview:
    left, right = st.columns(2)
    by_region = view.region.value_counts().rename_axis("region").reset_index(name="camps")
    left.altair_chart(
        alt.Chart(by_region, title="Camps per region").mark_bar(color="#14b8a6")
        .encode(x="camps:Q", y=alt.Y("region:N", sort="-x", title=None), tooltip=["region", "camps"]),
        width="stretch",
    )
    top = pd.Series([d for ds in view.disciplines for d in ds]).value_counts().head(15)
    right.altair_chart(
        alt.Chart(top.rename_axis("discipline").reset_index(name="camps"), title="Most offered disciplines")
        .mark_bar(color="#f97316")
        .encode(x="camps:Q", y=alt.Y("discipline:N", sort="-x", title=None), tooltip=["discipline", "camps"]),
        width="stretch",
    )
    left2, right2 = st.columns(2)
    left2.altair_chart(
        alt.Chart(view.dropna(subset=["altitude_m"]), title="Altitude distribution")
        .mark_bar(color="#0ea5e9")
        .encode(x=alt.X("altitude_m:Q", bin=alt.Bin(maxbins=30), title="altitude (m)"), y=alt.Y("count()", title="camps")),
        width="stretch",
    )
    fac_totals = pd.Series(
        [n for fc in view.facility_counts for n in fc.values()],
        index=[t for fc in view.facility_counts for t in fc.keys()],
    ).groupby(level=0).sum().sort_values(ascending=False).head(12)
    right2.altair_chart(
        alt.Chart(fac_totals.rename_axis("type").reset_index(name="count"), title="Facilities by type")
        .mark_bar(color="#8b5cf6")
        .encode(x="count:Q", y=alt.Y("type:N", sort="-x", title=None), tooltip=["type", "count"]),
        width="stretch",
    )

with climate:
    with_climate = view.dropna(subset=["temp_max_c"])
    if with_climate.empty:
        st.info("No climate data for the selected camps.")
    else:
        name = st.selectbox("Camp", with_climate.sort_values("name").name)
        camp = with_climate[with_climate.name == name].iloc[0]
        monthly = pd.DataFrame({
            "month": MONTHS,
            "min °C": camp.temp_min_c,
            "max °C": camp.temp_max_c,
            "rain (mm)": camp.rainfall_mm if isinstance(camp.rainfall_mm, list) else [None] * 12,
        })
        temps = monthly.melt("month", ["min °C", "max °C"], var_name="series", value_name="°C")
        base = alt.Chart(temps).encode(x=alt.X("month:N", sort=MONTHS, title=None))
        st.altair_chart(
            base.mark_line(point=True).encode(y="°C:Q", color=alt.Color("series:N", scale=alt.Scale(range=["#0ea5e9", "#f97316"])))
            .properties(title=f"Monthly temperatures · {camp.city} ({camp.altitude_m} m)"),
            width="stretch",
        )
        st.altair_chart(
            alt.Chart(monthly).mark_bar(color="#14b8a6").encode(x=alt.X("month:N", sort=MONTHS, title=None), y="rain (mm):Q")
            .properties(title="Monthly rainfall"),
            width="stretch",
        )

with table:
    columns = ["name", "city", "region", "altitude_m", "n_facilities", "disciplines", "options"]
    shown = view[columns].assign(
        disciplines=view.disciplines.str.join(", "), options=view.options.str.join(", ")
    ).sort_values(["region", "name"])
    st.dataframe(shown, width="stretch", hide_index=True)
    st.download_button("⬇️ Download these camps (CSV)", shown.to_csv(index=False).encode("utf-8"),
                       "paris2024_training_camps.csv", "text/csv")
