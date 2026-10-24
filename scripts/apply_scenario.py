"""Apply a checked-in Toxiproxy scenario through the edge gateway."""
from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = ROOT / "scenarios"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", choices=("good", "poor", "flapping", "random-walk", "lossy"))
    parser.add_argument("--gateway", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    config = json.loads((SCENARIOS / f"{args.scenario}.yaml").read_text(encoding="utf-8"))
    request = urllib.request.Request(f"{args.gateway.rstrip('/')}/scenario",
        data=json.dumps({"name": config["name"]}).encode(), method="PUT",
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            print(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError) as exc:
        parser.error(f"Could not apply scenario through the local gateway: {type(exc).__name__}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
