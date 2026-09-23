# Implementation plan: Fix automated classification QA defects

## Delivery sequence

- [x] Review and approve this parent plan and all three child plans.
- [x] Implement `07-27-invalidate-classification-preview`; preserve its test evidence and defer closure to aggregate manual QA.
- [x] Implement `07-27-localized-generic-skill-retry`; preserve its test evidence and defer closure to aggregate manual QA.
- [x] Implement `07-27-company-industry-source-mapping`; dry-validate before the approved idempotent sandbox synchronization and defer closure to aggregate manual QA.
- [x] Run the aggregate automated classification regression suite.
- [x] Close #36/#37 with their focused automated evidence and the current full
  E2E regression; the user explicitly waived a separate human browser pass.
  Close #38 as superseded by removal of Company Industry.
- [x] Preserve targeted evidence on #36/#37/#38 and aggregate evidence on
  #32/#34; add a closure summary that distinguishes verified fixes from the
  superseded Company scope.

## Parent integration gate

- [x] Frontend classification component tests pass (11/11).
- [x] Backend classification runtime and current-taxonomy tests pass (52/52 relevant aggregate tests).
- [x] Frontend lint and production build pass; full frontend suite passes (204/204).
- [x] Backend Ruff and relevant test suites pass. Mypy was executed; the repository's existing SQLAlchemy typing baseline remains (811 errors), with no direct errors in the new manifest module or new Company adapter path.
- [x] Existing 27-test QA baseline remains covered; added regression cases raise the focused classification component count from 9 to 11 and the aggregate relevant backend count to 52.
- [x] Automated regression proves localized generic terminal resolution and
  Preview invalidation. The mapped-Company scenario is explicitly superseded,
  not claimed as executed.
- [x] The final Jev project regression and browser E2E completed with no active
  classification batch left as a closure dependency.

## Review and rollback points

- Review after each child; do not bundle a failing child with successful ones.
- Before mapping synchronization, validate all manifest entries and save the command's deterministic proposed-change summary.
- If mapping synchronization or Company QA fails, restore the prior manifest, rerun synchronization, and verify readiness without changing unrelated taxonomy state.
- Update `.trellis/spec/backend/automated-classification-batches.md` and `.trellis/spec/backend/ordinary-current-taxonomies.md` when implementation makes the new contracts executable.
