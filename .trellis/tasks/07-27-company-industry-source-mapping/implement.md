# Implementation plan: Add Company Industry Source Mapping setup path

## Manifest and synchronization

- [x] Add failing parser/validator tests for duplicate labels, malformed keys, missing reasons, non-mapping with targets, mapped without targets, unknown/inactive/non-assignable targets, missing observed OfferToday labels, and cross-Source isolation.
- [x] Define the current-state manifest schema and one loader/normalizer shared by the management command and runtime resolver.
- [x] Conservatively disposition all 54 observed OfferToday runtime labels with stable reasons and no invented leaf mappings. The current all-non-mapping manifest was approved on 2026-07-28; any future positive leaf mapping still requires target-specific evidence and review.
- [x] Implement deterministic dry validation and per-Source change planning.
- [x] Implement per-Source atomic positive-mapping synchronization into `current_source_taxonomy_mappings`, including stale-row removal and idempotence.
- [x] Add the explicit deployment management command with non-zero failure exit and stable JSON/text summary.
- [x] Test rollback, repeated runs, full pre-mutation validation, and absence of startup mutation.

## Runtime and API

- [x] Add a shared Company disposition resolver that checks manifest authority and exact positive DB projection.
- [x] Refactor Company candidate selection to return bounded mapped items, explicit exclusions, and actionable unsupported items without per-candidate query amplification.
- [x] Extend Preview schemas/serialization with selected, mapped/effective, unmapped/error, and excluded-non-mapping counts/details.
- [x] Enforce `mapped > 0` in backend Start as well as the UI.
- [x] Preserve per-item transaction isolation for unsupported items in partially ready batches.
- [x] Prove explicit non-mapping Companies create no Batch item and never enter failed-only Retry.

## Frontend and verification

- [x] Render Company mapping readiness counts/reasons and disable Start when mapped is zero.
- [x] Add frontend tests for zero-ready, partial-ready, exclusions, and unaffected Job/Skill tabs.
- [x] Run targeted backend tests including `tests/test_current_taxonomies.py` and `tests/test_classification_batch_runtime.py` (52 passed).
- [x] Run classification API tests and backend Ruff; run Mypy and record the existing SQLAlchemy typing baseline (811 errors, no direct errors in the new manifest module or new Company adapter path).
- [x] Run targeted and full frontend tests (204 passed), frontend lint, and production build.
- [x] Run the management command in validation/dry mode and inspect the complete OfferToday summary (54 non-mapping dispositions, zero positive changes).
- [x] Apply the approved current manifest to the shared sandbox (idempotent zero-change synchronization).
- [ ] Manual QA is explicitly deferred: UI-hit one explicit exclusion and one missing/invalid disposition failure, then test a positive mapped Company after target-specific evidence supplies a defensible leaf. The synthetic real-write test already proves assignment provenance.
- [x] Update ordinary-current-taxonomy and automated-classification-batch specs.

Shared-sandbox Preview smoke for OfferToday limit 100 completed after synchronization: selected 100, mapped 0, unsupported 100, excluded 0. The oldest bounded population has no retained Source Industry Label evidence, so the backend correctly blocks Start without pulling replacement Companies beyond the limit.

## Rollback points

- Before sandbox application: no database rollback is needed.
- After application: restore the prior manifest, rerun the same atomic synchronization command, and verify exact positive mapping rows/readiness.
- Never repair mapping failures with direct SQL, inferred display-name joins, fallback targets, or a startup side effect.
