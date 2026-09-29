# Design: Remove Jev and unify Job AI Enrichment

## 1. Boundary

The system has one Job-level AI workflow: ordinary AI Enrichment. One provider
request produces the current Job insight snapshot, including summary,
experience, governed Skill dispositions, and Related Jobs ranking. There is no
second correction system, manual operation console, candidate-classification
batch, feature-specific provider profile, or separate Job processing state.

Retained modules:

- `EnrichmentRunService` remains the authority for candidate selection, run
  lifecycle, Stop, Retry failed, monitoring, and history.
- `AIEnrichmentService.enrich_job()` remains the per-Job transaction boundary.
- `JobInsightExtractor` remains the single ordinary Job provider call.
- `CurrentSkillEnrichment` remains the validator and writer for current Skill
  mentions and governed assignments.
- `JobRecommendationService` remains the deterministic, bounded Related Jobs
  candidate generator.
- `recommendation-api` remains the read-side owner for Related Jobs and the
  public backend continues to proxy to it.

Removed modules include all Jev APIs/models/services/tests/product surfaces and
the complete Skill-only Classification/review batch product. Unresolved Skill
evidence remains internal current-taxonomy data, not an actionable queue.

## 2. Unified request and validation

Before the one provider call, the enrichment service freezes at most ten
candidate records from `JobRecommendationService.recommend_for_job(job.id,
limit=10)`. A missing source embedding produces an empty candidate set and is
not an error. The extractor receives the existing Job evidence, active governed
Skill taxonomy choices, and the frozen Related Jobs candidate evidence.

The response contract has four required sections:

```text
summary
experience
skills[]
related_jobs[]
```

Each Skill result contains a normalized term, evidence/reason, and exactly one
provider-neutral disposition:

```text
match_existing | unresolved | generic | rejected
```

`match_existing` requires an active assignable Skill code from the supplied
taxonomy. `unresolved` writes non-searchable evidence through the existing
candidate-backed mention representation; it does not authorize taxonomy node
creation. `generic` and `rejected` remain evidence dispositions and never
become governed assignments. The retained projection service drops the legacy
`jev_route` vocabulary and accepts a provider-neutral disposition field.

Each Related Jobs result contains one supplied candidate UUID and a bounded
concise reason. Validation rejects duplicate IDs, IDs outside the frozen set,
more than five results, and malformed reasons. The provider cannot invent a
Job. An empty frozen candidate set requires an empty related result and remains
a valid enrichment success.

The existing LLM clients parse JSON objects but do not enforce provider-side
JSON Schema. Therefore strict domain validation happens in the extractor or a
dedicated response validator before any ORM object is mutated. Required-section
shape errors raise the existing response-format failure class so the ordinary
run item becomes failed and is recoverable through `Retry failed jobs`.

## 3. Atomic write model

`AIEnrichmentService.enrich_job()` performs candidate generation and the single
provider request, validates the complete response, then writes all outputs in
its existing database session. Its one final `db.commit()` remains the commit
point. Any upstream, validation, projection, or persistence exception triggers
the existing `db.rollback()` and leaves the preceding successful non-Jev
snapshot intact.

The current Related Jobs snapshot uses normalized current-state persistence,
not an evaluation history table:

```text
job_related_jobs_snapshots
  source_job_id PK/FK -> jobs.id ON DELETE CASCADE
  source_evidence_hash
  model_provenance JSON
  completed_at
  updated_at

job_related_jobs_snapshot_items
  source_job_id FK -> job_related_jobs_snapshots.source_job_id ON DELETE CASCADE
  target_job_id FK -> jobs.id ON DELETE CASCADE
  position
  reason
  PK(source_job_id, target_job_id)
  UNIQUE(source_job_id, position)
```

A parent row with no items records a successful empty AI selection. Items store
only stable identities, order, and AI reason; Job title/company/location and
other display data are read live so a frozen ranking does not freeze stale Job
display facts. Model provenance is operational traceability, not exposed on Job
Detail. Snapshot replacement deletes/replaces its children in the same Job
enrichment transaction.

## 4. Related Jobs read contract

The recommendation read service first loads the current snapshot and its live,
non-deleted target Jobs. A snapshot is usable only when at least one target is
still available. A usable snapshot returns at most five targets in persisted
order, with `result_source="ai_ranked"` and an optional `reason` on each item.

When no snapshot exists, the snapshot is empty, or every selected target has
become unavailable, the service calls the deterministic recommendation service
and returns `result_source="similarity"` with no AI reasons. No read path sends
an AI request. No candidate produces an empty list.

The provider-neutral response removes evaluation IDs, scores/reasons prefixed
with Jev, and evaluation status. Deterministic semantic/skill/freshness metrics
may remain as algorithm diagnostics where currently required; AI-ranked items
need not expose provider/model/request/cost data.

Job Detail renders only:

- `AI-ranked from the latest enrichment` for `ai_ranked`;
- `Suggested by job similarity` for `similarity`;
- `No related jobs available` for an empty list.

## 5. Skill evidence after Classification removal

`CurrentJobSkillMention` and `CurrentSkillCandidate` remain implementation data
for unresolved evidence aggregation and later replacement by a new enrichment.
They no longer represent a review queue. Candidate list/decision APIs,
Classification navigation/page, batch runtime/history, review Settings,
Dashboard backlog actions, startup candidate reconciliation, and taxonomy
maintenance scheduling are removed.

Job Detail no longer exposes an actionable Skill Candidate Evidence panel or a
compatibility candidate-review payload. The domain glossary uses `Unresolved
Skill Evidence` for unknown terms. Existing operator-authored decisions remain
protected by the projection boundary, but this task adds no interface for new
manual decisions and never creates new Skill taxonomy nodes.

## 6. Removal matrix

| Surface | Disposition |
|---|---|
| Jev Operations route/page/navigation | Delete |
| Jev Settings, connection test, provider limits | Delete |
| Jev general runs/batches/attempts | Delete |
| Online Skill correction/backfill/maintenance | Replace with unified ordinary enrichment, then delete |
| Possible same vacancy / duplicate association | Delete without replacement |
| Search relevance reranking | Delete without replacement |
| Crawl incident triage and content-quality advisory | Delete without replacement |
| Jev-ranked Related Jobs | Replace with ordinary enrichment snapshot |
| Classification/Skills-review page and batch runtime | Delete |
| Unresolved Skill evidence tables | Retain as internal data |
| Archived tasks, journals, Git history | Preserve as history |
| Issue #83 / old active repair task | Closed and archived as superseded |

The live manifest found 81 Jev-exclusive tracked files suitable for deletion
and 42 retained files with Jev integration seams. Implementation must rerun the
manifest search rather than rely on this count alone. The two generated
`frontend/dist` assets and local caches are not tracked source.

## 7. One-time database cutover

The authoritative database cutover is destructive and happens while backend,
enrichment, scheduler, recommendation, and related workers are stopped. A
normal full database backup is a hard precondition.

During implementation only, a temporary tool provides:

1. `preflight`: read-only counts and preservation classification;
2. `apply --confirm-remove-jev`: reruns preflight, performs cleanup/drop, and
   writes a secret-safe report;
3. a repeated `apply` proof that reports already removed and touches no
   unrelated data;
4. post-cutover schema/projection verification.

The temporary tool is deleted before the final work commit. It is never
imported by bootstrap, startup, an API, or a worker.

### Skill cleanup order

Before history tables are dropped:

1. Read Jev maintenance `applied_changes` and explicit approval state.
2. Read terminal completed Classification Batch items and resolve their
   `subject_id` values to Skill Candidates.
3. Classify current decisions as proven automatic, proven operator-approved,
   or ambiguous. Ambiguous data is preserved.
4. Remove all mentions and assignments whose source directly proves Jev
   classification.
5. Reverse proven automatic maintenance/batch candidate resolutions, restore
   their mentions to unresolved evidence where the original candidate link is
   available, clear automatic candidate resolution, and recompute metrics and
   current Job assignments.
6. Remove an alias only when persistence evidence proves that exact alias was
   created by an automatic action. The current alias schema has no provenance;
   aliases lacking such proof are ambiguous and remain.
7. Preserve explicitly approved proposed Skills, existing ordinary
   operator-authored decisions, and all ambiguous records.
8. Do not change `jobs.ai_enriched_at`, create enrichment runs, or requeue Jobs.

Then drop all fifteen `jev_*` tables plus
`classification_batch_run_items` and `classification_batch_runs`. Fresh
bootstrap must no longer create or expect them.

The secret-safe verification report records only counts, table names,
preservation categories, backup acknowledgement, and pass/fail invariants. It
contains no API keys, prompts, provider receipts, Job descriptions, or exported
Jev data.

## 8. Deployment and rollback

Deployment is one coordinated compatibility break:

1. Build and test the new images/code while the old runtime remains stopped.
2. Stop every process that can write Job enrichment, Skill, recommendation,
   scheduler, or Jev state; verify the stopped legacy batch has no running work.
3. Create/verify the normal database backup.
4. Run the temporary preflight and review its report.
5. Run the explicitly confirmed apply and post-cutover verification.
6. Delete the temporary tool/tests, complete the live zero-reference scan, and
   create final images from the committed source.
7. Start the new backend, enrichment worker, recommendation API, scheduler, and
   frontend; run API/UI smoke checks.

Before apply, rollback is ordinary code rollback. After tables/projections are
removed, rollback requires restoring the full database backup and the old
application images/commit together. Reintroducing only old code against the
cut-over schema is unsupported. No Jev-specific export exists.

## 9. Verification invariants

- Exactly one provider call occurs per successfully attempted Job.
- Strict invalid response tests observe zero committed partial output.
- Operator-authored Skill decisions survive unified enrichment and cutover.
- No future pending/retry flow imports or calls a Jev service.
- Recommendation reads never invoke a provider and use deterministic fallback
  when a current AI snapshot is not usable.
- Fresh schema contains the new Related Jobs snapshot tables and contains none
  of the seventeen retired Jev/Classification batch tables.
- Existing authoritative schema contains none of those retired tables after
  cutover; repeated apply evidence shows no additional mutation.
- Route inventories/OpenAPI contain no retired endpoints or payload fields.
- A tracked-source scan, with only archived/history/removal-task evidence
  excluded, finds no case-insensitive Jev reference.
