"""Print the committed synthetic session for an offline presentation."""
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "sample_results"


def main() -> None:
    experiment = json.loads((SAMPLE / "experiment.json").read_text(encoding="utf-8"))
    with (SAMPLE / "summary.csv").open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    print("REPLAY MODE — historical synthetic simulator output, not live Azure measurements")
    print(f"Rows: {len(rows)} | seeds: {len(experiment.get('final_seeds', []))}")
    for row in rows:
        print(f"{row.get('scenario', '?'):24} {row.get('policy', '?'):12} "
              f"mean={row.get('mean_completion_s', '?')} s "
              f"p95={row.get('p95_completion_s', '?')} s "
              f"cost=${row.get('cloud_cost_usd', '?')}")


if __name__ == "__main__":
    main()
