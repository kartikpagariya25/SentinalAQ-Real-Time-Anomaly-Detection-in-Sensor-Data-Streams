import sys
import time
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

from app.config import DATA_FILE, MODEL_FILE, REPORT_DIR  # noqa: E402
from app.model import load_bundle  # noqa: E402
from app.priors import CITIES  # noqa: E402
from app.stream import DayWriter, stream_ticks  # noqa: E402

st.set_page_config(page_title="SentinelAQ", layout="wide")

COLORS = {"VALID": "#2e7d32", "EVENT": "#b26a00", "INVALID": "#c62828", "REVIEW": "#6a1b9a"}


@st.cache_data
def load_data():
    return pd.read_parquet(DATA_FILE)


@st.cache_resource
def get_bundle():
    return load_bundle()


def style_rows(df):
    def paint(row):
        key = row["verdict"] if row["verdict"] != "VALID" else "EVENT" if row["detected_as"] == "pollution_event" else "VALID"
        return [f"color: {COLORS[key]}; font-weight: {'600' if key != 'VALID' else '400'}"] * len(row)
    return df.style.apply(paint, axis=1)


st.title("SentinelAQ - live reading validation")
st.caption("Every reading gets a verdict, a confidence score and a plain-language reason. Readings are simulated from patterns learned on real Atmos data.")

tab_live, tab_data = st.tabs(["Live stream", "Synthetic data explorer"])

with tab_live:
    if not MODEL_FILE.exists():
        st.error("Model not found. Run: python -m app.cli train")
        st.stop()


    with st.sidebar:
        st.header("Stream settings")
        start = st.date_input("Start date", pd.Timestamp("2026-11-07"))
        days = st.slider("Days to stream", 1, 7, 2)
        cities = st.multiselect("Cities", list(CITIES), default=["Delhi", "Pune"])
        delay = st.slider("Seconds per hour of data", 0.0, 2.0, 0.3, 0.1)
        seed = st.number_input("Simulation seed", value=2026, step=1)
        devices = [f"{CITIES[c]['code']}-{k + 1:02d}" for c in cities for k in range(CITIES[c]["devices"])]
        focus = st.selectbox("Device to chart", devices) if devices else None
        run = st.button("Start stream", type="primary", disabled=not cities)

    metrics = st.empty()
    left, right = st.columns([3, 2])
    table_box = left.empty()
    chart_box = right.empty()
    download_box = st.container()

    if run:
        writer = DayWriter(REPORT_DIR / "dashboard")
        seen = []
        bundle = get_bundle()
        progress = st.progress(0.0, text="Warming up on the previous 48 hours")
        total = days * 24
        for i, res in enumerate(stream_ticks(str(start), days, cities, int(seed), bundle)):
            writer.add(res)
            seen.append(res)
            allr = pd.concat(seen, ignore_index=True)
            inv = allr["verdict"] == "INVALID"
            with metrics.container():
                a, b, c, d, e = st.columns(5)
                a.metric("Readings checked", f"{len(allr):,}")
                b.metric("Flagged invalid", f"{int(inv.sum()):,}")
                c.metric("Needs review", f"{int((allr['verdict'] == 'REVIEW').sum()):,}")
                d.metric("Pollution events", f"{int((allr['detected_as'] == 'pollution_event').sum()):,}")
                e.metric("Mean confidence", f"{allr['confidence'].mean():.2f}")
            shown = res[["timestamp", "device_id", "pm25", "temp", "rh", "verdict", "detected_as", "confidence", "reason"]]
            table_box.dataframe(style_rows(shown), hide_index=True, width="stretch", height=420)
            one = allr[allr["device_id"] == focus]
            fig = go.Figure(go.Scatter(x=one["timestamp"], y=one["pm25"], mode="lines", line=dict(color="#607d8b", width=1.5), name="PM2.5"))
            for key, mask, col in (
                ("Invalid", one["verdict"] == "INVALID", COLORS["INVALID"]),
                ("Review", one["verdict"] == "REVIEW", COLORS["REVIEW"]),
                ("Event", one["detected_as"] == "pollution_event", COLORS["EVENT"]),
            ):
                sub = one[mask]
                fig.add_trace(go.Scatter(x=sub["timestamp"], y=sub["pm25"], mode="markers", marker=dict(color=col, size=8), name=key))
            fig.update_layout(height=420, margin=dict(l=10, r=10, t=30, b=10), title=f"{focus} PM2.5", yaxis_type="log", legend=dict(orientation="h"))
            chart_box.plotly_chart(fig, width="stretch")
            progress.progress(min((i + 1) / total, 1.0), text=f"{res['timestamp'].iloc[0]:%d %b %Y %H:%M}")
            if delay:
                time.sleep(delay)
        writer.flush()
        progress.empty()
        st.session_state["report_dir"] = str(writer.dir)

    report_dir = Path(st.session_state.get("report_dir", ""))
    if report_dir.is_dir():
        with download_box:
            st.subheader("Day-wise reports")
            files = sorted(report_dir.glob("2*.csv"))
            cols = st.columns(min(len(files), 4) or 1)
            for i, f in enumerate(files):
                cols[i % len(cols)].download_button(f.stem, f.read_bytes(), file_name=f.name, mime="text/csv", key=f.name)
            summary = report_dir / "daily_summary.csv"
            if summary.exists():
                st.dataframe(pd.read_csv(summary), hide_index=True, width="stretch")

with tab_data:
    if not DATA_FILE.exists():
        st.info("No synthetic data yet. Run: python -m app.cli generate")
    else:
        data = load_data()
        st.caption("Locations are assumed. The real Atmos file has no city or device location.")
        c1, c2, c3 = st.columns(3)
        city = c1.selectbox("City", sorted(data["city"].unique()))
        sub = data[data["city"] == city]
        dev = c2.selectbox("Device", sorted(sub["device_id"].unique()))
        sub = sub[sub["device_id"] == dev]
        lo, hi = sub["timestamp"].min().date(), sub["timestamp"].max().date()
        rng = c3.date_input("Date range", (pd.Timestamp("2025-10-25").date(), pd.Timestamp("2025-11-20").date()), min_value=lo, max_value=hi)
        if len(rng) == 2:
            sub = sub[(sub["timestamp"].dt.date >= rng[0]) & (sub["timestamp"].dt.date <= rng[1])]
        only = st.checkbox("Show only non-normal rows")
        view = sub[sub["fault_type"] != "normal"] if only else sub
        fig = go.Figure(go.Scatter(x=sub["timestamp"], y=sub["pm25"], mode="lines", line=dict(color="#607d8b", width=1.2), name="PM2.5"))
        for lab, col in (("pollution_event", COLORS["EVENT"]), ("spike", COLORS["INVALID"]), ("stuck", "#ad1457"), ("drift", "#00695c"), ("saturation", "#4e342e")):
            m = sub[sub["fault_type"] == lab]
            if len(m):
                fig.add_trace(go.Scatter(x=m["timestamp"], y=m["pm25"], mode="markers", marker=dict(size=7, color=col), name=lab))
        fig.update_layout(height=380, margin=dict(l=10, r=10, t=30, b=10), yaxis_type="log", legend=dict(orientation="h"))
        st.plotly_chart(fig, width="stretch")
        st.dataframe(view[["timestamp", "device_id", "pm25", "temp", "rh", "fault_type", "fault_tier", "event_cause", "event_mult"]].head(500), hide_index=True, width="stretch")
        st.download_button("Download this view as CSV", view.to_csv(index=False).encode(), file_name=f"{dev}.csv", mime="text/csv")
