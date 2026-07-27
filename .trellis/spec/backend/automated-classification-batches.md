# Automated Classification Batch Contracts

## 1. Scope / Trigger

Use this contract when changing automated Job Taxonomy, Company Industry, or
Skill classification selection, batch lifecycle, Skill Candidate promotion,
the classification HTTP API, the Classification console, or the repeated-Skill
threshold in Settings.

Classification Processing Batches replace routine Governance queues. They use
ordinary current taxonomy state and never create releases, revisions, review
items, or fallback taxonomy nodes.

## 2. Signatures

Shared runtime and adapters:

```python
ClassificationBatchRuntime(db, adapters).preview(domain, filters, limit)
ClassificationBatchRuntime(db, adapters).start(domain, filters, limit)
ClassificationBatchRuntime(db, adapters).execute(run_id)
ClassificationBatchRuntime(db, adapters).request_stop(run_id)
ClassificationBatchRuntime(db, adapters).retry_failed(run_id)

ClassificationDomainAdapter.select_candidates(db, filters, limit)
ClassificationDomainAdapter.process_candidate(db, candidate)
```

HTTP:

```text
POST /api/job-intelligence/classification-batches/{domain}/preview
POST /api/job-intelligence/classification-batches/{domain}/runs
GET  /api/job-intelligence/classification-batches/runs?domain=...
GET  /api/job-intelligence/classification-batches/runs/{run_id}
POST /api/job-intelligence/classification-batches/runs/{run_id}/stop
POST /api/job-intelligence/classification-batches/runs/{run_id}/retry-failed
```

Request body:

```json
{"filters": {"source_sites": ["jobsdb"]}, "limit": 100}
```

Persistence uses `classification_batch_runs` and
`classification_batch_run_items`. `app_runtime_settings` owns nullable
`skill_auto_create_distinct_job_threshold`; its effective default is `5`.

## 3. Contracts

- The shared runtime owns `pending -> running -> completed |
  completed_with_failures | failed | cancelled`, aggregate counts, cooperative
  Stop, and retry snapshots. Domain adapters own only bounded selection and one
  item transaction work.
- At most one active run exists per domain. Job Taxonomy, Company Industry, and
  Skill may run independently.
- Preview and start use the same adapter selection. Limit is `1..5000` and the
  stable item snapshot is persisted before background execution begins.
- Job Taxonomy selects non-deleted unassigned Jobs and calls the existing
  taxonomy-only AI interface. A non-selection is an item failure; no fallback
  assignment is written.
- Company Industry selects non-deleted unassigned Companies and accepts only a
  current Source Industry mapping supported by preserved Job evidence. JobsDB,
  OfferToday, and CTgoodjobs follow the same Source-qualified rule. A label is
  never guessed into a Company Industry code.
- Skill selects unresolved Candidates whose current `distinct_job_count`
  reaches the effective Settings threshold. Changing Settings affects later
  selection only.
- Skill processing first reuses exact current code/name/alias matches. Known
  generic or suppressed terms are converted to generic/rejected Mention
  evidence and never become Skills.
- New Skills require an existing active Category/Technology pair. The created
  Skill, aliases, Candidate resolution, active Mention targets, and all affected
  Job Skill projections share the item's transaction. Uncertain placement is a
  retryable item failure; `Other`, `Unknown`, or other fallback nodes are never
  created.
- The frontend exposes three tabs over the same lifecycle: preview, start,
  progress, Stop, failure detail, and retry-failed. It does not expose a
  Governance or per-item review queue.

## 4. Validation & Error Matrix

| Condition | Required result |
|---|---|
| Unknown domain or limit outside `1..5000` | `400`/`422`; no run |
| Active run already exists for the domain | `409`, code `active_classification_batch_exists`, existing run ID |
| Preview selects zero items | Start remains disabled in the UI; direct start creates a terminal empty run |
| Stop pending run | Cancel every pending item immediately |
| Stop running run | Set `stopping`; finish the in-flight item and cancel untouched items |
| Retry has no failed items | `400`; no run |
| Skill Candidate falls below current threshold before execution | Item failed; no taxonomy mutation |
| Skill matches current name/code/alias | Reuse it and reproject affected Jobs |
| Skill is generic/suppressed | Generic/rejected Mention evidence; no Skill node |
| Category/Technology missing, inactive, mismatched, or uncertain | Item failed; no fallback or partial write |
| Company lacks mapped Source Industry evidence | Item failed; never infer by display label |

## 5. Good / Base / Bad Cases

- **Good:** `Py` reaches five distinct Jobs, matches the current `Py` alias for
  Python, resolves every active Mention, and rebuilds those five Job projections.
- **Good:** `DuckDB` reaches the threshold, the classifier chooses an exact
  existing Data/Data Warehouse path, and one ordinary current Skill is created.
- **Base:** a Candidate reaches the threshold but placement is uncertain. The
  item remains failed and can be retried after taxonomy or model improvements.
- **Base:** `Project Management` reaches the threshold and becomes generic
  evidence without creating a Skill.
- **Bad:** create `Other / Unknown / MysteryDB`, create a Review row, or mutate a
  taxonomy release so the batch can report success.
- **Bad:** implement three separate run tables/services with divergent Stop and
  retry states.

## 6. Tests Required

- Runtime tests assert preview/start parity, bounded stable item snapshots,
  active conflict, success/failure counts, pending/running Stop, and failed-only
  retry.
- Skill tests assert threshold default/update, threshold selection, exact alias
  reuse, generic rejection, confirmed-path creation, affected Job reprojection,
  and uncertain failure with no fallback nodes.
- Adapter tests assert unassigned/non-deleted selection and Source filters for
  Job and Company domains.
- API tests assert the shared route set and run/item serialization without
  Governance/Review routes.
- Frontend tests assert preview gates Start, domain filters normalize correctly,
  progress is accessible, failed reasons render, retry targets the displayed
  run, and Skill does not show Source filters.
- Empty-schema bootstrap must include both classification tables and the Skill
  threshold column. Frontend lint/tests/build and backend Ruff/Mypy/tests pass.

## 7. Wrong vs Correct

### Wrong

```python
if placement_is_uncertain:
    create_skill(category="Other", technology="Unknown", name=candidate.name)
```

This hides classification uncertainty and pollutes the ordinary taxonomy.

### Correct

```python
if decision.status != "create":
    raise ValueError("Skill candidate placement is uncertain")
```

The runtime records the item failure and `retry_failed` can try it again later.
No taxonomy, Candidate, Mention, or Job projection mutation survives the failed
item transaction.
