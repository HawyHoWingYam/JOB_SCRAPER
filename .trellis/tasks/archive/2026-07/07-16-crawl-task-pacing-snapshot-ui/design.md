# Design: Crawl Task pacing and cancellation projection

## Backend Projection

Extend the explicit Crawl Task schema instead of relying on `extra="allow"`.
The snapshot service owns normalization:

- detail phase + valid stored snapshot -> typed pacing object;
- detail phase + missing/legacy snapshot -> null plus not-recorded semantics;
- listing phase -> no pacing card projection.

Add cancellation events to progress-context selection and `cancelling` to active
and operator-state projection. Rendering consumes normalized fields and does not
re-parse request payloads.

## Task Details Layout

Place `Detail Pacing` with task facts/metrics and before recovery/Danger Zone.
Use three compact labelled values:

- Random interval: `1-3 seconds`
- Burst: `20 attempts`
- Burst pause: `30 seconds`

For legacy detail tasks, the card says `Not recorded` with no inferred values.

## Action State

Use backend status as the durable truth and local action pending only for the
request round trip. After Cancel returns `cancelling`, refetch/poll the selected
task and display that status. Disable both Cancel and Resume during cancellation.
Terminal states do not expose invalid actions.

## Testing

Backend snapshot tests cover typed values, malformed/missing legacy payloads,
listing omission, and cancellation event ordering. Frontend tests cover all
action/status combinations and exact pacing labels without runtime counters.
