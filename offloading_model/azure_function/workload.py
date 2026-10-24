"""Identical deterministic task on the laptop and Azure Functions."""

import hashlib
import time


def compute(payload):
    iterations = payload.get("iterations")
    data = payload.get("data")
    if (
        not isinstance(iterations, int)
        or isinstance(iterations, bool)
        or not 1 <= iterations <= 250_000
    ):
        raise ValueError("iterations must be an integer between 1 and 250000")
    if not isinstance(data, str) or len(data.encode("utf-8")) > 200_000:
        raise ValueError("data must be a string of at most 200000 UTF-8 bytes")
    start = time.perf_counter()
    digest = hashlib.sha256(data.encode("utf-8")).digest()
    for _ in range(iterations):
        digest = hashlib.sha256(digest).digest()
    return {
        "digest": digest.hex(),
        "compute_ms": (time.perf_counter() - start) * 1000,
        "iterations": iterations,
        "input_bytes": len(data.encode("utf-8")),
    }
