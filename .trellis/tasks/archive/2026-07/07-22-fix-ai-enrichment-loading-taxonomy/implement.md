# Implementation plan: AI Enrichment bootstrap and provenance recovery

## Ordered checklist

1. **Create red regression coverage for the current failure modes.**
   - Add backend tests proving monitor and overview projections omit unused
     `job_ids`, while detail/status serialization remains compatible.
   - Add Source Job Attribute tests for revision overlay: missing revision is
     filled only with a matching source/fingerprint, mismatches fail closed,
     and exact replay is idempotent.
   - Add repair-service tests for complete coverage, unknown node IDs, mixed
     repairable/unrepairable jobs, active-revision drift, bounded batches, and
     no-write inspection.
   - Add versioned ingest/detail tests that prove the Dispatch Plan revision
     reaches persisted Source Classification Paths.
   - Add/extend `AIEnrichmentPage.test.jsx` coverage for bootstrap timeout and
     partial/degraded responses without fabricated counters.

2. **Implement the typed revision handoff.**
   - Extend the relevant Source Job Attribute evidence/parser seam with an
     optional `SourceCatalogRevisionRef`.
   - Add the shared revision overlay/validation helper at the
     `SourceJobAttributes` boundary.
   - Thread the immutable revision from `ExecutionAuthorityV1` through
     `ListingRuntimePlan`/`DetailRuntimePlan` and direct OfferToday persistence.
   - Thread the revision through Redis ingest using `crawl_job_id`; leave
     legacy no-plan events provenance-limited instead of guessing.

3. **Implement the historical coverage report and repair.**
   - Add the repair service and typed report model.
   - Parse the selected published revision's normalized payload into a stable
     source-qualified identity set.
   - Add the Source Job Attribute repair method with locking, version/hash
     updates, one outbox event per changed job, and idempotent behavior.
   - Add `backend/scripts/repair_source_catalog_provenance.py` with report-only
     default, explicit revision pinning, bounded apply batches, and a required
     confirmation flag.

4. **Reduce AI bootstrap payloads without changing product semantics.**
   - Add compact serializer options in `backend/app/api/ai.py`.
   - Use compact projections for `/ai/overview` and monitor list responses.
   - Preserve full payloads for run detail/status and existing API consumers.
   - Keep the frontend's independent overview/runs loading and degraded error
     behavior; only adjust copy or tests if the current error is misleading.

5. **Run a read-only local recovery preview.**
   - Run the new report against the active OfferToday revision and the current
     pending cohort.
   - Confirm the report accounts for all 9,458 pending OfferToday jobs and
     lists any uncovered identities before considering `--apply`.
   - Do not execute the bulk repair in this implementation pass without a
     separate explicit operator instruction after the report is reviewed.

6. **Quality gate.**
   - Run focused backend tests for Source Job Attributes, ingest, AI runs, and
     repair coverage.
   - Run `frontend` AI Enrichment tests and the frontend production build.
   - Run repository lint/type checks documented by the package scripts.
   - Inspect the final diff for unrelated changes and confirm no debug output,
     temporary data files, or accidental live writes remain.

## Planned file boundaries

- `backend/app/job_intelligence/source_attributes/contracts.py`
- `backend/app/job_intelligence/source_attributes/module.py`
- `backend/app/job_intelligence/source_attributes/rebuild.py` or a focused
  provenance-repair module beside it
- `backend/app/crawl_control/listing_runtime.py`
- `backend/app/crawl_control/detail_runtime.py`
- `backend/app/services/offertoday_detail_pipeline.py`
- `backend/app/workers/run_ingest_worker.py`
- `backend/app/api/ai.py`
- `backend/scripts/repair_source_catalog_provenance.py`
- `backend/tests/test_source_job_attributes.py`
- `backend/tests/test_source_job_attribute_ingest.py`
- `backend/tests/test_source_job_attribute_adapters.py`
- `backend/tests/test_ai_enrichment_runs.py`
- `frontend/src/components/ai/AIEnrichmentPage.test.jsx`

## Review gates and rollback points

- Stop after revision-overlay tests pass and review the authority flow before
  adding any repair write.
- Stop after the repair report is implemented and inspect its local output;
  coverage failures must remain visible rather than being auto-repaired.
- Stop after compact API projections pass contract tests and verify detail
  endpoints still expose their legacy fields.
- Only after the user reviews the read-only report should a separate command
  be considered for applying the pinned OfferToday repair.
