# Implementation plan

## Ordered work

1. Add red tests for the source-policy contract.
   - Verify every root in `category_catalog_v1.json` has exactly one explicit
     mapped or excluded handling rule.
   - Verify mapped default paths, allowed domains/categories/subcategories, and
     subclassification hints resolve against the internal taxonomy.
   - Verify an unknown source ID and an explicitly excluded source ID produce a
     typed unsupported preflight result rather than reaching the LLM seam.

2. Complete and validate OfferToday source policy data.
   - Add defensible mappings for source roots with existing internal domains.
   - Add explicit exclusion reasons for roots without a defensible destination.
   - Preserve all existing non-OfferToday mapping entries byte-for-byte where
     behavior is unchanged.

3. Add run-level exclusion persistence.
   - Create an Alembic migration for `enrichment_runs.excluded_items` with a
     zero default.
   - Extend `EnrichmentRun` and count/status helpers with the excluded bucket.
   - Ensure old runs continue to serialize with `excluded_items = 0`.

4. Implement candidate preflight in `EnrichmentRunService`.
   - Reuse the registry policy rather than duplicating source-ID logic in the
     API or frontend.
   - Mark unsupported selected items as `excluded` with a stable reason.
   - Queue only pending/supported items.
   - Keep `total_items`, progress, terminal status, stop handling, and retry
     semantics truthful for the new bucket.
   - Avoid publishing an execution event when no supported item remains.

5. Extend API projections and endpoint tests.
   - Add exclusion fields to preview, create-run, run-list, run-detail, and item
     responses.
   - Return grouped source ID/name/count/reason details for preview and run
     creation.
   - Cover mixed supported/excluded, all-excluded, and provider-failure-plus-
     exclusion cases.

6. Update the AI enrichment console.
   - Add excluded metrics and terminal summary copy.
   - Use settled buckets for progress and keep excluded out of failed/retry
     actions.
   - Show enough grouped detail for an operator to understand which categories
     were not attempted.
   - Add frontend tests for preview, active/terminal cards, and all-excluded
     response handling.

7. Run the quality gate.
   - Backend focused tests for registry, enrichment runs, and API serialization.
   - Frontend focused tests for `AIEnrichmentPage`.
   - Backend lint/type checks and the relevant full test commands from the repo.
   - Inspect migration SQL and confirm no unrelated dirty files were changed.

## Planned files / boundaries

- `backend/app/data/job_source_taxonomy_mapping.json` and any explicit policy
  data file introduced for exclusions.
- `backend/app/services/job_taxonomy_registry.py`.
- `backend/app/services/job_category_normalizer.py` only if needed to consume
  the typed preflight result.
- `backend/app/services/enrichment_run_service.py`.
- `backend/app/models/enrichment_run.py`.
- `backend/app/api/ai.py`.
- `backend/alembic/versions/<new_revision>_add_enrichment_exclusions.py`.
- `backend/tests/test_ai_enrichment_runs.py` plus focused registry/API tests.
- `frontend/src/components/ai/AIEnrichmentPage.jsx` and its test/style files.

## Review gates and rollback points

- Stop after policy tests and review the mapping/exclusion matrix before
  touching run persistence.
- Stop after backend/API work and verify a dry-run preview reports exclusions
  without publishing a worker event.
- Stop after frontend work and verify excluded items never appear as failed or
  retryable.
- Do not run `task.py start` or implement code until the user reviews this plan.
