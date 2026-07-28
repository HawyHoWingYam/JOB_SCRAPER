# Implementation plan: Invalidate classification Preview after input changes

- [x] Add failing component tests for Source and limit invalidation after a successful Preview.
- [x] Add failing tests for domain invalidation, restoring old values, and Start remaining disabled until fresh Preview.
- [x] Add a deferred-response test proving an older Preview cannot overwrite a newer request/input state.
- [x] Introduce one normalized immutable Preview-input builder shared by Preview and Start.
- [x] Store accepted Preview inputs with the response and invalidate them on every material input change.
- [x] Add request sequence/abort handling and ignore stale success or failure completion.
- [x] Make Start submit only the stored Preview inputs.
- [x] Run `cd frontend && npm test -- --run src/components/classification/ClassificationBatchesPage.test.jsx`.
- [x] Run `cd frontend && npm run lint && npm run build` as separate verification steps if required by shell policy.
- [ ] Manual QA #37 with Source and limit changes; attach UI/network evidence showing Start cannot consume unconfirmed inputs.

## Rollback point

Revert the state transition and tests together. No backend rollback is required.
