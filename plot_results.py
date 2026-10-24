"""Create report-ready comparison plots from summary.csv (requires matplotlib)."""

import argparse
import csv
from collections import defaultdict
from pathlib import Path
from statistics import mean


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("results", nargs="?", default="results")
    args = parser.parse_args()
    folder = Path(args.results)
    with (folder / "summary.csv").open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    try:
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise SystemExit(
            "Install matplotlib to generate figures: python -m pip install matplotlib"
        ) from exc
    policies = ["edge_only", "cloud_only", "threshold", "adaptive"]
    scenarios = list(dict.fromkeys(r["scenario"] for r in rows))
    grouped = defaultdict(list)
    for row in rows:
        grouped[(row["scenario"], row["policy"])].append(row)
    for metric, title, filename in [
        ("mean_completion_s", "Mean task completion time (s)", "completion.png"),
        ("p95_completion_s", "95th percentile task completion time (s)", "p95.png"),
        ("cloud_cost_usd", "Estimated cloud cost per run (USD)", "cost.png"),
    ]:
        fig, ax = plt.subplots(figsize=(10, 5))
        width = 0.19
        for j, policy in enumerate(policies):
            values = [mean(float(r[metric]) for r in grouped[(s, policy)]) for s in scenarios]
            ax.bar(
                [i + (j - 1.5) * width for i in range(len(scenarios))],
                values,
                width=width,
                label=policy.replace("_", " "),
            )
        ax.set_xticks(range(len(scenarios)), [s.replace("_", "\n") for s in scenarios])
        ax.set_ylabel(title)
        if metric != "cloud_cost_usd":
            ax.set_yscale("log")
            ax.set_ylabel(title + " (log scale)")
        ax.legend(ncol=2)
        ax.grid(axis="y", alpha=0.2)
        fig.tight_layout()
        fig.savefig(folder / filename, dpi=180)
        plt.close(fig)
    print(f"Saved completion.png, p95.png and cost.png to {folder.resolve()}")


if __name__ == "__main__":
    main()
