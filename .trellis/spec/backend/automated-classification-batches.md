# Automated Classification Batch Contracts

## Scenario: Classify Company Industry and repeated Skill Candidates

### 1. Scope / Trigger

Use this contract for the shared preview/run/stop/retry lifecycle, Company
Industry mapping batches, repeated-Skill Candidate promotion, Classification UI,
or the Skill threshold in Settings. Supported domains are exactly
`company_industry` and `skill`.

### 2. Signatures

```python
ClassificationBatchRuntime(db, adapters).preview(domain, filters, limit)
ClassificationBatchRuntime(db, adapters).start(domain, filters, limit)
ClassificationBatchRuntime(db, adapters).execute(run_id)
ClassificationBatchRuntime(db, adapters).request_stop(run_id)
ClassificationBatchRuntime(db, adapters).retry_failed(run_id)
```

```text
POST /api/job-intelligence/classification-batches/{domain}/preview
POST /api/job-intelligence/classification-batches/{domain}/runs
GET  /api/job-intelligence/classification-batches/runs?domain=...
GET  /api/job-intelligence/classification-batches/runs/{run_id}
POST /api/job-intelligence/classification-batches/runs/{run_id}/stop
POST /api/job-intelligence/classification-batches/runs/{run_id}/retry-failed
#classification?target=<skill|company_industry>
```

Persistence uses `classification_batch_runs` and
`classification_batch_run_items`. `app_runtime_settings` owns nullable
`skill_auto_create_distinct_job_threshold`; effective default is `5`.

### 3. Contracts

- The runtime owns `pending -> running -> completed |
  completed_with_failures | failed | cancelled`, counts, Stop, and retry.
- At most one active run exists per retained domain; domains run independently.
- Preview and Start use the same bounded selector; limit is `1..5000`.
- Company Industry applies Source filters, selects a bounded Company population,
  then reports `mapped_item_count`, `unmapped_item_count`, and
  `excluded_item_count`. Start requires at least one mapped item.
- Skill selects unresolved Candidates whose `distinct_job_count` reaches the
  effective threshold. Existing Skill names/codes/aliases are reused.
- Promotion creates no `Other`/`Unknown` fallback. Skill node, aliases,
  Candidate resolution, Mentions, and affected projections share one item
  transaction.
- Failed-only Retry rechecks current eligibility and excludes Candidates that
  already reached a terminal disposition.
- The frontend has two tabs, defaults invalid/bare routes to `skill`, and keeps
  Company Industry and Skill route targets durable.
- Preview authority is the immutable accepted `{result, inputs}` pair. Any
  domain, Source-filter, or limit change clears it and aborts the request.

### 4. Validation & Error Matrix

| Condition | Required result |
|---|---|
| Unknown domain or limit outside `1..5000` | `400`/`422`; no run |
| Active run exists for domain | `409 active_classification_batch_exists` |
| Invalid/bare frontend target | Select `skill`; perform no mutation |
| Company selected population has zero mapped items | Show counts; disable/reject Start |
| Company mapping is missing | Isolated item failure; never infer |
| Company label is explicit non-mapping | Count excluded; no item/retry |
| Candidate is below threshold at execution | Item failure; no taxonomy mutation |
| Candidate placement is uncertain | Retryable failure with visible reason |
| Inputs change after Preview | Abort, clear Preview, disable Start |
| Superseded response arrives | Ignore success and failure |

### 5. Good / Base / Bad Cases

- **Good:** repeated `DuckDB` evidence is placed under an existing active
  Category/Technology pair and affected Jobs gain a governed Skill.
- **Good:** a Company batch processes mapped rows while preserving unsupported
  rows as isolated failures.
- **Base:** `#classification` loads Skill history without Preview or Start.
- **Bad:** accept a removed Job-classification domain or fallback route.
- **Bad:** hide Candidate failure reasons or create fallback Skill nodes.

### 6. Tests Required

- Runtime tests cover both domains, active-run conflict, Stop, partial failure,
  retry, transaction isolation, and settings threshold.
- Company tests cover mapping counts, Source filters, non-mapping exclusions,
  drift, and zero-mapped rejection.
- Skill tests cover aggregation, aliases, terminal dispositions, uncertain
  placement, atomic promotion, and reprojected Jobs.
- Frontend tests cover two tabs, Skill default, Company route durability,
  immutable Preview authority, request abort, visible failure evidence, and
  no Source filters for Skill.

### 7. Wrong vs Correct

#### Wrong

```js
startClassificationBatch(domain, buildPayloadFromCurrentControls())
```

#### Correct

```js
startClassificationBatch(preview.inputs.domain, preview.inputs.payload)
```

Only the visible accepted Preview snapshot authorizes Start.
