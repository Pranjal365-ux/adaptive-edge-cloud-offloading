# Five-minute OffloadOps demo

Start the local stack with .\tasks.ps1 demo, then open http://localhost:8000/console. Wait for the gateway and cloud worker telemetry indicators to turn live.

| Time | Action | What to explain |
|---|---|---|
| 0:00–0:40 | Show the edge gateway, cloud worker, and live utilization charts. | The gateway receives the job. The two charts report rolling busy-worker-slot time; they do not represent host CPU. Throughput counts completed jobs in the last minute. |
| 0:40–1:20 | Keep the built-in scratched-part image at High detail, select Edge only, and submit it. | The input image, job envelope, destination, inspection verdict, defect candidates, compute time, and annotated output are visible. |
| 1:20–2:00 | Check Compare edge + cloud on this image and submit the same input. | The gateway starts both workers concurrently. Each independently returns an annotated image and timing, so this is a live comparison rather than a simulation. |
| 2:00–2:45 | Switch to Adaptive, apply Good network, wait for probe updates, and submit. | Adaptive compares estimated edge and cloud completion using image size, queue activity, measured RTT/throughput, learned service rates, and a synthetic cost term. It can select either worker. |
| 2:45–3:30 | Apply Poor network and submit again. | The local Toxiproxy adds latency and limits bandwidth. The graph and route estimates should react; edge can be preferable when sending the image takes too long. |
| 3:30–4:15 | Show the route indicator and recent decisions. | Explain the policy reason and whether a cloud failure triggered local fallback. For a direct Azure worker URL, Toxiproxy controls are disabled because the traffic bypasses the local proxy. |
| 4:15–5:00 | Open Grafana and the Prometheus targets page. | Prometheus scrapes local application metrics; Grafana loads its provisioned dashboard. Cloud estimates are synthetic and are not an Azure invoice. |

For Azure-backed mode, set AZURE_WORKER_URL and CLOUD_API_KEY in Windows user environment variables, then run .\tasks.ps1 demo-azure. The dashboard and edge gateway remain local; only the cloud worker is hosted in Azure. Docker Desktop therefore needs to remain running for this mode.