# Invalidate classification preview after scope changes

## Goal

Fix GitHub issue #37 so changing Source or limit after Preview invalidates confirmation and disables Start until a fresh preview.

## Background

- The UI currently clears Preview when the classification domain changes, but not when Source or limit changes.
- Start eligibility checks only that some Preview exists with a non-zero count; it does not verify that Preview inputs match current inputs.
- Start sends current form inputs rather than the inputs that produced the displayed Preview.
- Preview responses are applied unconditionally, so a late response for older inputs can replace a newer result.
- The backend Preview response has no token, input hash, or Dispatch Plan identity. Start reselects candidates using its request and only then freezes the Classification Processing Batch snapshot.
- For this fix, Preview remains an advisory selection estimate bound to exact inputs; it does not freeze candidate identities.

## Requirements

- A Preview must be associated with the exact domain, Source filter, and limit that produced it.
- Any material input change invalidates the displayed Preview and disables Start until a matching Preview succeeds.
- A late response for superseded inputs must not become the active Preview.
- Start must submit the exact inputs associated with the active Preview rather than independently reading mutable form state.
- Candidate identities continue to be selected and frozen by the backend when Start creates the run; no preview token or single-use Dispatch Plan protocol is introduced.
- Skill remains Source-independent; changing a hidden/non-applicable Source filter must not affect Skill behavior.

## Acceptance Criteria

- [ ] Changing domain, Source selection, or limit invalidates the active Preview and disables Start.
- [ ] Restoring old form values does not silently resurrect a discarded Preview; a fresh Preview is required.
- [ ] An out-of-order Preview response cannot overwrite the result for newer inputs.
- [ ] Start submits the domain, filters, and limit associated with the visible Preview.
- [ ] Company Industry and Skill Preview/Start component tests cover their applicable input contracts. The former Job Taxonomy case is superseded by task `07-29-remove-canonical-job-taxonomy`.
- [ ] Backend run creation still freezes a stable candidate snapshot and existing lifecycle tests remain green.
