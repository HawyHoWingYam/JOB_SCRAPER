# OfferToday Production Crawl Contracts

## Scenario: Practical IT listing and incremental detail targeting

### 1. Scope / Trigger

Use this contract when changing the production OfferToday standalone crawl,
listing conditions, cursor policy, page-cap behavior, staging classification,
detail target loading, or crawl metrics.

The production objective is practical IT coverage from the checked-in category,
keyword, and hybrid search space. It does not require a full-site denominator,
research artifact, repeated census, canary, or soak.

Research-only artifact/candidate/stability code is not a production dependency.
Preserve its source, tests, schemas, strict verifier, specifications, and local
runtime artifacts for historical replay, but do not add new production imports
or research phases. Research replay may continue to use shared cursor,
response, identity, staging, and detail primitives.

### 2. Signatures

```text
python backend/scripts/offertoday_standalone_crawl.py \
  --crawl-job-id <uuid> \
  --crawl-phase <full|listing|detail> \
  --max-pages <positive-int> \
  [--category-ids <csv>] [--keywords <csv>] \
  [--headed] [--auth-state <path>]
```

```python
build_offertoday_listing_conditions(
    category_ids,
    *,
    keywords=None,
    default_to_it=True,
    endpoint="search",
    rcd_type=None,
) -> list[OfferTodayListingCondition]

OfferTodayListingRunner.run(
    *,
    conditions,
    stop_policy,
    retry_policy,
    observation_sink,
    staging_sink,
    session_mode,
    request_policy,
    terminal_policy="result-transition-confirmation-v1",
) -> ListingRunResult

CrawlJobRuntime.stage_listing_batch(
    *,
    crawl_job_id,
    source_site="offertoday",
    payloads,
    skip_existing,
) -> ListingBatchPersistResult

CrawlJobRuntime.load_detail_targets(
    *,
    source_site="offertoday",
    request_payload,
    detail_crawl_job_id,
) -> DetailTargetLoadResult
```

The implementation may refine type names while preserving the contracts below.

### 3. Contracts

#### Production listing policy

- Every default IT category, keyword, hybrid, and explicit-keyword condition
  uses `/wapi/geek/recommend/search/list`.
- Omit `rcdType` and request `pageSize=10`.
- Page 1 has no cursor. Page 2+ carries the exact prior response's
  `sessionId`, `supplePage`, `suppleAmount`, and `suppleType`.
- Cursor state belongs to one condition/browser chain and resets before the
  next condition.
- Two successful cursor-continuous pages with empty `resultList` produce
  natural result exhaustion.
- `suppleRcdList` is observed and deduplicated separately but never staged or
  detailed. Invalid/conflicting supplemental identity evidence is counted and
  excluded, not treated as a result-crawl hard stop.
- `max_pages` is a per-condition safety cap, default 100. No unique-ID cap is
  used for the default IT crawl.

#### Partial and hard-stop policy

`ListingStopPolicy.page_cap_behavior` has exact values:

- `reject`: capped condition stops and rejects the run; and
- `retain-and-continue`: production keeps validated rows, records the condition
  partial, resets the cursor, and continues.

Only `page_cap` may continue. Auth/WAF/IP, endpoint/cursor/page/session,
result-cohort identity, unresolved gap, and staging persistence failures stop
the run. A hard stop prevents detail loading.

A run whose conditions are all natural or page-cap partial finishes
`completed`; any cap sets `listing_partial=true`.

#### Batch classification and writes

Validate response, cursor, endpoint, and identity before database access or
staging.

Each canonical result page uses one bulk published-Job lookup and bulk staging
blocker/current-crawl lookups. Per-ID existence queries are forbidden.

Apply classification precedence:

1. identity conflict -> hard stop;
2. historical OfferToday code `2520` terminal -> skip;
3. published Job passing `is_complete_offertoday_job()` -> skip;
4. published incomplete/failed Job -> one current-crawl pending `repair` row;
5. absent Job -> one current-crawl pending `new` row.

Persist `detail_target_kind` (`new` or `repair`) in staging JSON. The current
schema is sufficient unless an amended spec proves otherwise. Do not skip all
historical staged or published IDs indiscriminately.

Commit one validated page batch atomically. Duplicates across pages/conditions
do not create another current-crawl row or target.

#### Detail boundary and metrics

Load detail targets only after every listing condition is natural or allowed
partial. New and repair IDs produce one target each; complete, terminal,
supplemental-only, duplicate, and conflict IDs produce none.

Production metrics include at least:

```text
listing_partial
listing_condition_count
listing_natural_condition_count
listing_capped_condition_count
listing_capped_condition_ids
distinct_it_result_ids
supplemental_rows_observed
distinct_supplemental_ids
supplemental_result_overlap_count
supplemental_identity_issue_count
complete_existing_skipped
terminal_unavailable_skipped
new_detail_targets
repair_detail_targets
detail_success
detail_failure
```

Event order is listing events -> `listing_completed` -> detail cohort -> detail
events -> `crawl.completed`. A hard stop has no later detail-cohort event.

#### Historical replay serialization compatibility

`listing_observation_to_payload()` remains the frozen historical
artifact/replay serializer. Additive production fields must not silently
invalidate historical schemas:

- omit `supplemental_identity_issues` and
  `supplemental_identity_conflicts` from the historical serializer;
- omit `ListingConditionOutcome.is_partial` when it is `false`;
- add non-empty supplemental evidence only in the production crawl event sink;
  and
- leave historical schema key sets and strict verifiers unchanged.

Do not weaken the required historical key set, cursor evidence validation, or
artifact hashes to gain compatibility. Saved-response production fixtures must
carry a coherent page-size-10 response cursor chain; a legacy envelope fixture
is not evidence that the production cursor contract should be relaxed.

### 4. Validation & Error Matrix

| Condition | Required result |
|---|---|
| Page 2 lacks or changes a required cursor field | Hard stop; no current page staging or detail |
| Response page size changes inside one chain | Hard stop as cursor/page contract violation |
| Two cursor-continuous empty `resultList` pages | Natural condition completion |
| Supplemental rows remain while `resultList` is empty twice | Natural result completion; supplemental metrics only |
| Production page cap | Retain validated rows, continue next condition, set partial |
| Auth/WAF/IP | Manual action; no detail |
| Result or historical identity conflict | Identity audit/manual action; no detail |
| Supplemental identity conflict | Count and exclude from supplemental sets; continue |
| Retry exhaustion/unresolved gap | Failed; no detail |
| Complete existing Job | Count and skip; zero detail request |
| Historical code-2520 terminal | Count and skip; zero detail request |
| Incomplete existing Job | One repair staging row and one detail target |
| New canonical ID | One new staging row and one detail target |
| Bulk lookup or staging write fails | Roll back the page batch and fail the run |
| Any per-ID existence query appears | Test failure; implementation is invalid |
| Historical observation serialization receives supplemental evidence | Omit production-only fields and preserve the exact historical schema |
| Production page observation has non-empty supplemental evidence | Add it to the production crawl event payload only |
| Saved-response production fixture omits cursor fields | Production hard stop; fix the fixture, not the parser |

### 5. Good / Base / Bad Cases

- **Good:** One category naturally exhausts and one keyword hits page 100. Both
  validated result prefixes are retained, the next condition starts with no
  cursor, listing completes partial, and one deduplicated new/repair cohort is
  fetched.
- **Base:** Every condition naturally exhausts and all IDs are already complete
  or terminal. The crawl completes with zero detail requests and exact skipped
  metrics.
- **Bad:** Production enables the response cursor but keeps buffered
  condition-only staging. A page cap then rolls back the entire validated
  prefix, defeating retain-and-continue.
- **Bad:** Staging skips every published Job before calling
  `is_complete_offertoday_job()`. An incomplete old Job disappears from the
  repair queue.

### 6. Tests Required

- `test_offertoday_search_space.py`: all production families use search,
  omitted `rcdType`, and deterministic order.
- `test_offertoday_listing_contract.py`: page-size/cursor exact validation and
  no cross-condition cursor.
- `test_offertoday_listing_runner.py`: two result-empty confirmations,
  supplemental exclusion/non-blocking identity issues, page-cap
  retain/continue, immediate validated staging, and every hard stop.
- `test_crawl_job_runtime.py`: one bulk Job lookup per page, no N+1, exact
  complete/terminal/new/repair/conflict partition, atomic rollback, and one
  current-crawl row/target per ID.
- `test_offertoday_standalone_crawl.py`: detail begins after all natural/partial
  conditions, page-cap run completes partial, hard stops have no detail, and
  exact metrics/event order.
- Existing browser, identity, completeness, detail-pipeline, transaction, and
  manual-action regression suites remain green.
- Historical research source/tests/schemas/strict replay and ignored runtime
  artifacts remain present, while the production standalone path imports no
  research-only module.
- Research observation and strict pagination replay tests retain the exact
  historical payload schema; production sink tests cover non-empty supplemental
  evidence separately.
- Run focused production tests, Ruff on touched Python, `py_compile`, complete
  backend tests, and `git diff --check`.

### 7. Wrong vs Correct

#### Wrong

```python
result = await runner.run(conditions=conditions, stop_policy=stop_policy)
for job_id in result.accepted_job_ids:
    if repository.get_job_by_source_key(db, "offertoday", job_id):
        continue
    stage(job_id)
```

This omits the production cursor policy, creates N+1 reads, skips incomplete
published Jobs, and cannot distinguish terminal or repair targets.

#### Correct

```python
result = await runner.run(
    conditions=conditions,
    stop_policy=ListingStopPolicy(
        max_pages_per_condition=100,
        unique_job_cap=None,
        page_cap_behavior="retain-and-continue",
    ),
    request_policy=production_cursor_policy(page_size=10),
    terminal_policy="result-transition-confirmation-v1",
    observation_sink=observation_sink,
    staging_sink=production_staging_sink,
    session_mode=session_mode,
)

# The sink classifies each already-validated page with bulk reads and stages
# only current-crawl new/repair rows in one transaction.
if result.hard_stopped:
    stop_without_detail(result)
else:
    targets = load_current_crawl_new_and_repair_targets()
```

The listing policy, continuation boundary, bulk classification, and detail gate
are explicit and independently testable.
