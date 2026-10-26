# Measurement and implementation boundaries

## Active application

The edge gateway and cloud worker call the same explainable image-inspection implementation. It decodes a bounded JPEG/PNG/WebP image, compares pixels to a local median surface, groups high-contrast regions, and returns a verdict with an annotated image. This is a classroom heuristic, not a trained or certified quality-inspection model.

The adaptive router estimates task completion from image work units, measured application-level cloud RTT and probe throughput, local queue activity, learned worker service rates, and a synthetic cloud-cost term. Estimates are not platform scheduling guarantees. The cloud cost term is a teaching assumption and must not be described as actual Azure billing.

## Metrics

- Edge and cloud utilization represent rolling busy-worker-slot time over ten seconds, divided by the configured slot capacity. This is application telemetry, not Azure host CPU or memory utilization.
- Throughput is the gateway's count of successful jobs in a rolling sixty-second window, split by final destination. It is not a long-run benchmark.
- Cloud RTT includes HTTP/service overhead. The probe transfer rate is application-level response throughput, not available link capacity.
- Task end-to-end time includes request transfer, network and service overhead, queueing, image processing, and response transfer. Worker compute time is reported separately.
- A live same-image comparison sends independent requests to both workers concurrently. Their end-to-end times include their respective request paths and are affected by current network conditions.
- Azure Monitor and Container Apps logs describe the deployed Azure worker. Local Prometheus/Grafana scrape the local Compose services. The local edge can query a remote Azure worker, but that does not turn local edge metrics into Azure-host metrics.

## Failure and fallback

The gateway can fall back to edge processing if the cloud request fails or the circuit breaker is open. A comparison request reports each side independently and does not silently substitute edge output for a failed cloud result. Do not retry timed task submissions automatically because a remote task may have completed even when its response was lost.

## Reproducibility and scope

Historical simulation code, old Azure Functions prototypes, experiment drivers, and generated result files were moved to the sibling archive outside this deliverable repository. They remain available for reference but are not part of the live image-inspection application or its current deployment path.