# One-time cutover and retention map

## Retain

- `jobs`: Source IDs, listing/detail payloads, normalized fields, AI summary and
  enrichment fields (`backend/app/models/job.py:37-104`).
- `companies`: company identity/details/AI description
  (`backend/app/models/company.py:22-56`).
- `job_embeddings`: vector/document payloads; remove only model/version identity
  (`backend/app/models/job_embedding.py:15-38`).
- Source Job Attribute projections and complete Source Classification Path
  evidence (`backend/app/models/source_job_attributes.py:27-163`), after removing
  catalog revision references.
- Accepted Job Taxonomy, Company Industry, and Skill assignments/projections;
  governance audit and idempotency evidence needed to explain accepted state.

## Delete

- Source Catalog candidates, validations, revisions, active pointers, reviews,
  publications, rollback and provenance-repair state.
- All crawl/automation/dispatch/schedule/manual-action task history.
- AI Enrichment, Company Enrichment, embedding, recommendation, recovery,
  ingestion, and scheduler task/run history.
- `event_outbox`, Redis Streams, consumer groups, pending/claimed entries, and
  dead-letter task commands.
- Legacy Job Intelligence per-item review queues after accepted assignments and
  required evidence have been exported.
- Alembic history and application-level release/version data.

## Deletion hazards

- `crawl_jobs` references `crawl_dispatch_plans` with RESTRICT and consumed
  dispatch plans reference `crawl_jobs` with RESTRICT
  (`backend/app/models/crawl_job.py:58-72`,
  `backend/app/models/crawl_dispatch_plan.py:151-159`). The cutover must not use
  naive ORM cascade deletion.
- `schedule_executions` also references dispatch plans with RESTRICT
  (`backend/app/models/schedule.py:281-325`).
- `enrichment_run_items.run_id` cascades from `enrichment_runs`, but `job_id`
  references retained Jobs without delete cascade
  (`backend/app/models/enrichment_run.py:10-74`).
- `company_enrichment_run_items` has the analogous safe run-to-item cascade and
  retained Company reference
  (`backend/app/models/company_enrichment_run.py:10-66`).
- Deleting Jobs or Companies would cascade into embeddings and accepted
  projections. They are never cleanup roots.

## Cutover protocol

1. Stop frontend, API, scheduler, all workers, and helper processes.
2. Record before-counts and stable identity/hash manifests for retained data.
3. Export only retained business/governance data into the cutover artifact.
4. Destroy the database and Redis task/queue state; do not create a backup.
5. Create the target schema directly from one current schema definition.
6. Import and remap retained data to ordinary stable classification identities.
7. Assert count/identity/content preservation and zero task/version history.
8. Start the complete application atomically and run cross-source smoke tests.

The retained export is a one-time transformation artifact, not a reusable backup
or migration history.
