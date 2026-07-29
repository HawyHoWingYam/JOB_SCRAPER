# Implementation Plan: Remove Canonical Job Taxonomy

## Preconditions

- Keep the change atomic across backend, frontend, schema bootstrap, fixtures, and specs.
- Preserve unrelated existing worktree changes.
- Before each edit, read the exact owning code and relevant active Trellis spec.
- Do not run destructive commands against shared `jobsdb` during implementation or
  automated verification; use disposable databases ending in `_test`.

## 1. Resolve task and spec conflicts

- [x] Inspect active Job-taxonomy-specific tasks and mark their requirements as
      superseded or re-scope them before code changes:
      `07-27-invalidate-classification-preview`,
      `07-27-qa-automated-classification-frontend`, and the Job portions of
      `07-27-fix-automated-classification-qa-defects`.
- [x] Preserve the Company Industry mapping and localized Skill Candidate task scopes.
- [x] Record affected specs to update: ordinary current taxonomies, automated
      classification batches, AI enrichment runs, product reads, search, Dashboard,
      database/cutover, and source attributes where references require narrowing.

## 2. Lock the removal with focused tests

- [x] Update/add backend contract tests that expect no Job taxonomy routes, schemas,
      product fields, filters/facets, stats, export field, classification domain, or
      recommendation taxonomy score.
- [x] Add recommendation tests for exact 0.80/0.15/0.05 scoring and unchanged title
      deduplication/candidate retrieval.
- [x] Add embedding tests proving taxonomy text/events are absent and governed Skill
      names remain.
- [x] Update/add frontend tests for removal from Job detail, Job Browser, filters/routes,
      Dashboard, classification console, and Related Jobs.
- [x] Retain explicit regression assertions for Source Classification Paths, Company
      Industry, Governed Skills, Skill Candidate Evidence, and automatic Candidate
      processing.

## 3. Remove backend Job taxonomy domain and persistence

- [x] Remove `CurrentJobTaxonomyAssignment`, its table export, Job assignment commands,
      Job reader/state/embedding methods, Job seed transform, and package exports.
- [x] Remove `job` rows/allowed discriminator values from shared current-taxonomy node,
      alias, and mapping behavior while retaining Company Industry and Skill storage.
- [x] Remove Job Taxonomy seed data and synchronization calls.
- [x] Remove Job Source-to-Canonical mapping resolution and enrichment candidate slices.
- [x] Remove Job Taxonomy schemas and `/job-taxonomy` routes.
- [x] Narrow sandbox table inventories, retained row transforms, import order, target
      verification, and forbidden-table checks to the new schema.

## 4. Remove processing and downstream backend contracts

- [x] Remove Job taxonomy extraction/assignment from AI enrichment and ingestion repair
      paths; keep Job summaries, Company Industry, and Skills intact.
- [x] Remove `job_taxonomy` from classification batch supported domains and database
      constraints; remove Job adapter/readiness code and API branches.
- [x] Remove canonical state/availability from Job detail, search, recommendation, and
      product-read schemas and bulk readers.
- [x] Remove canonical structured filters/facets, stats/category buckets, and CSV export
      columns.
- [x] Remove `job.canonical_taxonomy_changed`, taxonomy embedding input, and taxonomy
      refresh dependencies.
- [x] Change Related Jobs scoring to semantic 0.80, governed Skills 0.15, freshness 0.05;
      remove taxonomy helpers, reads, and response fields.

## 5. Remove frontend Job taxonomy surfaces

- [x] Remove Canonical Job Taxonomy sections and helpers from Job detail and Related
      Jobs cards while retaining Source Classification Paths and both Skill sections.
- [x] Remove Job Browser canonical labels and canonical filter/facet request/response
      state.
- [x] Remove canonical route/query keys, hydration, selector/chip/summary code, and stale
      deep-link behavior.
- [x] Remove Dashboard Category chart and Job Taxonomy classification navigation.
- [x] Remove the Job Taxonomy domain/tab from automated classification while retaining
      Company Industry and Skill.
- [x] Remove Job-only current-taxonomy API client functions and preserve Company/Skill
      functions.

## 6. Update fixtures, docs, and specs

- [x] Update backend product fixtures first, then make frontend fixture copies exact.
- [x] Split mixed current-taxonomy fixtures/tests so Company Industry and Skill coverage
      remains explicit after deleting Job portions.
- [x] Remove Job taxonomy vocabulary from `CONTEXT.md` and update all affected active
      Trellis specs to the new contracts.
- [x] Run architecture searches and classify any remaining `canonical_taxonomy`,
      `job_taxonomy`, or `canonical_job` occurrence as intentionally historical/test
      evidence or remove it.

## 7. Focused verification

- [x] Run focused backend tests, including:
      `test_current_taxonomies.py`, `test_job_intelligence_response_contracts.py`,
      `test_job_search_facets.py`, `test_stats.py`, AI enrichment/classification tests,
      recommendation/embedding tests, `test_sandbox_cutover.py`, and bootstrap tests.
- [x] Run focused frontend tests for Job detail, Job Browser, FilterPanel, app routes,
      Dashboard, classification batches, API clients, and layer summaries.
- [x] Verify backend/frontend fixture equality.
- [x] Run targeted architecture searches for removed runtime contracts.

## 8. Full quality gate

- [x] `python3 -m pytest --collect-only -q backend/tests` (514 collected before the
      final regression additions)
- [x] `python3 -m pytest -q backend/tests` (474 passed, 43 skipped after final changes)
- [x] `cd frontend && npm test` (35 files, 214 tests)
- [x] `cd frontend && npm run lint`
- [x] `cd frontend && npm run build`
- [x] Run empty-schema bootstrap parity tests on a disposable `*_test` database.
- [x] Run the sandbox cutover integration rehearsal twice on disposable PostgreSQL and
      Redis state (`job_scraper_cutover_test` plus Redis DB 15; disposable state removed).

Additional completed checks: backend/frontend fixture equality and the targeted
removed-contract architecture search both pass.

## 9. Operational cutover and post-cutover checks

- [x] Stop persistent services and export/validate the narrowed transient artifact.
- [x] Confirm Job Taxonomy and `job_embeddings` are excluded while all required retained
      domains are present.
- [x] Clear, bootstrap, import, and exactly verify according to the sandbox contract.
- [x] Start the complete stack and enqueue regeneration of all retained Job embeddings.
- [x] Verify stale embeddings are never served and monitor regeneration completion
      (6,743 Jobs, 6,743 current 384-dimensional embeddings, zero missing).
- [x] Smoke-test source classification display/filtering, Skills/Candidates, Company
      Industry, AI enrichment, Dashboard, search, export, and Related Jobs.
- [x] Finalize the transient artifact only after all verification succeeds.

## Rollback Points

- Before shared sandbox clearing: abort deployment and keep the old complete stack.
- After clearing but before verification: keep services stopped and the transient
  artifact intact; repair the new code/cutover path and repeat import/verification.
- After artifact finalization: no application-level rollback is promised by the project
  contract; remediation is forward-only.
