# Five-minute classroom demo

Start with `.\tasks.ps1 demo` and keep the console at `http://localhost:8000/console` visible. Use the browser UI; the expected observations below describe behavior, not fixed result values.

| Time | Action | What to point out |
|---|---|---|
| 0:00–0:30 | Open the console and the architecture panel. | The edge gateway receives the task. Local CPU work runs in worker processes. Cloud requests pass through Toxiproxy to the cloud worker. |
| 0:30–1:00 | Choose `edge_only`, apply it, and send a sample task. | The decision feed identifies local execution and reports the measured completion time. |
| 1:00–1:30 | Choose `cloud_only`, apply it, and send another task. | The response includes the cloud replica and build SHA. Point to the RTT and throughput probe estimates; they include service overhead. |
| 1:30–2:00 | Choose `adaptive` and send several sample tasks. | The reason panel uses estimated edge and cloud completion, queue activity, network probes, and the synthetic cost term. Estimates update from completed work. |
| 2:00–2:45 | Apply `Poor network`, wait for probes, then send a task. | The RTT/throughput panels react to the injected network condition. The adaptive policy can keep work local when cloud transfer is predicted to dominate. |
| 2:45–3:20 | Apply `Flapping`, then `Random walk`. | The route changes over time. Flapping alternates the configured good/poor phases; random walk uses a fixed seed for repeatable direction changes. |
| 3:20–4:20 | Run `Race mode · simulated`. | All policies receive one common seeded workload and network trace. The race is explicitly simulated; `adaptive_oracle` is shown separately from observable adaptive. |
| 4:20–5:00 | Open Grafana and show the live overview. | Prometheus scrapes policy decisions, latency histograms, queue/probe gauges, errors, and model cost. The cloud cost is a synthetic estimate, not a bill. |

If the live stack is unavailable, run `.\tasks.ps1 demo-replay`. It prints the committed historical synthetic session and must be described as simulator output, not live Azure data.
