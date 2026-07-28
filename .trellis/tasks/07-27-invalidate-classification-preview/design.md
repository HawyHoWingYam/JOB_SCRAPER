# Design: Invalidate classification Preview after input changes

## State authority

Represent an accepted Preview as `{result, inputs, requestId}`. `inputs` is an immutable normalized snapshot of domain, applicable Source filters, and numeric limit. Skill snapshots omit Source filters because Skill selection is Source-independent.

An input key derived from the normalized snapshot owns validity:

- changing domain, Source selection, or limit invalidates the active Preview immediately;
- restoring old values does not resurrect a discarded Preview;
- Start remains disabled until a new successful Preview matches the current key.

## Request races

Advance a request sequence whenever a Preview begins or relevant inputs change. Commit a response only when its sequence is latest and its input key still equals the current key. Abort the prior request where the API helper supports `AbortSignal`; the sequence/key check remains the correctness backstop.

Start reads only the immutable inputs stored with the visible Preview. It never reconstructs a request from mutable controls. The backend continues to reselect and freeze candidate identities at Start; no preview token or Dispatch Plan is added.

## Compatibility

- No backend or HTTP payload change.
- Existing empty Preview, API error, active-run conflict, polling, Stop, and Retry behavior remains unchanged.
- Source arrays are normalized deterministically so checkbox order cannot create false validity.

## Validation

Component tests cover domain, Source, and limit invalidation; no resurrection; out-of-order responses; Start payload equality; empty/error states; and Skill's Source-independent payload.
