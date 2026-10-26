"""Explicit synthetic cloud-cost estimate used by the live routing policy.

This is not an Azure invoice estimator. Verify against current pricing, region,
plan, free grants, egress tier and account terms before using it for a budget.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class CostModel:
    compute_usd_per_second: float = 0.0001
    request_usd: float = 0.0
    egress_usd_per_gb: float = 0.0

    def estimate(self, compute_seconds: float, response_mb: float) -> float:
        if compute_seconds < 0 or response_mb < 0:
            raise ValueError("cost inputs must be nonnegative")
        return (
            compute_seconds * self.compute_usd_per_second
            + self.request_usd
            + response_mb / 1000 * self.egress_usd_per_gb
        )
