# Five-minute classroom demo

Start with `.\tasks.ps1 demo` and keep the console at `http://localhost:8000/console` visible. Use the browser UI; the expected observations below describe behavior, not fixed result values.

| Time | Action | What to point out |
|---|---|---|
| 0:00–0:30 | Open the console and the architecture panel. | The edge gateway receives the task. Local CPU work runs in worker processes. Cloud requests pass through Toxiproxy to the cloud worker. |
| 0:30–1:00 | Generate the sample scratched-part image and inspect the preview and job settings. Choose `edge_only`, then submit. | The input image and inspection request are visible. The response includes PASS/REVIEW, suspected defect count, processing time, and the annotated output image. |
| 1:00–1:30 | Choose `cloud_only`, then submit the same sample again. | The image is sent to the cloud worker through Toxiproxy. Compare route, timings, verdict, and output; the image pixel count creates meaningful processing work. |
| 1:30–2:00 | Choose `adaptive` and submit a few jobs. | The reason panel uses estimated edge/cloud completion, image work units, queue activity, network probes, and the synthetic cost term. Estimates update from completed work. |
| 2:00–2:45 | Apply `Poor network`, wait for probes, then submit the image again. | The RTT/throughput panels react to the injected network condition. Adaptive routing can keep image processing local when transfer is predicted to dominate. |
| 2:45–3:20 | Apply `Flapping`, then `Random walk`. | The route changes over time. Flapping alternates the configured good/poor phases; random walk uses a fixed seed for repeatable direction changes. |
| 3:20–4:20 | Run `Race mode · simulated`. | All policies receive one common seeded workload and network trace. The race is explicitly simulated; `adaptive_oracle` is shown separately from observable adaptive. |
| 4:20–5:00 | Open Grafana and show the live overview. | Prometheus scrapes policy decisions, latency histograms, queue/probe gauges, errors, and model cost. The cloud cost is a synthetic estimate, not a bill. |

If the live stack is unavailable, run `.\tasks.ps1 demo-replay`. It prints the committed historical synthetic session and must be described as simulator output, not live Azure data.
