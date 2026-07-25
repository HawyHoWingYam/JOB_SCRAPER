# Technical design

## Components

- `JobsDBBrowserDetailScraper`: consumes an allocated fresh profile or explicit fixed profile and reports structured launch/attach stages.
- Profile manager/recovery utility: allocates task-owned directories, lazily reaps expired orphans, checks liveness, removes only safe singleton markers, and performs terminal cleanup.
- Crawl dispatch/recovery service: persists profile metadata in request/resume context, performs one cleanup/retry per Resume, and exposes a Reset action without changing the detail checkpoint.
- Manual-action normalization/projection: derives capabilities for legacy and current events, suppresses unsafe actions when liveness is unknown, and preserves the explicit headless→headed verification exception.
- Task-control frontend: renders explicit strategy buttons and diagnostics using the normalized action projection; the existing ManualActionRecoveryPanel remains the helper implementation source.

## Reset flow

1. Frontend requests Reset for a task in `manual_action_required` and confirms the operator intent.
2. Backend loads the latest manual-action event and normalizes its profile metadata.
3. Backend checks matching process liveness and registry/helper reachability. If unknown or live, return `reset_available=false` with diagnostics and leave the task unchanged.
4. If safe, remove known singleton markers (or delete the task-owned temporary directory), clear stale registry state, and record a reset event.
5. Return the same task as resumable; the next explicit Resume creates/uses a fresh isolated profile and filters detail statuses from the stored classification.

## Manual verification flow

For any supported manual challenge, including one raised by a headless task, the UI can start/check the Host Helper, open the dedicated headed browser, and then submit `reuse_open_browser`. The worker attaches to the registered CDP session only for that recovery attempt. If the helper is offline or the session is not reachable, the task stays paused and the UI shows the concrete prerequisite.

## Data and safety

Profile paths are operational metadata, not target scope. Fresh profile allocation is task-owned and retained while active/manual, cleaned after terminal outcome, and eligible for 24-hour lazy orphan cleanup. Fixed reuse profile data is never deleted by task cleanup. Process/registry adapters are injectable to make fail-closed behavior testable.

## API/UI compatibility

Keep existing `resume` strategy literals and legacy events. Add the Reset action and richer diagnostics as optional fields/actions so older clients can continue to submit Fresh Profile. New Task Details controls are capability-gated and share the existing helper endpoints where possible.
