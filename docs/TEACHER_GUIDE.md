# Presenter and viva notes

## Project in one sentence

OffloadOps routes surface-inspection tasks between edge and cloud workers using selectable policies, and includes a separate simulator for controlled policy comparisons.

## Explain the architecture

Image in browser → edge gateway → local worker OR configured cloud worker → annotated result.

Both workers use the same surface-inspection code. In the local Compose setup, Toxiproxy controls the cloud link and Prometheus/Grafana provide monitoring. A configured Azure worker is another deployment option. Pranjal must confirm the actual endpoint and routing path before claiming a live Azure demonstration.

## Questions to prepare for

| Question | Answer |
|---|---|
| What is the threshold? | Fixed-threshold routing compares estimated workload with a configured cutoff. The live code defaults to 500,000 work units; deployment configuration can override it. |
| What makes routing adaptive? | It updates network and service-time estimates, estimates waiting time, and compares edge time with cloud time plus a weighted estimated cost. |
| Is this machine learning? | No trained model is used for routing or inspection. Routing uses estimates; inspection uses neighborhood contrast and connected regions. |
| Why can cloud be slower? | Upload time, network overhead, queueing, and processing all contribute. More compute does not remove communication overhead. |
| What is PASS or REVIEW? | PASS means the heuristic did not flag qualifying regions; REVIEW indicates candidate anomalies. Neither is a certified quality decision. |
| Are predictions measurements? | No. Predicted edge/cloud times are estimates before execution. Gateway elapsed and worker compute come from the completed request. Gateway elapsed excludes the browser-to-gateway connection. |
| Does priority change routing? | The priority field is metadata in this implementation; it does not establish priority scheduling. |
| Does comparison change the policy? | No. It runs both paths concurrently and reports their individual results. Completed work can update service estimates. |
| What happens when cloud fails? | A routed cloud task can fall back to local execution. Repeated failures can open the circuit breaker. Failure detection can add delay. |
| Does adaptive always win? | No. Estimates can lag, conditions change, and workload matters. A single comparison is illustrative, not a benchmark conclusion. |
| Are displayed costs Azure charges? | No. The cost model is synthetic. Historical sample CSVs are simulation outputs, not Azure measurements. |
| Is the cloud really remote? | Answer according to the verified demo setup: a local container emulates the cloud role; Azure is a remote deployment only when configured and verified. |

## Repository map

- services/: edge gateway, cloud worker, browser console.
- offloader/: shared image processor, policies, simulator, and synthetic cost model.
- monitoring/ and toxiproxy/: observability and controlled network scenarios.
- infra/: current Container Apps infrastructure; terraform/ and azure_function/ retain the older prototype.
- .github/workflows/: validation, image publishing, and Azure deployment configuration.
- sample_results/: historical synthetic examples.

## Deployment statements that need confirmation

An older version of this guide named an Azure deployment as live. That is a historical claim, not a current readiness check. Confirm readiness and the running revision on Pranjal's machine before presenting it as deployed.

The checked-in deploy-azure.yml workflow is configured to deploy after CI succeeds on main, or manually using an immutable image tag. It requires the azure-production environment, Azure variables, and OIDC access. The presence of the workflow is not proof that a GitHub Actions run succeeded.

The existing verification and blockers documents record earlier sessions. They are not an up-to-date status dashboard. Use [the handoff checklist](PRESENTATION_HANDOFF.md) for this UI change and [the demo script](DEMO.md) for the talk.
