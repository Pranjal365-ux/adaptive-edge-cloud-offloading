"""Small, testable destination-selection policies for the simulator."""
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class DecisionContext:
    work_mi: float
    input_mb: float
    output_mb: float
    edge_service_seconds: float
    cloud_service_seconds: float
    upload_seconds: float
    download_seconds: float
    one_way_latency_seconds: float
    edge_wait_seconds: float
    cloud_wait_seconds: float
    upload_wait_seconds: float
    download_wait_seconds: float
    cloud_cost_usd: float
    cost_weight_seconds_per_usd: float


class Policy(Protocol):
    name: str

    def choose(self, context: DecisionContext) -> str: ...


class EdgeOnly:
    name = "edge_only"

    def choose(self, context: DecisionContext) -> str:
        return "edge"


class CloudOnly:
    name = "cloud_only"

    def choose(self, context: DecisionContext) -> str:
        return "cloud"


@dataclass(frozen=True)
class Threshold:
    threshold_mi: float
    name: str = "threshold"

    def choose(self, context: DecisionContext) -> str:
        return "cloud" if context.work_mi > self.threshold_mi else "edge"


class AdaptiveOracle:
    """Simulation-only policy: uses exact queued service estimates available to the model."""
    name = "adaptive_oracle"

    def choose(self, context: DecisionContext) -> str:
        edge = context.edge_wait_seconds + context.edge_service_seconds
        cloud = (context.upload_wait_seconds + context.upload_seconds
                 + context.one_way_latency_seconds + context.cloud_wait_seconds
                 + context.cloud_service_seconds + context.download_wait_seconds
                 + context.download_seconds + context.one_way_latency_seconds
                 + context.cost_weight_seconds_per_usd * context.cloud_cost_usd)
        return "cloud" if cloud < edge else "edge"


class AdaptiveObserved:
    """Adaptive policy; the simulator supplies EWMA probes and learned service rates."""
    name = "adaptive"

    def choose(self, context: DecisionContext) -> str:
        edge = context.edge_wait_seconds + context.edge_service_seconds
        cloud = (context.upload_wait_seconds + context.upload_seconds
                 + context.one_way_latency_seconds + context.cloud_wait_seconds
                 + context.cloud_service_seconds + context.download_wait_seconds
                 + context.download_seconds + context.one_way_latency_seconds
                 + context.cost_weight_seconds_per_usd * context.cloud_cost_usd)
        return "cloud" if cloud < edge else "edge"
