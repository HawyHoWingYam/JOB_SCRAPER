# Add Job AI Enrichment and Flexible Companies — Implementation Plan

## Delivery strategy

Keep the work in one Trellis task because the externally testable outcome depends on one cross-layer contract, but implement it in small rollback-safe slices. Do not start frontend behavior before the backend command/read contracts for that slice are executable.

The existing working tree is dirty. Before every slice, inspect overlapping changes and preserve unrelated user work. The project uses an empty-schema sandbox bootstrap rather than in-place migrations; never mutate or clear a shared database as part of automated implementation checks.

## 1. Lock the current product contracts with failing tests

- [ ] Add backend contract tests for the new Manual Job create/update command shapes:
  - existing versus new Company discriminated choice;
  - Company website validation and normalized response;
  - no `ai_description`, legacy `employment_type`, or `salary_range` in manual inputs;
  - structured salary/experience range validation;
  - duplicate-candidate response and explicit confirmation fingerprint;
  - idempotent replay, key/hash conflict, and concurrent-key behavior;
  - atomic rollback for Company + Job + governed Employment Types + receipt.
- [ ] Extend frontend tests first for the persistence-only Add Job labels, non-persisted Company draft, website, duplicate review, retry-safe key reuse, collapsed optional fields, and structured salary.
- [ ] Add read-contract fixtures for Manual Entry origin, editable/operator fields, structured salary, eligibility reason, and intelligence freshness.

Validation:

```bash
python3 -m pytest -q backend/tests/test_manual_job_product_contract.py
cd frontend && npm test -- src/components/jobs/AddJobPage.test.jsx
```

Rollback point: tests only; production behavior unchanged.

## 2. Change the current-schema storage model and retained-data contract

- [ ] Add nullable normalized `Company.website` and nullable `Company.ai_description_updated_at`.
- [ ] Remove `Company.extra_data` and every repository/backfill payload/write that targets it.
- [ ] Remove `Job.search_vector` and verify no read/write remains.
- [ ] Add Manual Job evidence/freshness storage that records:
  - current normalized evidence fingerprint;
  - the fingerprint last successfully enriched;
  - which optional values were operator-authored where needed to prevent AI overwrite;
  - captured/updated timestamps.
- [ ] Add a domain-owned manual mutation receipt with unique idempotency key, command hash, result Job/Company identities, and creation time. Do not couple ordinary Job creation to `GovernanceAuditEvent`.
- [ ] Register all current-schema models in metadata/bootstrap imports.
- [ ] Update sandbox cutover retained-table/column manifests, serialization, import ordering, verification, and fixtures. Preserve Company website, Manual evidence/freshness, and mutation receipts; remove the two deleted columns.
- [ ] Add metadata/bootstrap parity and disposable `_test` PostgreSQL coverage. Do not add Alembic or in-place upgrade behavior.
- [ ] Make the retained-artifact exclusion of `Company.extra_data` and `Job.search_vector` explicit and report their pre-cutover non-null counts for operator review. Do not claim those discarded values can be restored after artifact finalization.

Validation:

```bash
python3 -m pytest -q \
  backend/tests/test_crawl_control_bootstrap.py \
  backend/tests/test_sandbox_cutover.py \
  backend/tests/test_job_intelligence_test_safety.py
```

Rollback point: before a shared sandbox rebuild, revert models/manifests and leave the existing database untouched. After verified import and artifact finalization, deleted-column data has no rollback path; any correction requires a new full cutover.

## 3. Implement the `ManualJobIntake` deep module

- [ ] Define one normalized Manual Job facts contract used by create and update.
- [ ] Define the Company choice union:
  - `existing` with Company UUID;
  - `new` with name and optional website/location/Company Industry evidence.
- [ ] Centralize trimming, URL/currency/range validation, governed Employment Type code validation, and command hashing.
- [ ] Implement advisory Company duplicate lookup without name-based automatic merge.
- [ ] Implement likely Job duplicate lookup using Company, normalized title, location, and posted date.
- [ ] Bind explicit duplicate confirmation to the normalized command and current candidate identities; newly changed candidates require a fresh decision.
- [ ] Implement idempotency:
  - first key + hash performs the mutation and stores the result;
  - same key + hash replays the first result;
  - same key + different hash returns a stable conflict;
  - concurrent identical submissions converge on one receipt/result.
- [ ] Atomically create optional Company, Manual Job, governed Employment Type assignments, Manual evidence, and receipt. Establish explicit Manual Entry identity rather than inheriting JobsDB defaults.
- [ ] Implement update for Manual Jobs only. Reuse the same validation/Company/duplicate interfaces, replace governed Employment Types atomically, update Manual evidence fingerprint, and reject collected Source Jobs.
- [ ] Mark intelligence stale only when the normalized enrichment-relevant evidence fingerprint changes.

Target implementation area:

- `backend/app/schemas/job.py`, `backend/app/schemas/company.py`
- new or existing manual-intake contracts/module under `backend/app/job_intelligence/` or `backend/app/services/`
- `backend/app/models/job.py`, `backend/app/models/company.py`, new current-schema models
- `backend/app/repositories/company_repository.py`

Validation:

```bash
python3 -m pytest -q backend/tests/test_manual_job_product_contract.py
```

Rollback point: the deep module is testable before routes switch to it.

## 4. Switch Manual Job APIs and composed reads to the new interface

- [ ] Replace the existing `/api/jobs/manual` create implementation with the `ManualJobIntake.create` interface.
- [ ] Remove automatic run creation, outbox publication, terminal wait, and enrichment-success response semantics from Add Job.
- [ ] Add Manual-only update route through `ManualJobIntake.update`.
- [ ] Return stable duplicate/idempotency/validation error codes and composed current Job Detail results.
- [ ] Split Company create input from Company response; reject/exclude `ai_description` from ordinary create commands and add website to reads.
- [ ] Align `JobSchema`/`JobDetailSchema` product reads with structured salary, Job Origin, manual editability, enrichment eligibility, and freshness. Continue composing through `compose_current_job_detail`.
- [ ] Keep retired collected `POST /api/jobs` behavior unchanged.

Validation:

```bash
python3 -m pytest -q \
  backend/tests/test_manual_job_product_contract.py \
  backend/tests/test_job_intelligence_response_contracts.py \
  backend/tests/test_source_job_attribute_api.py
```

Rollback point: route switch can revert to the old implementation while the unused new module remains additive; do not restore automatic enrichment messaging in the frontend independently.

## 5. Implement the `JobEnrichmentEvidence` seam and origin-aware batches

- [ ] Introduce the shared inspection result with stable states including `supported`, `needs_job_description`, and existing governed Source exclusions.
- [ ] Implement the Source adapter over `SourceJobAttributes` and current Canonical Taxonomy preflight without weakening Source checks or identity rules.
- [ ] Implement the Manual adapter over Manual evidence:
  - require a non-blank description;
  - expose no Source Classification paths;
  - use the full active assignable Canonical Job Taxonomy;
  - preserve governed Employment Types and operator-authored-field protection.
- [ ] Replace direct `source_attribute_projection.has()` eligibility decisions in overview, pending counts, filter options, preview, create, and worker preflight with the shared inspection semantics or an equivalent query projection proven to match it.
- [ ] Preserve preview/create/worker parity and stable exclusion reasons.
- [ ] Make unenriched and stale Manual Jobs pending when supported. Count missing descriptions separately as `Needs job description`.
- [ ] Extend filter/read contracts from displayed Source to `Origin`; add Manual Entry. Source Classification/Subclassification filters apply only to external Source origins and never fabricate Manual paths.
- [ ] Update AI enrichment writes so operator-authored values are preserved. Successful Manual enrichment records the enriched evidence fingerprint and clears stale state in the same transaction as AI summary/taxonomy/skills replacement.
- [ ] Fill omitted Manual experience values from AI output, preserve operator-authored experience values, and retain conflicting AI extraction only as evidence. Add tests for omitted, matching, and conflicting cases.
- [ ] Ensure retry and active-run scheduling remain unchanged for existing Sources.
- [ ] Add Origin-path backend regressions proving empty filters without `all_pending_acknowledged` return 422, the acknowledgement remains ephemeral, and an explicit Manual-only scope never falls through to all pending.

Validation:

```bash
python3 -m pytest -q \
  backend/tests/test_ai_enrichment_runs.py \
  backend/tests/test_source_job_attributes.py \
  backend/tests/test_source_job_attribute_architecture.py \
  backend/tests/test_current_taxonomies.py
```

Rollback point: retain Source adapter behavior and disable Manual origin selection; persisted Manual Jobs/evidence remain valid intake records.

## 6. Rebuild Add Job and add Manual Job editing

- [ ] Extract one reusable Manual Job form module owning field state, normalization, validation display, Company choice/draft state, duplicate confirmation, and idempotency key lifetime.
- [ ] Rework Add Job core fields to title, Company, and description. Show `Optional for saving · Required for AI enrichment`.
- [ ] Move structured salary, location, governed Employment Types, posted date, and experience into `Optional job details`; remove free-text salary range.
- [ ] Keep typed new Company data local until final submit; add optional website and retain Company Industry as explicitly labelled evidence.
- [ ] Improve Company combobox keyboard navigation, loading/search error feedback, candidate identity detail, and stale-state reset when starting another Job.
- [ ] Handle duplicate-candidate decisions without changing the idempotency key for one logical submission.
- [ ] Replace all automatic-enrichment labels and result summaries with persistence-only success and ordinary navigation.
- [ ] Add Manual-only Edit action/form to Job Detail using the shared form module. Keep collected Jobs and AI-derived fields read-only.
- [ ] Render eligibility (`Needs job description`) and current/stale Job Intelligence distinctly in Job Detail/read consumers.

Validation:

```bash
cd frontend && npm test -- \
  src/components/jobs/AddJobPage.test.jsx \
  src/components/JobDetailModal.test.jsx
```

Rollback point: keep backend command available while reverting the frontend route to a read-only state; do not restore the old sequential Company creation call.

## 7. Extend the Job AI Enrichment console for Manual Entry

- [ ] Rename the displayed filter dimension from Source to Origin without changing external Source identities.
- [ ] Add Manual Entry option and Manual pending/needs-description metrics.
- [ ] Hide/disable Source Classification and Subclassification cascades when only Manual Entry is selected; mixed-origin filters retain external Source cascade semantics.
- [ ] Normalize request payloads so an explicit Manual-only selection cannot degrade to unfiltered all-pending scope.
- [ ] Preserve debounced/aborted preview, active-run conflict, monitor, exclusion, Stop, retry, and persisted-filter behavior.
- [ ] Preserve browser storage key `ai-enrichment-filtered-run:v1` and its existing payload fields/limit. The UI label changes to Origin, while the compatibility payload continues to store `source_sites` (including the manual discriminator); do not persist transient all-pending acknowledgement.
- [ ] Add storage regressions for existing v1 payloads, Manual Entry round-trip, invalid/stale selections, and read/write failure fallback to in-memory defaults.

Validation:

```bash
cd frontend && npm test -- src/components/ai/AIEnrichmentPage.test.jsx
```

Rollback point: hide Manual Entry in the console while retaining backend/manual evidence; external Source operations remain unchanged.

## 8. Add quantity-driven Company Generate and Regenerate runs

- [ ] Extend Company run request/storage with mode (`generate_missing` or `regenerate_existing`) and positive requested Run size. Do not add a product-level maximum; retain bounded worker concurrency.
- [ ] Generate freezes up to the requested number of blank-description Companies ordered by `created_at`, then ID.
- [ ] Regenerate freezes up to the requested number of non-blank Companies ordered by null/oldest `ai_description_updated_at`, then ID, and requires explicit confirmation.
- [ ] Persist frozen item IDs, mode, requested size, and Web Search intent. An existing active run retains its original intent.
- [ ] On success, update `ai_description` and `ai_description_updated_at` atomically. On failure, preserve both previous values.
- [ ] Add retry-failed behavior that reuses the original failed Company IDs and mode rather than reselecting a different cohort.
- [ ] Update Companies page controls, explanatory copy, progress/run summaries, confirmation, and failure retry. Manual Companies require no special eligibility branch.
- [ ] Keep Company Web Search explicit, default-off, fingerprint-gated, and never exposed on Job enrichment.

Validation:

```bash
python3 -m pytest -q backend/tests/test_company_enrichment.py
cd frontend && npm test -- src/components/companies/CompaniesPage.test.jsx
```

Rollback point: disable Regenerate and Run-size controls while retaining missing-description Generate behavior; additive timestamps may remain nullable.

## 9. Cross-layer fixtures, specs, and full verification

- [ ] Update backend-owned and frontend mirror fixtures exactly once through the product-read seam.
- [ ] Update `.trellis/spec/backend/ai-enrichment-runs.md` for Manual evidence eligibility, Origin filters, freshness, and preview/create/worker parity.
- [ ] Update `.trellis/spec/backend/company-enrichment-runs.md` for mode, Run size, deterministic selection, retry, and description scheduling timestamp.
- [ ] Update `.trellis/spec/backend/source-job-attributes.md` to state explicitly that Manual evidence is separate and Source projection constraints remain unchanged.
- [ ] Update `.trellis/spec/backend/job-intelligence-product-surfaces.md`, database/cutover specs, and frontend AI console spec for the final contracts.
- [ ] Search for removed columns, obsolete auto-enrichment copy, legacy Manual Job salary input, and direct Manual Source projection assumptions.
- [ ] Run targeted tests, then full backend/frontend gates.

Validation:

```bash
rg -n "extra_data|search_vector|Create Job & Enrich|AI enrichment will run automatically" backend frontend
python3 -m pytest --collect-only -q backend/tests
python3 -m pytest -q backend/tests
cd frontend && npm test
cd frontend && npm run lint
cd frontend && npm run build
```

PostgreSQL-only validation, when the disposable `_test` services are available:

```bash
python3 -m pytest -q backend/tests/integration/test_sandbox_cutover_rehearsal.py
```

Final rollback boundary: do not rebuild the shared sandbox until the complete code set, retention artifact checks, full test suite, and operator stop/export/clear confirmations are ready.
