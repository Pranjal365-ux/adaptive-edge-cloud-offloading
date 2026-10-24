"""Optional interactive dashboard. Run: streamlit run dashboard.py"""

import csv
import json
import subprocess
import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "dashboard_results"
st.set_page_config(page_title="Edge Cloud Offloading", layout="wide")
st.title("Adaptive Task Offloading")
st.caption("Simulated edge and cloud resources; all policies replay the same task traces.")

with st.sidebar:
    task_count = st.slider("Tasks per scenario and repetition", 50, 1000, 300, 50)
    seeds = st.slider("Final repetitions", 1, 20, 5)
    run = st.button("Run all four policies", type="primary")

if run:
    with st.spinner("Running simulation"):
        subprocess.run(
            [
                sys.executable,
                str(ROOT / "offloading.py"),
                "--tasks",
                str(task_count),
                "--seeds",
                str(seeds),
                "--output",
                str(RESULTS),
            ],
            check=True,
        )

if not (RESULTS / "summary.csv").exists():
    st.info("Choose the experiment size and run the simulation.")
    st.stop()

with (RESULTS / "experiment.json").open(encoding="utf-8") as f:
    experiment = json.load(f)
st.write(
    f"Fixed baseline threshold: **{experiment['selected_threshold_mi']:.2f} million instructions**"
)
with (RESULTS / "summary.csv").open(newline="", encoding="utf-8") as f:
    summaries = list(csv.DictReader(f))
scenarios = list(dict.fromkeys(r["scenario"] for r in summaries))
selected = st.selectbox("Scenario", scenarios)
try:
    import pandas as pd
except ImportError:
    st.error("Install pandas for the dashboard: python -m pip install pandas")
    st.stop()
df = pd.DataFrame([r for r in summaries if r["scenario"] == selected])
metrics = [
    "mean_completion_s",
    "p95_completion_s",
    "throughput_tasks_per_s",
    "edge_utilization",
    "network_mb",
    "cloud_cost_usd",
    "cloud_task_fraction",
]
df[metrics] = df[metrics].astype(float)
averages = df.groupby("policy", sort=False)[metrics].mean()
st.subheader("Completion time by policy")
st.bar_chart(averages[["mean_completion_s", "p95_completion_s"]])
st.subheader("Mean metrics across repetitions")
st.dataframe(averages.round(4), use_container_width=True)
st.download_button("Download summary CSV", (RESULTS / "summary.csv").read_bytes(), "summary.csv")
st.download_button("Download task log CSV", (RESULTS / "tasks.csv").read_bytes(), "tasks.csv")
with st.expander("Scenario settings and threshold tuning"):
    st.json(experiment)
