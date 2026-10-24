"""Statistical helpers shared by reports and simulator output."""
from __future__ import annotations

import math
import random
from statistics import fmean, stdev
from typing import Sequence


def nearest_rank(values: Sequence[float], fraction: float) -> float:
    """Return the nearest-rank quantile (ceil(p*N), one-based)."""
    if not values:
        raise ValueError("values must not be empty")
    if not 0 < fraction <= 1:
        raise ValueError("fraction must be in (0, 1]")
    ordered = sorted(values)
    return ordered[math.ceil(fraction * len(ordered)) - 1]


def mean_std(values: Sequence[float]) -> tuple[float, float]:
    if not values:
        raise ValueError("values must not be empty")
    return fmean(values), stdev(values) if len(values) > 1 else 0.0


def bootstrap_mean_ci(values: Sequence[float], *, seed: int = 0,
                      confidence: float = 0.95, resamples: int = 10_000) -> tuple[float, float]:
    """Seeded percentile bootstrap CI for the mean; reports data, not a model claim."""
    if not values:
        raise ValueError("values must not be empty")
    if not 0 < confidence < 1 or resamples < 1:
        raise ValueError("confidence must be in (0, 1) and resamples positive")
    if len(values) == 1:
        value = float(values[0])
        return value, value
    rng = random.Random(seed)
    n = len(values)
    means = sorted(fmean(rng.choices(values, k=n)) for _ in range(resamples))
    tail = (1 - confidence) / 2
    return nearest_rank(means, tail), nearest_rank(means, 1 - tail)


def paired_mean_ci(left: Sequence[float], right: Sequence[float], *, seed: int = 0,
                   confidence: float = 0.95, resamples: int = 10_000) -> tuple[float, float, float]:
    """Bootstrap the paired difference left-right while preserving matched seeds."""
    if len(left) != len(right) or not left:
        raise ValueError("paired samples must have the same nonzero length")
    differences = [a - b for a, b in zip(left, right)]
    low, high = bootstrap_mean_ci(differences, seed=seed, confidence=confidence,
                                  resamples=resamples)
    return fmean(differences), low, high
