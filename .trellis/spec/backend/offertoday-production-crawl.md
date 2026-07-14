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

## Scenario: IP-block manual action and same-task recovery

### 1. Scope / Trigger

Use this contract when OfferToday listing/job-ID collection or detail fetching
classifies a response as `auth_expired`, `waf_challenge`, or `ip_blocked`, when
an older persisted manual-action event must be reopened, or when the host
verification browser is reused from a Dockerized crawl worker.

`ip_blocked` is an operator-recoverable session stop, not a parser failure or a
page-cap condition. The operator must change the public IP or network and
confirm OfferToday is reachable before resuming. Already committed listing rows,
detail results, target statuses, and metrics remain durable.

Identity classifications (`identity_issue`, `identity_conflict`, and
`id_mismatch`) are a different boundary: they require evidence review and must
not expose browser-resume actions.

### 2. Signatures

```python
normalize_manual_action_payload(
    payload,
    *,
    source_site,
    request_payload=None,
    default_browser_channel=None,
    default_browser_profile_path=None,
) -> dict[str, Any]

CrawlJobDispatchService.resume_crawl_job(
    db,
    *,
    crawl_job_id,
    requested_by=None,
    strategy: Literal["fresh_profile", "reuse_open_browser"] | None = None,
) -> CrawlJob
```

```http
POST /api/v1/crawl-jobs/{crawl_job_id}/resume
Content-Type: application/json

{"strategy": "reuse_open_browser"}
```

The host-only helper accepts `{"crawl_job_id": "<uuid>"}` at:

```text
POST /manual-actions/open-browser
POST /manual-actions/reuse-status
POST /manual-actions/close-profile-windows
POST /manual-actions/capture-screenshot
```

The container-side attach address is configured separately:

```text
MANUAL_ACTION_CDP_HOST=host.docker.internal
```

### 3. Contracts

#### Resumable OfferToday payload

Every new listing or detail session stop must persist one normalized
`manual_action` object with these fields:

```text
action_type = "session_recovery"
source_site = "offertoday"
stage = "listing" | "detail" | "browser_session"
classification = "auth_expired" | "waf_challenge" | "ip_blocked"
code = 1002 | -1000035 | null
blocked_url
crawl_mode
message
instructions[]
evidence{}
resume_context{}
browser_channel
browser_profile_path
resume_supported = true
reuse_open_browser_supported = true
preferred_resume_strategy = "reuse_open_browser"
```

For `ip_blocked`, `code` is exact integer `-1000035`; the message and
instructions explicitly say to change the public IP/network, confirm access,
and resume the same crawl. Listing evidence records the hard-stop observation.
Detail evidence includes the blocked `source_job_id`, listing IDs,
`detail_index`, and `detail_total`.

`resume_context` must contain enough data to redispatch the same phase. Listing
context includes the search categories/keywords and page budget. Detail context
includes `source_listing_crawl_job_id`, detail statuses, and detail limit. A
detail resume selects `manual_action_required` and `pending` targets; completed
targets are not reset or fetched again.

#### Legacy event normalization

Snapshot projection, resume dispatch, and the host helper must all call
`normalize_manual_action_payload()` before inspecting capabilities. For older
events, normalization may recover classification from `resume_context`, infer
the OfferToday blocked URL, code, message, instructions, resume flags, browser
launch fields, and preferred strategy. Do not rewrite historical events merely
to make them actionable.

An explicit persisted `false` capability is authoritative. Normalization must
never turn an identity audit into a resumable session action.

#### Browser profile and CDP topology

The normalized `browser_profile_path` is the identity shared by all three
boundaries:

1. the host helper launches or reuses Edge with that profile and records its
   debug port in the live-browser registry;
2. resume dispatch copies the same channel/profile into
   `manual_action_browser_channel` and
   `manual_action_browser_profile_path`; and
3. `OfferTodayBrowserRuntime` looks up that same registered profile and attaches
   to its debug port.

The current shared host-helper defaults retain the legacy environment names
`JOBSDB_HEADED_BROWSER_CHANNEL` and
`JOBSDB_HEADED_BROWSER_USER_DATA_DIR`. Once normalized into the event payload,
consumers use the payload values; they must not independently substitute the
OfferToday fresh-profile directory.

`MANUAL_ACTION_CDP_HOST` changes only the network address used by the
container-side CDP connection. Resolve the configured hostname to an IP before
`connect_over_cdp`; Edge may reject the raw Docker hostname. Emit
`manual_action_attach_attempt`, `manual_action_attach_success`, or
`manual_action_attach_failure` with source, host, resolved host, port, and
strategy.

#### Identity-audit boundary

Identity stops use `action_type="identity_audit"`, preserve their exact
classification and evidence, and set both resume flags to `false`. The task
snapshot may show the issue, but the UI hides Open Browser and Resume. The
dispatcher rejects any direct resume attempt.

### 4. Validation & Error Matrix

| Condition | Required result |
|---|---|
| Listing response is `ip_blocked` | Persist complete session-recovery payload, stop listing, and do not load details |
| Detail response is `ip_blocked` | Persist metrics and complete session-recovery payload, stop before later targets, and do not mark the crawl completed |
| Legacy event lacks resume/browser fields but proves a resumable classification | Normalize at read time and expose the recovered browser/resume contract |
| Legacy or new event explicitly sets `resume_supported=false` | Keep non-resumable; direct resume returns a conflict |
| Identity classification is observed | Persist identity evidence with both resume flags false; expose no browser actions |
| `reuse_open_browser` requested while reuse is unsupported | Reject before dispatch; do not change the task to running |
| Host helper is unreachable | Keep the task at `manual_action_required`; report helper unavailability and start/retry the helper |
| Live-browser registry has no reachable session for the payload profile | Report reuse unavailable; reopen the browser for the same profile |
| Docker worker attaches to a host browser | Use resolved `MANUAL_ACTION_CDP_HOST` plus the registry debug port |
| CDP attach succeeds | Emit `manual_action_attach_success` and continue the persisted phase |
| Page cap is reached without block evidence | Complete as listing-partial; do not create an IP/WAF manual action |

### 5. Good / Base / Bad Cases

- **Good:** Detail target 191 returns `-1000035`. The task keeps the first 190
  completed results, shows change-IP guidance, opens the registered host
  profile, and after operator verification resumes with target 191/pending
  work rather than resetting the cohort.
- **Base:** An old OfferToday event contains only `classification=ip_blocked`
  in its resume context. Snapshot, helper, and dispatcher independently
  normalize it to the same actionable contract without mutating the event.
- **Bad:** The helper opens one profile while the worker recomputes an
  OfferToday fresh-profile path. The registry lookup cannot find the open
  browser and reuse fails despite a visible verified page.
- **Bad:** An identity conflict is normalized as generic human verification.
  This hides the integrity problem and permits an unsafe automatic resume.

### 6. Tests Required

- `test_offertoday_standalone_crawl.py`: listing and detail `ip_blocked`
  payloads contain classification/code/evidence/context/browser fields,
  preserve prior metrics, stop later work, and never emit completion.
- `test_crawl_task_snapshot.py`: an old incomplete IP-block event projects as
  actionable with change-IP text, exact issue code/stage, browser fields, and
  both resume capabilities.
- `test_crawl_job_regressions.py`: legacy normalization permits a valid resume,
  copies the host profile for `reuse_open_browser`, and still rejects identity
  audits or unsupported strategies.
- `test_offertoday_browser_runtime.py`: the configured Docker CDP hostname is
  resolved and `connect_over_cdp` receives the resolved host plus registry
  port.
- `CrawlTasksPage.test.jsx`: IP blocks render change-IP and preserved-progress
  guidance plus browser/resume actions; identity audits render neither action.
- Live verification: open the browser through the helper, complete the
  challenge/change network, resume with `reuse_open_browser`, observe
  `manual_action_attach_success`, and prove the same crawl leaves
  `manual_action_required` without losing completed detail progress.

### 7. Wrong vs Correct

#### Wrong

```python
manual_action = dict(latest_event.payload.get("manual_action") or {})
if not manual_action.get("resume_supported"):
    raise RuntimeError("manual action does not support resume")

browser = await playwright.chromium.connect_over_cdp(
    f"http://127.0.0.1:{session.debug_port}"
)
```

This rejects valid legacy OfferToday events and makes a Docker worker attach to
its own loopback address rather than the host browser.

#### Correct

```python
manual_action = normalize_manual_action_payload(
    latest_event.payload.get("manual_action"),
    source_site=crawl_job.source_site,
    request_payload=latest_event.payload.get("request_payload") or crawl_job.request_payload,
    default_browser_channel=host_browser_channel,
    default_browser_profile_path=host_browser_profile_path,
)

cdp_host = resolve_manual_action_cdp_connect_host(
    settings.manual_action_cdp_host or settings.manual_action_helper_host
)
browser = await playwright.chromium.connect_over_cdp(
    f"http://{cdp_host}:{session.debug_port}"
)
```

The compatibility boundary, profile identity, and container-to-host network
boundary remain explicit and independently testable.

## Scenario: Listing-bound detail scope and truthful crawl-task history

### 1. Scope / Trigger

Use this contract when changing durable Crawl Tasks ordering, the direct-run
OfferToday detail scope control, detail target selection/resume behavior, or
the distinct progress fields returned by crawl-task snapshots.

This boundary exists because mutable crawl metrics update both detail jobs and
their source listing jobs. Activity timestamps are useful display evidence but
are not stable history identity, and staging-row counts are not canonical job
progress.

### 2. Signatures

```http
POST /api/v1/crawl-jobs
Content-Type: application/json

{
  "source_site": "offertoday",
  "crawl_phase": "detail",
  "source_listing_crawl_job_id": "<listing-crawl-uuid>",
  "category_ids": [],
  "detail_limit": 5000,
  "detail_statuses": ["pending", "failed", "manual_action_required"],
  "skip_existing": false
}
```

```http
GET /api/v1/crawl-jobs/tasks?page=<n>&page_size=<n>&time_range=all
```

```python
CrawlJobRepository.list_crawl_task_page(
    db,
    *,
    page,
    page_size,
    status,
    source_site,
    crawl_mode,
    updated_since=None,
) -> tuple[list[CrawlJob], int]

build_crawl_task_snapshot(
    crawl_job,
    latest_event,
    *,
    now,
    events=None,
    category_lookup_cache=None,
) -> dict[str, Any]
```

### 3. Contracts

#### Stable task history

Durable Crawl Tasks history uses this exact order:

```text
queued_at DESC, created_at DESC, id DESC
```

`updated_at` remains display-only. Progress, issue, reconciliation, or linked
listing metric updates must not move an existing row. The API preserves
repository order and the frontend must not sort by mutable activity time.

#### Listing-bound versus global detail scope

- OfferToday detail mode defaults to the newest `completed` listing batch with
  pending, failed, or manual-action work. Compare immutable `queued_at`, then
  use the crawl-job ID as a deterministic tie-breaker.
- Selecting a batch persists `source_listing_crawl_job_id` in the crawl-job
  request payload. Resume starts from that payload and must preserve the ID.
- When `source_listing_crawl_job_id` is present,
  `resolve_offertoday_detail_category_ids()` returns `[]`. Selection filters by
  listing crawl-job ID and includes null-classification keyword/hybrid rows.
- When the batch ID is absent, global category backlog is an explicit advanced
  scope. Requested root categories expand normally and
  `source_classification_id` filtering remains active.
- Group candidate rows by canonical `source_job_id` before applying
  `detail_limit`; duplicate staging siblings produce one fetch target.

#### Distinct progress projection

The task-list and active-progress paths batch-load these event types once for
all task IDs in the requested set:

```text
crawl.detail_cohort_frozen
crawl.detail_attempt
crawl.detail_reconciled
```

For OfferToday tasks with frozen-cohort evidence, snapshots expose:

```text
detail_distinct_target_total
detail_distinct_succeeded
detail_distinct_terminal_unavailable
detail_distinct_failed
detail_distinct_reconciled
detail_distinct_remaining
```

The first largest frozen fetch cohort is the stable target universe; later
resume cohorts are subsets and do not replace the denominator. Reconciled IDs
were removed before the fetch cohort was frozen, so reconciliation is reported
as adjacent scope and is not subtracted from fetch-target remaining.

Count distinct canonical `source_job_id` values. `success` wins over terminal
and failure; `terminal_unavailable` wins over failure. Non-retrying
`invalid_payload`, `id_mismatch`, `persist_failure`, and exhausted
`transient_transport` attempts are failed unless the same ID has success or
terminal evidence. Recoverable `auth_expired`, `waf_challenge`, and
`ip_blocked` attempts do not settle or inflate a target.

```text
remaining = max(target_total - distinct(success U terminal U failed), 0)
```

If no frozen-cohort event exists, return null distinct fields and retain the
legacy Queue/Saved projection. Do not reinterpret `detail_run_completed` as a
job count; it is a staging-row metric. OfferToday `jobs_saved` fallback checks
raw `metrics.jobs_saved` before ingest-only counters; other sources retain
their existing ingest-first projection.

The Crawl Tasks list row and Task Details panel render the same summary:

```text
Fetched <success> / <target>
Terminal <terminal>          # non-zero only
Reconciled <reconciled>      # non-zero only
Failed <failed>              # non-zero only
Remaining <remaining>
```

### 4. Validation & Error Matrix

| Condition | Required result |
|---|---|
| Only `updated_at` or metrics change | Task ID order remains unchanged |
| Queue/creation timestamps tie | `id DESC` resolves order deterministically |
| Bound batch row has null classification | Include it when status is eligible |
| Bound request also carries category IDs | Ignore category narrowing |
| Unbound root category is requested | Expand and filter global backlog |
| Duplicate staging rows share one canonical ID | Fetch once after grouping |
| Resume follows IP/auth/WAF stop | Preserve batch ID and original denominator |
| An ID has blocked attempts then success | Count one success, zero blocked settlement |
| An ID has success plus duplicate attempts | Count the ID once |
| No frozen cohort exists | Emit null distinct fields and use legacy UI fallback |
| Listing condition reaches page cap | Preserve partial-listing semantics; do not classify as detail failure |

### 5. Good / Base / Bad Cases

- **Good:** A completed keyword/hybrid listing batch contains null-category
  rows. Detail mode selects that batch, fetches every eligible distinct ID,
  survives an IP-block resume, and continues to show the original denominator.
- **Base:** An older task has no cohort event. Its row continues to show
  `Queue <detail_target_rows>` without claiming distinct completion.
- **Bad:** History is sorted by `updated_at`, so downstream staging metrics move
  an old listing task above a running detail task every polling interval.
- **Bad:** A bound listing ID and `category_ids=[118000]` are both applied at the
  repository query, silently excluding keyword/hybrid rows with null category.
- **Bad:** `detail_run_completed=2464` is displayed as fetched jobs even though
  duplicate staging siblings produced that row count.

### 6. Tests Required

- `test_crawl_job_runtime.py`: immutable queue/creation/ID ordering with
  timestamp ties and pagination; bound null-category keyword/hybrid selection;
  other-batch exclusion; duplicate grouping; unbound category expansion.
- `test_crawl_job_regressions.py`: manual dispatch persists the selected listing
  ID and IP-block resume retains it.
- `test_offertoday_standalone_crawl.py`: detail manual-action resume context
  contains `source_listing_crawl_job_id` and later targets remain untouched.
- `test_crawl_task_snapshot.py`: duplicate attempts, recoverable blocks,
  terminal/failure precedence, reconciled union, multiple resume cohorts,
  active-path batch wiring, raw `jobs_saved`, and the historical
  `1311/1305/6/95/0` projection.
- `CrawlTasksPage.test.jsx`: running, manual-action, completed, and legacy
  fallback summaries in both row chips and Task Details; partial listing remains
  unchanged; frontend consumes API order.
- `ScheduleManager.test.jsx`: newest completed eligible batch wins even when API
  order differs, running batches are skipped, explicit global scope survives an
  async batch response, and submitted payload carries the listing ID.

### 7. Wrong vs Correct

#### Wrong

```python
rows = query.order_by(desc(CrawlJob.updated_at)).all()
completed = int(metrics.get("detail_run_completed") or 0)
```

```jsx
<option value="">No legacy batch filter</option>
```

This makes history jump on activity, calls staging rows completed jobs, and
makes global category backlog look like the normal detail path.

#### Correct

```python
rows = query.order_by(
    desc(CrawlJob.queued_at),
    desc(CrawlJob.created_at),
    desc(CrawlJob.id),
).all()

detail_progress = project_distinct_detail_events(events_by_job[crawl_job.id])
```

```jsx
<option value="">Global category backlog (advanced)</option>
```

Immutable history identity, explicit scope, and one shared event projection
keep the repository, API, and UI on the same units.
