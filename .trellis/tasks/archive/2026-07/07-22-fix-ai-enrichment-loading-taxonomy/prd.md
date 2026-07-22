# Fix AI enrichment loading and taxonomy exclusions

## Goal

Make the AI Enrichment console usable against the current OfferToday backlog:
the page should load its overview/monitor data reliably, and historical pending
jobs should either be safely repaired into the governed source-catalog model or
remain visibly and intentionally excluded with an actionable recovery path.

## Background and confirmed facts

- The console loads `GET /api/v1/ai/overview` and
  `GET /api/v1/ai/runs?monitor=true` in parallel and applies an 8-second
  frontend timeout (`frontend/src/components/ai/AIEnrichmentPage.jsx:326-425,
  557-635`).
- The monitor serializer includes the full `job_ids` array even though
  `AIEnrichmentPage` does not consume it (`backend/app/api/ai.py:289-358`,
  `frontend/src/components/ai/AIEnrichmentPage.jsx`). The current local
  responses are approximately 79 KB for overview and 83 KB for monitor runs.
- A local probe on 2026-07-22 returned HTTP 200 for both endpoints in under
  0.1 seconds, so the reported timeout is not currently reproducible against
  the local API. It may be transient or environment-specific, but the payload
  shape is an avoidable latency risk.
- The current local database has 9,458 pending OfferToday jobs. All 9,458 have
  a Source Job Attribute projection and classification path, but every path has
  a NULL `source_catalog_revision_id`; the active OfferToday catalog revision
  is sequence 1 (`e2f6f849-d696-4141-a14e-429373cb417b`), published on
  2026-07-20.
- Canonical preflight intentionally fails closed when a path lacks catalog
  provenance (`backend/app/job_intelligence/canonical_taxonomy/evaluator.py:520-542`,
  `backend/app/job_intelligence/canonical_taxonomy/preflight.py:31-64`). The
  preview therefore correctly reported `source_catalog_provenance_missing`,
  excluded 2,000 selected jobs, and enabled zero jobs.
- Project contracts prohibit bypassing preflight or treating legacy scalar
  classification fields as canonical authority (`.trellis/spec/backend/ai-enrichment-runs.md`,
  `.trellis/spec/backend/source-job-attributes.md`,
  `.trellis/spec/backend/canonical-job-taxonomy.md`).

## Requirements

### R1. Keep taxonomy safety fail-closed

The fix must not make a job AI-eligible merely because it has a legacy source
classification scalar. Missing or mismatched source-catalog provenance must
remain a distinct non-provider exclusion unless a governed repair process has
validated and persisted the missing provenance.

### R2. Define a safe historical OfferToday recovery path

For historical OfferToday paths with missing catalog provenance, add a
deterministic, auditable recovery path only if the current published catalog is
confirmed to cover every stored source-classification identity involved. The
recovery must preserve source identity, use the existing `SourceJobAttributes`
projection boundary, and be repeatable without duplicate evidence or outbox
events. Unrecoverable or ambiguous jobs remain excluded with their stable
reason.

### R3. Make AI console bootstrap resilient

The overview and monitor endpoints must return only the fields needed by their
consumer, avoiding full per-run job-ID payloads in the monitor response. The
console must retain truthful partial/degraded error handling and must not show
fabricated queue counts when bootstrap requests fail.

### R4. Preserve filtered-run truthfulness

Preview and create must continue to agree on selected, effective, and excluded
counts. The Pending Limit must still apply before exclusions, jobs must launch
oldest first, and an all-excluded selection must never dispatch an empty worker
run.

### R5. Add regression coverage

Cover the historical recovery validation/no-op behavior, missing and mismatched
provenance, compact monitor serialization, bootstrap timeout/degraded behavior,
and existing mixed/all-excluded filtered-run contracts.

## Acceptance Criteria

- [ ] A current-corpus AI Enrichment page loads overview and monitor data
      without serializing unused full `job_ids` arrays in the monitor payload.
- [ ] A deterministic check reports every historical OfferToday classification
      identity that is absent from or incompatible with the selected published
      catalog revision before any repair write occurs.
- [ ] If the recovery decision is approved, all covered historical OfferToday
      paths are reprojected through `SourceJobAttributes`, preserve their
      evidence identity, and become eligible only after canonical preflight
      succeeds; exact replay is idempotent.
- [ ] Jobs that cannot be safely recovered remain excluded with
      `source_catalog_provenance_missing` or a more specific stable reason and
      are never mislabeled as provider failures.
- [ ] Preview/create parity, oldest-first ordering, limit-before-exclusion,
      all-excluded no-dispatch, and retry semantics remain unchanged.
- [ ] Focused backend and frontend tests pass, including the existing
      `AIEnrichmentPage` and `test_ai_enrichment_runs.py` suites.

## Resolved product decision

The current published OfferToday catalog revision may repair historical pending
OfferToday paths, but only after a deterministic read-only coverage check and
through a separate operator-approved repair command/migration that pins the
expected revision. A revision drift or incomplete identity coverage aborts the
write. This restores the backlog without weakening fail-closed policy.

## Scope boundaries

- Do not bypass canonical taxonomy mappings or source-catalog provenance.
- Do not change LLM provider, prompt, retry, or worker behavior.
- Do not perform an unreviewed live bulk write while developing the fix.
- Keep company enrichment and unrelated crawl automation out of scope.

## Notes

- Keep `prd.md` focused on requirements, constraints, and acceptance criteria.
- Lightweight tasks can remain PRD-only.
- For complex tasks, add `design.md` for technical design and `implement.md` for execution planning before `task.py start`.
