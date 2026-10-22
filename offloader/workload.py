"""Deterministic CPU workload shared by local edge and cloud containers."""
from __future__ import annotations

import hashlib
import time
from typing import Any


def compute(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("payload must be a JSON object")
    iterations = payload.get("iterations")
    data = payload.get("data")
    if not isinstance(iterations, int) or isinstance(iterations, bool) or not 1 <= iterations <= 2_000_000:
        raise ValueError("iterations must be an integer between 1 and 2000000")
    if not isinstance(data, str) or len(data.encode("utf-8")) > 200_000:
        raise ValueError("data must be a string of at most 200000 UTF-8 bytes")
    started = time.perf_counter()
    digest = hashlib.sha256(data.encode("utf-8")).digest()
    for _ in range(iterations):
        digest = hashlib.sha256(digest).digest()
    return {"digest": digest.hex(), "compute_ms": (time.perf_counter() - started) * 1000,
            "iterations": iterations, "input_bytes": len(data.encode("utf-8"))}
