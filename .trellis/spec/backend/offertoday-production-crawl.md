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

`listing_capped_condition_ids` is the runner's condition identity. Production
also maps those conditions through the immutable runtime plan to ordered,
source-qualified `listing_capped_classification_ids` for Task Control recovery.
These IDs are emitted only for the per-condition `page_cap`
retain-and-continue path. A whole-run `run_page_cap` is a separate hard stop
and must not be presented as capped Query Targets or used to create a
continuation draft.

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
listing_capped_classification_ids
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

OfferTodayBrowserRuntime._fetch_json_response(
    url,
    *,
    method,
    payload=None,
) -> _OfferTodayHttpJsonResponse
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

The helper also exposes `GET /health`. Runtime capabilities must distinguish a
configured helper URL from a reachable helper and include the health URL plus
an environment-appropriate manual-start command. The frontend keeps
`Open Browser` disabled while health is unavailable, exposes Retry and the
manual-start instruction, and re-enables it after a successful health check.
There is no resident launcher or automatic host-process startup contract.
`Resume Fresh` remains independent of helper reachability.

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
and resume the same crawl. Listing evidence records the hard-stop observation,
blocked response URL, exact code, page count, and accepted-ID count; it never
persists an unbounded accepted-ID list. Detail evidence includes the blocked
`source_job_id`, listing IDs, `detail_index`, and `detail_total`.

`resume_context` must contain enough data to redispatch the same phase. Listing
context includes the search categories/keywords and page budget. Detail context
includes `detail_scope`, `source_listing_crawl_job_id` when bound, detail
statuses, and detail limit. A detail resume preserves the stored scope and
batch ID; it selects `manual_action_required` and `pending` targets, while
completed targets are not reset or fetched again.

#### Browser-fetch redirect race

OfferToday may navigate the page to `/web/passport/cm/verify.html` while an
in-page `window.fetch()` is active. Playwright then rejects `page.evaluate()`
with `TypeError: Failed to fetch` before an API payload exists.

`OfferTodayBrowserRuntime._fetch_json_response()` handles only recognized
browser-fetch rejection messages. It gives the page URL a bounded settle
window (currently at most 150 ms), captures the post-error `page.url`, and
raises `OfferTodayTransportError(error_kind="network", response_url=...)`.
Programming/context errors still propagate unchanged.

`classify_offertoday_response()` parses the verification URL's exact integer
query code before applying the generic verify-path rule:

```text
verify URL code=-1000035 -> ip_blocked, retryable=false, stop_batch=true
other verify URL          -> waf_challenge, retryable=false, stop_batch=true
failed fetch on normal URL -> transient_transport, retryable=true
```

`ListingPageObservation.response_url` carries this evidence through the
production listing runner. The frozen historical
`listing_observation_to_payload()` serializer always omits the new field;
`_production_listing_observation_payload()` adds it only to production crawl
events. The full URL remains in the durable manual-action payload, while
structured logs strip query/fragment values and log `classification` / `code`
separately.

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
| `page.evaluate()` fails and settled page URL has `code=-1000035` | Classify one non-retryable `ip_blocked` attempt, preserve URL/code, and pause |
| `page.evaluate()` fails on a normal page URL | Keep `transient_transport`; use the bounded retry policy |
| Non-fetch Playwright programming/context error | Propagate unchanged; do not normalize as network/IP |
| Verify URL has another or missing code | Classify `waf_challenge`, not `ip_blocked` |
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
- **Good:** Listing fetch aborts while the page redirects to
  `verify.html?code=-1000035`. One attempt is recorded, the exact URL/code reach
  the durable manual action, and no transient retry or detail request occurs.
- **Base:** An old OfferToday event contains only `classification=ip_blocked`
  in its resume context. Snapshot, helper, and dispatcher independently
  normalize it to the same actionable contract without mutating the event.
- **Bad:** The helper opens one profile while the worker recomputes an
  OfferToday fresh-profile path. The registry lookup cannot find the open
  browser and reuse fails despite a visible verified page.
- **Bad:** An identity conflict is normalized as generic human verification.
  This hides the integrity problem and permits an unsafe automatic resume.
- **Bad:** The rejected fetch is classified from the original API URL before
  the page URL settles. The IP block becomes a generic transport retry and the
  operator sees only `Page.evaluate: Failed to fetch`.

### 6. Tests Required

- `backend/tests/test_cross_source_ip_recovery.py`: synchronous and delayed
  redirect races, exact `-1000035` classification, other-verify WAF behavior,
  normal-page transport behavior, non-fetch error propagation, one-attempt
  listing hard stop, production-only response URL, compact evidence, and
  source-aware same-task resume payload.
- `backend/tests/test_cross_source_crawl_logging.py`: OfferToday listing/detail
  manual and terminal summaries, retry correlation, common fields, and blocked
  URL query-secret exclusion.
- `frontend/src/components/scraper/ipBlockGuidance.test.js`: source-aware
  CTGoodJobs, JobsDB, OfferToday, and unknown-source change-IP guidance.
- Run focused tests, Ruff, `compileall`, frontend helper tests/build, container
  health/log smoke, and `git diff --check` without restoring the intentionally
  deleted legacy suites.
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

#### Redirect race: wrong

```python
except Exception as exc:
    raise OfferTodayTransportError(
        "fetch failed",
        response_url=request_url,
        error_kind="network",
    ) from exc
```

This records the original API URL and can consume transient retries while the
page is already redirecting to an IP-verification URL.

#### Redirect race: correct

```python
except Exception as exc:
    if not is_browser_fetch_rejection(exc):
        raise
    response_url = await capture_bounded_post_fetch_url(page, request_url)
    raise OfferTodayTransportError(
        "fetch interrupted",
        response_url=response_url,
        error_kind="network",
    ) from exc
```

The response policy, not the raw Playwright error string, decides whether the
settled URL is an IP block, a generic WAF challenge, or transient transport.

## Scenario: Versioned finite detail scope and truthful crawl-task history

### 1. Scope / Trigger

Use this contract when changing durable Crawl Tasks ordering, versioned detail
scope/limits, Dispatch Plan target selection, recovery/cancellation, or the
normalized detail projections consumed by the Task Control Board.

The versioned contract replaces the old OfferToday-only behavior where
`detail_limit` capped one recovery segment and the same task repeatedly queried
a changing backlog. New code freezes one finite complete-run membership before
dispatch. Legacy fields/events remain readable compatibility evidence only.

### 2. Signatures

```http
POST /api/v1/dispatch-plans
Content-Type: application/json

{
  "version": 1,
  "kind": "one_off",
  "scope": {"version": 1, "source_site": "offertoday", "mode": "all", "rules": []},
  "listing_settings": null,
  "detail_settings": {
    "version": 1,
    "crawl_mode": "headless",
    "backlog_scope": {"kind": "source_backlog"},
    "limit": {"kind": "stop_after", "detail_run_cap": 5000},
    "backlog_snapshot": null
  }
}
```

```http
POST /api/v1/dispatch-plans/{plan_id}/dispatch
{"confirmation_token":"...","expected_plan_fingerprint":"<sha256>"}

GET /api/v1/crawl-jobs/tasks?page=<n>&page_size=<n>&time_range=all
GET /api/v1/task-control-board?source_site=offertoday
```

```python
DispatchPlanService.prepare(command, readiness, prepared_by) -> DispatchPreparationV1
load_worker_startup_input(db, crawl_job_id, default_source_site) -> WorkerStartupInput
build_crawl_task_snapshot(crawl_job, latest_event, *, now, events=None) -> dict[str, Any]
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

#### Explicit backlog scope and finite membership

`DetailBacklogScopeV1` has exactly three source-qualified variants:

```text
source_backlog
crawl_scope(scope=AuthoredCrawlScopeV1)
listing_batch(source_listing_crawl_job_id=UUID)
```

- `source_backlog` selects eligible canonical IDs for one Source and includes
  null-classification rows. `crawl_scope` applies the reviewed source-native
  classification expansion. `listing_batch` stays bound to the explicit
  listing Crawl Job and includes that batch's null-classification rows.
- Crawl Scope contracts use source-qualified IDs such as
  `offertoday:118000`, while historical staging rows may persist the native
  token `118000`. Detail candidate queries must match both the qualified and
  native representations at the repository boundary; they must never fall
  back to an unscoped query when the qualified filter has no direct match.
- No mode auto-selects the newest listing batch. Primitive `category_ids` and
  empty-array defaults cannot narrow or replace a versioned backlog scope.
- Preparation records a timezone-aware cutoff, groups eligible staging rows by
  canonical `source_job_id`, and persists one ordered target plus every
  contributing sibling row. Rows after the cutoff are not members.
- `stop_after.detail_run_cap` is the complete-run target cap. It is applied
  after canonical grouping. `entire_snapshot` freezes every eligible target
  only when the count fits the absolute safety cap; otherwise preparation
  fails with `BACKLOG_SAFETY_CAP_EXCEEDED`.
- The stored target/row membership, cutoff, counts, and fingerprint are
  immutable reviewed authority. Plan creation does not change staging status or
  launch a crawl.

#### Runtime, recovery, and cancellation

- A worker loads the consumed plan by Crawl Job ID and processes only its
  persisted targets/rows. Compatibility `request_payload`, later Catalog
  publication, and later-eligible staging rows cannot extend the run.
- Recovery Segment size is internal pacing. It may partition the frozen target
  order but never increase `detail_run_cap` or query another cohort into the
  same run. A successful final segment completes when plan membership is
  settled even if live future backlog is non-empty.
- IP/auth/WAF resume retains the original plan/fingerprint/membership and adds
  only execution-generation/resume context. Completed and terminal targets are
  not reset or fetched again.
- Cancellation remains `cancelling -> cancelled`. Acknowledgement releases
  only still-running plan membership to retryable state and preserves committed
  outcomes. A new mutually exclusive run cannot rely on the cancel request
  alone.
- The old per-segment continuation fields remain normalized for historical
  tasks. No new versioned path authors or executes that behavior.

#### Normalized detail projection

For a versioned run, immutable plan content supplies scope, cutoff, target
count, limit kind, and complete-run cap. Mutable runtime metrics may supply
outcomes only; they cannot redefine authority.

```text
detail_run_cap
detail_snapshot_cutoff_at
detail_snapshot_target_count
detail_snapshot_fetched_count
detail_snapshot_failed_count
detail_snapshot_unavailable_count
detail_snapshot_manual_action_count
detail_snapshot_remaining_count
detail_live_future_eligible_count
```

The normalized board/API object is:

```text
detail_snapshot.backlog_scope
detail_snapshot.limit_kind
detail_snapshot.cutoff_at
detail_snapshot.target_count
detail_snapshot.fetched_count
detail_snapshot.saved_count
detail_snapshot.failed_count
detail_snapshot.unavailable_count
detail_snapshot.manual_action_count
detail_snapshot.remaining_count
detail_snapshot.future_eligible_count
detail_snapshot.detail_run_cap
```

`remaining_count` means unresolved work inside the frozen plan.
`future_eligible_count` means live eligible work outside that plan. They may
both be non-zero and must never be added or substituted. Raw
`detail_run_completed` remains a staging-row compatibility metric, not a
canonical target count.

`ScrapeProgressPanel` remains the intentionally compact live-status shell; it
links to normalized Crawl Tasks/Task Details rather than parsing raw request or
event payloads.

### 4. Validation & Error Matrix

| Condition | Required result |
|---|---|
| Only `updated_at` or metrics change | Task ID order remains unchanged |
| Queue/creation timestamps tie | `id DESC` resolves order deterministically |
| Duplicate staging rows share one canonical ID | One target; persist every eligible sibling row |
| Row becomes eligible after snapshot cutoff | Report as future backlog; never add to this plan |
| Entire snapshot exceeds absolute cap | `BACKLOG_SAFETY_CAP_EXCEEDED`; persist no plan |
| Prepared membership is empty | Block with `DETAIL_BACKLOG_EMPTY`; issue no confirmation token |
| Qualified Crawl Scope ID targets native staging values | Match qualified and native ID representations; do not report a false empty backlog |
| Compatibility payload claims other IDs/cap | Ignore it; consumed plan remains authority |
| One target/row becomes ineligible before consume | Reject the whole plan as stale; claim nothing |
| Resume follows IP/auth/WAF stop | Keep the same plan and unfinished membership |
| Segment finishes while future backlog exists | Complete this finite run; expose future count separately |
| Cancellation requested but not acknowledged | Keep `cancelling`; do not treat as stopped |
| Listing condition reaches page cap | Preserve partial-listing semantics; do not classify as detail failure |

### 5. Good / Base / Bad Cases

- **Good:** A source backlog has 8 canonical IDs represented by 11 staging
  rows. A reviewed cap of 8 freezes all 8 targets and all 11 sibling rows. Two
  internal segments process only those IDs; 5 later IDs appear solely as
  `future_eligible_count=5`.
- **Good:** A listing-batch plan includes a null-classification row, survives an
  IP-block resume, and never switches to another batch.
- **Base:** An empty eligible query produces a blocked review with zero frozen
  targets and no launch token.
- **Good:** `offertoday:118000` matches staging rows persisted with native
  `118000`, so the reviewed classification scope freezes those eligible jobs.
- **Bad:** Runtime re-queries the global backlog after each segment until empty.
  The reviewed cap becomes a segment size and one run can grow without bound.
- **Bad:** JSX subtracts `detail_run_completed` from a plan target count or
  labels future backlog as remaining-in-run.

### 6. Tests Required

- `backend/tests/test_dispatch_plan_service.py`: three backlog scopes, cutoff,
  duplicate sibling membership, deterministic order/fingerprint, complete-run
  cap, empty/over-cap/stale selection, future rows, resume, cancellation, and
  transaction/concurrency rollback.
- `backend/tests/test_versioned_listing_runtime.py`: all Source runtimes consume
  only plan membership, segment without expansion, and publish future backlog
  separately.
- `backend/tests/test_crawl_task_snapshot_service.py`: snapshot authority wins
  over mutable counters; remaining-in-snapshot and future backlog stay distinct;
  cancellation/recovery remain normalized.
- `backend/tests/test_crawl_control_api.py`: reviewed fingerprint dispatch plus
  identical normalized detail/recovery projections in Crawl Tasks and Task
  Control Board, with no raw request/event payload dependency.
- Retain `test_offertoday_global_detail_backlog.py` only for legacy readability
  and source selection regression; it does not define new versioned limits.
- Run focused scope/plan/runtime/snapshot/cancellation tests and one complete
  backend suite. PostgreSQL tests cover atomic claims, rollback, and row-lock
  races.

### 7. Wrong vs Correct

#### Wrong

```python
while eligible_rows := repository.list_detail_candidates(source_site="offertoday"):
    process(eligible_rows[:detail_limit])
```

This makes `detail_limit` a segment size and silently absorbs work that was not
reviewed into the run.

#### Correct

```python
startup = load_worker_startup_input(
    db,
    crawl_job_id=crawl_job.id,
    default_source_site="offertoday",
)
runtime_plan = startup.detail_runtime_plan
for segment in partition(runtime_plan.targets, recovery_segment_size):
    process(segment)
```

The immutable plan defines complete-run membership; pacing only partitions it,
and later eligible work belongs to a later reviewed plan.
