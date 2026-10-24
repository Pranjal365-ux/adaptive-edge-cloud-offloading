# UI and presentation handoff for Pranjal

## Scope

This handoff improves the existing console and presentation notes. It does not change backend routing, inspection algorithms, infrastructure, or dependencies. No application services, Docker stack, or Azure deployment were started for this work.

## Changes

- Presentation view retains policy controls, image input, results, comparison, and network controls; it hides charts, recent history, and technical details to reduce clutter.
- Result cards distinguish predicted edge/cloud times from measured gateway elapsed and worker compute. Missing time values show a dash.
- Policy help explains each option; polling no longer overwrites an unapplied selection. Inspection asks the user to apply a changed selection first.
- A shared busy state prevents overlapping inspection/comparison actions and input changes during a request. Each submission receives a new job ID.
- Comparison request failures clear the running result. Unavailable worker outcomes remain explicit.
- Status polling is bounded and non-overlapping; disconnected telemetry is marked stale and current values are cleared. Recovery removes the error state.
- API errors include readable validation details; a bounded request timeout explains that server processing may continue.
- Network scenario selection is shown only after acknowledgement; a failed change leaves the selection unconfirmed.
- Presenter documentation distinguishes local emulation, Azure deployment, synthetic results, and live measurements.

## Acceptance checks on the presentation machine

Record pass/fail, environment (local or Azure), and any screenshot/error for each check. These checks remain pending until Pranjal runs them.

| Check | Expected behavior |
|---|---|
| Startup | Console reaches the gateway; no browser JavaScript errors. |
| Projection and narrow window | Presentation view keeps the full task workflow accessible; controls and results remain readable at the actual projector resolution and at a narrow window width. |
| Sample inspection | Annotated image, verdict, destination, measured times, predicted times, and routing reason appear. |
| Policy selection | Choose a different policy and wait more than two polling intervals. Selection remains unchanged; it becomes active only after Apply succeeds. |
| Repeated clicks | During inspection or comparison, the other action and input controls are disabled; they recover after success or failure. |
| Repeat same image | Successive submissions use different job IDs. |
| Comparison | Both outcomes are shown. An unavailable worker has an explicit error, without a timing winner. |
| Validation | Empty camera source or invalid upload produces readable feedback, and the UI remains usable. |
| Gateway disconnect/recovery | Current metric values clear and telemetry says stale; recovery restores current values and removes the error state. |
| Comparison request failure | No panel remains falsely marked Running after a failed request; controls are usable again. |
| Proxy scenario | Confirm traffic actually traverses Toxiproxy. Successful scenario acknowledgement is shown; a failed change is not labelled applied. |
| Cloud fallback | With a rehearsed failure setup and Cloud only selected, a successful local result explicitly reports EDGE FALLBACK. |
| Request timeout | If encountered, the UI reports unknown completion and advises checking recent decisions before retrying. |

## Validation boundary

Completed: source/API-contract review, inline JavaScript syntax checking, unique HTML IDs and literal DOM-reference checks, and isolated UI regression checks with mocked responses. The regression checks covered pending policy selection, queue labels, telemetry disconnect/recovery, overlapping refresh prevention, structured validation errors, timeout messaging, comparison failure cleanup, and partial comparison results. No services or network calls were used. They do not prove browser layout, live HTTP behavior, cloud readiness, or performance. Visual and end-to-end acceptance remain with Pranjal.

This supplied directory has no Git metadata. Review the edited files against the original GitHub checkout before committing. The changed files are services/console.html, README.md, docs/DEMO.md, docs/TEACHER_GUIDE.md, and this handoff document.
