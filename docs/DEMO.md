# Five-minute presentation walkthrough

This script is for Pranjal on the machine hosting the working demo. Start and rehearse the system there using the existing setup instructions. The UI/documentation handoff does not establish that Docker or Azure is currently working.

## Before presenting

- Confirm one successful inspection and one edge/cloud comparison.
- Confirm whether the cloud worker is a local container or Azure. Say which setup you are showing; the UI does not discover deployment topology.
- Confirm whether cloud traffic passes through Toxiproxy before demonstrating network scenarios. A direct Azure connection can bypass the proxy.
- Load the built-in scratched-part sample. Use Standard detail and Normal sensitivity initially.
- Click **Presentation view** to hide telemetry charts and technical details while keeping policy selection, image input, results, and network controls available. Exit it to show monitoring.
- Have a screenshot or recording of a successful run available and label it as recorded if used.

## Demonstration

| Time | Action | Explanation |
|---|---|---|
| 0:00–0:40 | Show the request path and sample image. | “The gateway decides whether this image is inspected locally or by the cloud worker.” |
| 0:40–1:20 | Select **Edge only**, click **Apply**, then **Inspect image**. | Point to the destination, PASS/REVIEW result, suspected regions, and measured times. REVIEW means candidate anomalies need review. |
| 1:20–2:00 | Click **Compare edge + cloud**. | Both workers receive the same image concurrently. Each measured path includes its waiting and processing; cloud also includes network overhead. One run does not prove a universal winner. |
| 2:00–2:40 | Select **Fixed threshold**, apply it, and inspect. | Work above a configured cutoff goes to cloud. This workload cutoff is separate from image-detection sensitivity. Changing image detail can change workload, but a routing change is not guaranteed. |
| 2:40–3:30 | Select **Adaptive**, apply it, and inspect. | Compare the predicted times with the measured result. Adaptive uses estimates plus a weighted synthetic cloud-cost term; it is not a trained AI model. |
| 3:30–4:15 | If the proxy path was verified, apply **Poor**, allow probes to update, and inspect again. | Explain the observed network estimates and route. Do not promise an immediate route switch. |
| 4:15–4:45 | If rehearsed, demonstrate cloud failure with **Cloud only** and the verified timeout/failure setup. | The returned **EDGE FALLBACK** badge is evidence of fallback. A normal adaptive edge choice alone does not demonstrate a cloud failure. A first failure may wait for a timeout. |
| 4:45–5:00 | Restore **Good** and **Adaptive**; exit presentation view if time permits. | Worker utilization measures occupied slots, not CPU percentage. State the inspection and measurement limitations. |

Use fewer scenarios during the talk; Flapping and Random walk are optional questions-and-answers material. Restore normal conditions and allow recovery before another run.

## If something fails

- Gateway disconnected: the UI clears current metric values and marks telemetry stale. Check the running stack on the demo machine.
- One comparison worker unavailable: explain the partial outcome; there is no valid timing winner.
- Request timeout: the UI cannot confirm completion. Check recent decisions before retrying; browser timeout does not cancel server work.
- Live system unavailable: show the clearly labelled recording. The existing demo-replay command prints historical synthetic results, not live inspection or Azure evidence.
