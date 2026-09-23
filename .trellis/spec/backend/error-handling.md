# Backend Crawl Error-Handling Contracts

## Scenario: Cross-source IP-block pause and explicit same-task resume

### 1. Scope / Trigger

Use this contract when CTGoodJobs, JobsDB, or OfferToday listing/detail
transports encounter access-denied evidence, WAF verification, authentication
expiry, or generic network failures.

An IP block is an operator-recoverable crawl stop. It is not a retryable
transport guess: only positive source/browser evidence may produce
`classification="ip_blocked"`.

### 2. Signatures

```python
classify_public_access_evidence(
    *,
    source_site: str,
    status_code: int | None = None,
    final_url: str | None = None,
    title: str | None = None,
    text: str | None = None,
) -> PublicAccessEvidence | None

build_session_recovery_manual_action(
    *,
    source_site,
    stage,
    blocked_url,
    classification,
    code=None,
    evidence=None,
    resume_context=None,
) -> ManualActionRequiredError

normalize_manual_action_payload(
    payload,
    *,
    source_site,
    request_payload=None,
    default_browser_channel=None,
    default_browser_profile_path=None,
) -> dict[str, Any]

resolve_manual_action_cdp_connect_host(configured_host: str | None) -> str

launch_browser_process(
    *, browser_channel, browser_profile_path, blocked_url, ...
) -> dict[str, Any]

_resolve_host_browser_profile_path(browser_profile_path: str) -> Path
```

The only product continuation endpoint is explicit:

```http
POST /api/crawl-jobs/{crawl_job_id}/resume
```

### 3. Contracts

#### Positive evidence boundary

| Source | `ip_blocked` evidence | Non-IP result |
|---|---|---|
| CTGoodJobs | HTTP 403/429 or explicit IP/rate-limit/access-block marker in bounded navigation evidence | Generic Cloudflare/human verification is `waf_challenge`; proxy/display/profile failures keep their own classes |
| JobsDB | HTTP 403/429 without an explicit challenge header, or an explicit IP/rate-limit/access-block marker in listing/detail response evidence | Generic interstitial is `waf_challenge`; `cf-mitigated: challenge` is strong WAF evidence even when the status is 403; other HTTP/network/parser behavior remains transport/failure |
| OfferToday | Exact API code `-1000035` or verify URL query `code=-1000035` | Other verify URLs are `waf_challenge`; failed fetch on a normal URL is transient transport |

DNS, connection reset, timeout, malformed JSON/HTML, parser failure, and auth
failure must never become `ip_blocked` without separate positive evidence.
Classify IP evidence before generic WAF markers because a blocked response may
also render a challenge page. An explicit `cf-mitigated: challenge` response
header is stronger than a generic 403 and must classify as `waf_challenge`.
Never store or log the inspected response body.

#### JobsDB listing transport retry boundary

`CategoryListScraper.fetch_page()` retries only transient JobsDB transport
exceptions: `httpx.TimeoutException`, `httpx.NetworkError`,
`httpx.RemoteProtocolError`, and `httpx.ProxyError`. The existing
`settings.scraper_max_retries` value is the retry count, so the default `3`
allows four total attempts with cancellation-aware 1, 2, and 4 second waits.

An internal transport retry belongs to the same logical listing page. It does
not call the outer `before_request` hook again and therefore consumes no extra
Dispatch Plan request-budget claim. Emit `SCRAPE_LISTING_PAGE_RETRY` only when
another attempt will occur; include category, page, attempt, maximum attempts,
delay, and exception type, but never raw exception text.

HTTP status errors, positive access-block/manual-action evidence, malformed
JSON, `httpx.LocalProtocolError`, programming errors, and cancellation are not
retryable at this boundary. Exhausted transient attempts re-raise the last
exception so the standalone executor records the existing truthful terminal
failure while retaining previously staged pages.

#### Pause payload and state

A confirmed block raises `ManualActionRequiredError` with:

```text
action_type = session_recovery
classification = ip_blocked
source_site
stage
blocked_url
code (when supplied by the source)
evidence = compact status/code/final-url/reason fields
resume_context = original phase/scope
resume_supported = true
message/instructions = source-aware change-IP/network guidance
```

The outer executor persists `crawl.manual_action_required`, sets the crawl job
to `manual_action_required`, and stops later listing/detail requests. It does
not consume remaining transient retries and does not begin detail after a
listing stop.

#### Persisted recovery boundaries

- CTGoodJobs stages each listing page. Resume may replay earlier pages; the
  same-crawl upsert retains one row per source Job ID.
- JobsDB awaits atomic page staging before requesting the next page. Resume
  repeats the deterministic category/page walk and upserts committed pages.
- OfferToday stages each validated response-cursor page; an IP/WAF/auth hard
  stop prevents detail loading.
- All detail paths persist the blocked target as
  `manual_action_required`. Resume selects `manual_action_required,pending`;
  completed targets are excluded and not fetched again.

Recovery is operator-driven. While paused, no worker polls the source and no
automatic resume occurs. The operator changes/clears the public IP/network,
confirms access, and clicks Resume for the same crawl-job ID.

#### Reusable-browser transport and attempt feedback

Every browser adapter connecting from Docker to a browser opened on the Windows
host must resolve `settings.manual_action_cdp_host` (falling back to
`settings.manual_action_helper_host`) through
`resolve_manual_action_cdp_connect_host(...)` before `connect_over_cdp`. Never
hard-code `127.0.0.1` in a container-side adapter: inside Docker it addresses
the container, not the operator browser.

Attach attempt, success, and failure records use `build_scrape_log_event()` and
include `source`, `crawl_job_id`, `strategy`, configured `cdp_host`, resolved
`cdp_connect_host`, and `debug_port`. Failures include only a bounded
`error_type` or reason; raw exception text and browser/session data are not
logged. An attach failure remains `reuse_open_browser_unavailable` and consumes
no detail target.

Crawl Tasks derives the latest explicit recovery attempt from the tail of the
existing event endpoint: newest `crawl.resume_requested`, followed by the first
later `crawl.manual_action_required` outcome when present. An unresolved attempt
disables both Resume strategies. Helper/browser connectivity never initiates a
resume by itself.

#### Crawl Tasks recovery projection

`build_crawl_task_snapshot(...)` treats the ordered event history as the
manual-action source of truth. When the persisted crawl-job status is
`manual_action_required`, it projects and normalizes the newest
`crawl.manual_action_required` event even if a later progress or segment event
is the job's overall latest event. This keeps `manual_action.resume_supported`
and `manual_action.reuse_open_browser_supported` available to the frontend.

The projection must not expose an older manual action after the crawl leaves
`manual_action_required`; completed, cancelled, failed, or resumed tasks do not
show stale recovery controls. Browser defaults may be supplied only for sources
that actually share the configured JobsDB/CTGoodJobs headed browser. OfferToday
must preserve its event-provided Edge/profile metadata and must not inherit
JobsDB-only defaults.

JobsDB browser-profile recovery is fail-closed. A fresh-profile Resume may make
one automatic cleanup/retry after process and registry liveness both prove the
task-owned profile is dead; a second launch failure becomes a new manual action.
The same contract applies to CTGoodJobs. Shared primitives live in
`browser_profile_recovery.py`; `jobsdb_profile_recovery.py` is compatibility-only.
Task profiles live at `<configured-root>/tasks/<crawl-job-id>` and non-task browser
operations at `<configured-root>/operations/<operation-id>`. Reset and terminal
cleanup require canonical containment beneath that configured root, the expected
ownership directory, and proven-dead liveness. Path traversal, an unrelated root,
or a symlinked owner/profile directory fails closed before process inspection or
recursive deletion. Fixed profiles must equal the configured root; they retain
cookies/login data and remove only stale singleton markers plus registry state.
Unknown liveness never mutates profile state.

The host manual-action helper is cross-platform. It resolves `chromium`,
`chrome`, and `msedge` through host-native application/PATH candidates, then
falls back to the installed Playwright Chromium executable for the `chromium`
channel. `JOBSDB_HEADED_BROWSER_EXECUTABLE_PATH` overrides discovery when set.
The host bootstrap command is a Python 3 command (`python3` on macOS/Linux); its
host-only requirements must keep SQLAlchemy at `>=2.0.44,<2.1` and
`psycopg2-binary>=2.9.11` so Python 3.14 can import the helper runtime.
When the host helper inherits the Compose database URL, it translates the
container-only `postgres-db:5432` endpoint to the published host endpoint
`127.0.0.1:5433`; `MANUAL_ACTION_HELPER_DATABASE_URL` is the explicit override
for a different host database.
When the API worker runs in Docker, a profile under
`/app/.host_browser_profiles/...` is translated to the bind-mounted
`backend/.host_browser_profiles/...` path only for the local browser process;
the API-visible path remains the registry key used by the worker's CDP attach.
The helper must prove the translated profile parent exists before launch or
close operations.

Normal headless JobsDB execution never calls the helper. For a supported WAF
challenge, the operator explicitly uses the helper to open a separate headed
verification browser, completes the challenge, and chooses
`reuse_open_browser` for that recovery attempt.

JobsDB detail transport is stable across new runs and resumes:
`jobsdb_standalone_crawl._detail_scraper_context(...)` always constructs
`JobsDBBrowserDetailScraper`. `crawl_mode` controls only fresh-browser
visibility (`headless` launches an invisible worker-owned browser; `headed`
launches a visible one), while `resume_strategy="reuse_open_browser"` is the
only path that attaches to the operator's verification browser. Never select
the legacy HTTP detail scraper or change transports merely because
`is_resume=true`; doing so makes checkpoint recovery behave differently from
the reviewed run.

Routine CTGoodJobs listing and detail execution follows the same headless-first
boundary. Headed remains an explicit debug/manual-recovery mode; a WAF/IP/human
verification signal never triggers a hidden headless-to-headed retry.

### 4. Validation & Error Matrix

| Condition | Required result |
|---|---|
| HTTP 403/429 on CTGoodJobs/JobsDB | Typed `ip_blocked`; immediate manual action |
| HTTP 403 with `cf-mitigated: challenge` | Typed `waf_challenge`; verification-browser guidance |
| Explicit IP/rate-limit marker on a 200 page | Typed `ip_blocked`; no generic challenge retry |
| Generic Cloudflare/human-verification page | `waf_challenge`, not IP |
| OfferToday exact code `-1000035` | Typed `ip_blocked`, code preserved, no transient retry |
| OfferToday other verify URL | `waf_challenge` |
| DNS/timeout/connection failure | Existing transient/failure behavior; never IP |
| JobsDB listing transport disconnect followed by success | Retry the same logical page without another request-budget claim |
| JobsDB listing transient failure on every attempt | Four attempts by default, then re-raise the final transport exception |
| JobsDB HTTP/local-protocol/parser/manual-action failure | Do not retry; preserve the typed or original failure |
| Cancellation during JobsDB retry backoff | Stop immediately; issue no later attempt |
| Listing block after committed pages | Keep prefix, emit manual action, skip detail |
| Detail block after completed targets | Keep completed targets; stop later targets |
| Resume attempted from `failed`/`running` | Reject; only `manual_action_required` is resumable |
| Resume capability explicitly false | Reject without changing crawl state |
| Operator has not clicked Resume | Issue zero new source requests |
| Manual action followed by a progress/segment event while still paused | Snapshot projects the newest manual-action event and keeps recovery controls available |
| Historical manual action followed by completion/resume | Snapshot returns `manual_action=null`; no stale recovery controls |
| OfferToday legacy event lacks browser fields | Do not synthesize JobsDB browser/profile values; reusable-browser support remains false |
| Container adapter resolves configured CDP host | Connect to the resolved host and registered debug port |
| CDP attach raises or exposes no context | Emit bounded attach failure; return resumable `reuse_open_browser_unavailable`; consume zero targets |
| Host helper receives `browser_channel=chromium` | Resolve a macOS/Linux/Windows executable or installed Playwright Chromium; otherwise return 409 with install/configuration guidance |
| Host helper receives a container `/app/.host_browser_profiles/...` path | Translate only the local process path; preserve the original path in the live-browser registry |
| Host process inspection is unavailable or incomplete | Fail closed; do not remove registry state or claim the profile is safe to reset |
| Temporary profile is outside the configured `tasks/` or `operations/` root, contains traversal, or resolves through a symlinked owner | `temporary_profile_not_owned`; do not inspect or delete it |
| Fixed profile does not equal the configured profile root | `fixed_profile_not_configured`; do not remove singleton markers |
| CTGoodJobs stale ProcessSingleton on the first fresh-profile resume launch | One proven-dead reset/retry; a second failure returns structured manual action |
| JobsDB new run or Fresh Profile Resume in `headless` mode | Use `JobsDBBrowserDetailScraper`; launch worker-owned Playwright with `headless=true`; do not call the Host Helper |
| JobsDB headless Resume with `reuse_open_browser` | Use `JobsDBBrowserDetailScraper`; attach to the explicitly opened verification browser over CDP |
| Latest resume event has no later outcome | Show accepted/waiting feedback and disable both Resume actions |
| Later manual-action event resolves the attempt | Show its stage/classification/message and permit another explicit action |

### 5. Good / Base / Bad Cases

- **Good:** JobsDB page 2 is staged, page 1 returns 429, and the same task
  pauses. After the IP changes, Resume replays page 2 idempotently and continues
  page 1 without losing rows or starting detail early.
- **Base:** A normal timeout remains transient/non-IP and follows the source's
  bounded retry policy.
- **Bad:** Any `Failed to fetch` is labeled IP blocked. A DNS outage now asks
  the operator to change IP and disables valid retry behavior.
- **Good:** JobsDB disconnects before response headers on page 124, waits one
  cancellation-aware second, and retries page 124 without claiming page 123's
  request budget.
- **Bad:** Catch every `httpx.TransportError`, causing a malformed local request
  to retry four times, or call `before_request` inside each transport attempt.
- **Bad:** A paused worker polls every few seconds and resumes itself. This
  violates explicit operator control and can immediately re-trigger a block.
- **Good:** A paused detail task emits `crawl.detail_segment` after
  `crawl.manual_action_required`; Crawl Tasks still renders the normalized
  recovery buttons from the manual-action event.
- **Bad:** Crawl Tasks reads manual-action fields only from the overall latest
  event, so a later bookkeeping event hides recovery controls while the task is
  still resumable.
- **Good:** JobsDB in Docker resolves `host.docker.internal`, attaches to the
  registered host-browser debug port, and continues the same target scope.
- **Good:** A macOS helper receives `/app/.host_browser_profiles/chromium`,
  launches Playwright Chromium from the bind-mounted backend profile, and
  registers `/app/...` so the container worker can attach over CDP.
- **Bad:** The helper reports connected, so the frontend automatically resumes
  or allows repeated Resume clicks before the previous event has an outcome.
- **Bad:** A macOS helper treats `chromium` as an unsupported branded channel,
  or launches with the container-only `/app` path and silently removes the
  registry entry when it cannot inspect host processes.

### 6. Tests Required

- `backend/tests/test_cross_source_ip_recovery.py` covers source-specific IP vs
  WAF/generic transport classification, immediate stop, committed page replay,
  same-task upsert behavior, compact/source-aware payloads, and completed-detail
  exclusion.
- `backend/tests/test_jobsdb_listing_pagination.py` covers transient disconnect
  recovery, bounded exhaustion, structured secret-safe retry logging, immediate
  HTTP/local-protocol failure, and cancellation-aware backoff.
- `backend/tests/test_cross_source_crawl_logging.py` covers listing/detail
  manual-action and terminal summaries plus no-later-target behavior.
- `frontend/src/components/scraper/ipBlockGuidance.test.js` covers source-aware
  operator guidance; production build proves both Crawl Tasks and Scrape
  Progress consume the helper.
- `backend/tests/test_crawl_task_snapshot_service.py` covers later-event
  ordering, stale recovery suppression after completion, and source-correct
  browser default projection.
- Synthetic responses are required for CTGoodJobs/JobsDB block tests. Do not
  deliberately ban the live public IP. Live OfferToday resume verification
  requires an actual operator IP change and explicit Resume.
- `backend/tests/test_jobsdb_browser_detail_scraper.py` proves the configured and
  resolved CDP host reaches `connect_over_cdp`, structured success fields are
  visible in formatted logs, and attach failure stays resumable.
- `backend/tests/test_listing_runtime.py` proves every JobsDB detail combination
  (new/Resume, headless/headed, Fresh Profile/Reuse Open Browser) enters the same
  mode-aware `JobsDBBrowserDetailScraper` transport.
- `frontend/src/components/scraper/recoveryAttemptUtils.test.js` and
  `CrawlTasksPage.test.jsx` cover attempt ordering, durable returned outcome,
  local request pending state, and disabled repeated Resume actions while the
  event-derived attempt is unresolved.
- `backend/tests/test_host_manual_action_helper.py` covers macOS Chromium
  discovery, Playwright fallback, container-to-host profile translation,
  Chromium process matching, and reachable CDP smoke behavior.
- `backend/tests/test_jobsdb_profile_recovery.py` covers shared lock recognition,
  dead-zombie handling, configured-root containment, path traversal, unrelated
  roots, symlinked owner rejection, and task/operation/fixed mutation boundaries.
- `backend/tests/test_ctgoodjobs_browser_page_scraper.py` covers CTGoodJobs mode
  propagation, owned profiles, one stale-lock retry, checkpoint metadata, and
  catalog/manual-action cleanup behavior.

### 7. Wrong vs Correct

#### Wrong

```python
except (TimeoutError, OSError, PlaywrightError) as exc:
    raise build_session_recovery_manual_action(
        source_site=source,
        classification="ip_blocked",
        evidence={"error": str(exc)},
    )
```

This guesses from a generic exception, leaks unbounded error text, and disables
legitimate retry behavior.

#### Correct

```python
evidence = classify_public_access_evidence(
    source_site=source,
    status_code=response_status,
    final_url=page_url,
    title=page_title,
)
if evidence and evidence.classification in {"ip_blocked", "waf_challenge"}:
    raise build_session_recovery_manual_action(
        source_site=source,
        stage=stage,
        blocked_url=evidence.final_url,
        classification=evidence.classification,
        evidence=evidence.to_payload(),
    )
```

The source adapter owns positive evidence; the shared manual-action layer owns
the pause/resume payload and operator guidance.

#### Wrong: project only the overall latest event

```python
raw_manual_action = _event_manual_action(latest_event)
```

A later segment/progress event can be valid while the persisted task remains
paused, so this drops a still-current recovery contract.

#### Correct: select by state and event kind

```python
manual_action_event = None
if crawl_job.status == "manual_action_required":
    manual_action_event = (
        latest_event
        if latest_event_type == "crawl.manual_action_required"
        else _latest_event_of_type(events, "crawl.manual_action_required")
    )
raw_manual_action = _event_manual_action(manual_action_event)
```

The persisted state prevents stale controls; the event-kind lookup preserves
the active recovery contract across later bookkeeping events.

#### Wrong: container-local CDP and invisible log extras

```python
logger.info("manual_action_attach_attempt", extra={"debug_port": port})
browser = chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
```

Default container logs may omit `LogRecord.extra`, and loopback cannot reach the
host browser.

#### Correct: resolved host and formatted bounded fields

```python
configured_host = settings.manual_action_cdp_host or settings.manual_action_helper_host
connect_host = resolve_manual_action_cdp_connect_host(configured_host)
logger.info(
    build_scrape_log_event(
        "manual_action_attach_attempt",
        source="jobsdb",
        cdp_host=configured_host,
        cdp_connect_host=connect_host,
        debug_port=port,
    )
)
browser = chromium.connect_over_cdp(f"http://{connect_host}:{port}")
```

#### Wrong: treat the API profile path as a host filesystem path

```python
process_launcher([executable, f"--user-data-dir={browser_profile_path}"])
```

#### Correct: translate only at the host process boundary

```python
host_profile = _resolve_host_browser_profile_path(browser_profile_path)
process_launcher([executable, f"--user-data-dir={host_profile}"])
registry.register(browser_profile_path=browser_profile_path, ...)
```

---

## Scenario: CTGoodJobs malformed-detail circuit breaker

### 1. Scope / Trigger

Use this contract when CTGoodJobs returns HTML that passes bounded IP/WAF
inspection but repeatedly fails canonical ingest because the document is not a
valid job detail. It prevents a verification or site-shape change from being
recorded as hundreds of unrelated job failures.

### 2. Signatures

```python
classify_ctgoodjobs_detail_page(
    *, status_code, final_url, title, html
) -> CTGoodJobsTerminalUnavailableEvidence | None

resolve_resume_detail_statuses(classification: str | None) -> list[str]
```

The manual-action classification is `content_anomaly`; its compact evidence is:

```text
reason = missing_job_content | missing_company_identity
consecutive_count = 2
```

### 3. Contracts

- Positive IP/WAF evidence runs before terminal-unavailable inspection.
- A positive CTGoodJobs WAF/interstitial classification pauses on its first
  occurrence. Do not spend transport retries on a page already known to need
  operator action.
- HTTP 404/410 or an explicit top-level removed/expired/not-found marker is
  `terminal_unavailable`; missing parsed fields alone are not expiry evidence.
- For HTTP 200 pages, unavailable marker text is authoritative only in the
  document title or an explicitly labelled page-state container (for example
  `data-page-state="job-not-found"`). Never scan arbitrary body prefixes or job
  descriptions for generic expiry phrases.
- CTGoodJobs' live expired-detail representation uses the source-owned
  `jd--expired` class and the top-level message `This job has expired`. Treat
  that class as an explicit page-state container, but still require a known
  unavailable marker within the captured container; the class token alone is
  not terminal evidence.
- The first allowlisted structural anomaly is `failed` and crawling continues.
- The immediately consecutive identical anomaly marks the current target
  `manual_action_required`, emits `content_anomaly`, and stops later requests.
- A successful detail or unrelated exception resets the consecutive signature.
- `content_anomaly` resume selects `failed,manual_action_required,pending` so
  the first anomaly is retried. Other manual-action resumes retain
  `manual_action_required,pending`.
- Never log or persist inspected HTML.

### 4. Validation & Error Matrix

| Condition | Required result |
|---|---|
| Explicit WAF marker plus `job not found` text | WAF manual action wins |
| Positive WAF marker on attempt 1 of N | Immediate manual action; one request total |
| HTTP 404/410 without WAF evidence | `terminal_unavailable`; continue next target |
| HTTP 200 `jd--expired` state with known expiry marker | `terminal_unavailable` with reason `job_expired`; continue next target |
| Expiry phrase inside an ordinary job description | Normal/unknown page state |
| First `missing_company_identity` | `failed`; continue |
| Second consecutive `missing_company_identity` | `content_anomaly`; stop |
| Anomaly, success, same anomaly | Two separate failures; no circuit break |
| Generic parser/network exception | Existing failed/transport behavior; never IP |

### 5. Good / Base / Bad Cases

- **Good:** Two consecutive verification-shaped pages pause after two requests,
  preserving completed work and retrying both anomaly targets after resume.
- **Base:** One genuinely malformed job fails, the next valid job succeeds, and
  crawling continues.
- **Bad:** Treating `missing_company_identity` as proof of expiry permanently
  drops a verification-blocked job.
- **Bad:** Inspecting unavailable markers before WAF markers turns a challenge
  page containing generic `job not found` copy into a terminal job outcome.

### 6. Tests Required

- `backend/tests/test_ctgoodjobs_page_state.py` covers HTTP and explicit page
  state evidence, the live `jd--expired` representation, and
  missing-field/body-text non-classification.
- `backend/tests/test_cross_source_ip_recovery.py` covers WAF precedence,
  resumable `content_anomaly`, non-IP guidance, and resume status selection.
- `backend/tests/test_cross_source_crawl_logging.py` covers first/second anomaly
  transitions, success reset, terminal-unavailable continuation, first-request
  WAF pause through the browser adapter, bounded logs, and no-later-target
  behavior.

### 7. Wrong vs Correct

#### Wrong

```python
except InvalidIngestPayloadError:
    mark_detail_failed(...)
    continue
```

#### Correct

```python
if reason == previous_allowlisted_reason:
    pause_as_content_anomaly(reason=reason, consecutive_count=2)
else:
    mark_detail_failed(...)
    previous_allowlisted_reason = reason
```

The bounded circuit breaker contains an unknown page-shape incident without
claiming it is an IP block, WAF challenge, or expired job.

---

## Scenario: Acknowledged manual crawl cancellation

### 1. Scope / Trigger

Use this contract when adding or changing Cancel behavior for manual listing or
detail `CrawlJob` executions. Scheduled crawls remain outside this flow.

### 2. Signatures

```http
POST /api/crawl-jobs/{crawl_job_id}/cancel
```

```text
queued | dispatching | running | manual_action_required
  -> cancelling + crawl.cancel_requested
  -> cancelled + crawl.cancelled     # only after execution stop is confirmed
```

```python
CrawlCancellationToken.raise_if_cancelled() -> None
CrawlCancellationToken.sleep(seconds: float) -> None
CrawlJobExecutionLauncher.request_cancel(*, crawl_job_id) -> bool
CrawlJobExecutionLauncher.recover_pending_cancellations() -> int
```

Durable process ownership is stored in `crawl_job_executions`. Each row carries
`crawl_job_id`, a UUID `generation`, PID, process create time, full command,
launcher instance, heartbeat/stop/exit timestamps, exit code, and execution
status. The generation is passed as `--execution-generation` and
`CRAWL_JOB_EXECUTION_GENERATION`.

Direct-launch execution ownership is also a liveness contract. The launcher
polls the durable heartbeat while supervising its local process. A heartbeat
older than `crawl_execution_heartbeat_stale_seconds` is terminal only after the
launcher verifies PID, process create time, stored command, Crawl Job ID, and
execution generation. A matching live process is stopped as a process tree; an
absent or identity-mismatched process is recorded stale without signalling the
PID. Access-denied or otherwise unverifiable identity remains active and is
retried with diagnostics. Startup performs the same stale reconciliation before
active execution rows can shield Crawl Jobs from interruption recovery.

### 3. Contracts

- Cancel is permanent and idempotent. `cancelled` tasks cannot Resume.
- `cancelling` means shutdown is pending; it must never claim that the worker is
  gone. `cancelled` is written only after no process remains.
- Workers check persisted cancellation immediately before each outbound
  listing/detail request. Controlled waits are split into slices of at most one
  second. An in-flight request may finish; no later request may start.
- Cooperative shutdown has 30 seconds. The supervisor then terminates the
  process tree and confirms exit before acknowledgement.
- PID is never sufficient ownership evidence. Validate process create time,
  crawl-job ID, execution generation, and the stored command before signalling.
  An unverifiable live PID remains `cancelling`; it is not treated as exited.
- API restart re-reads every `cancelling` task. Active generations are moved to
  `stop_requested` and supervised; tasks with no active execution are
  acknowledged without relaunching.
- Late worker transitions to running/completed/failed/manual-action cannot
  overwrite `cancelling` or `cancelled`.
- A non-cancelling execution heartbeat timeout records `crawl.failed`, marks the
  execution `terminated` or `stale`, and fails the Crawl Job only after owned
  process exit is confirmed. Existing completed, failed, manual-action,
  cancelling, and cancelled Crawl Jobs are never overwritten.
- Stale execution failure preserves committed listing events, metrics, and
  staging rows and releases only unresolved detail rows owned by the failed run.
- A deterministic detail persistence/programming failure is run-fatal. The
  executor records the first affected target as failed once, stops before later
  targets, and atomically records `crawl.failed` while releasing only owned
  still-`running` frozen rows to `pending` with outcome `failed_retryable`.
  Modeled target-content failures such as `InvalidIngestPayloadError` retain
  their source-specific continue or manual-action behavior.
- CTgoodjobs detail persistence has one Source-owned fact boundary:
  `jobContent.jobLocations[]` remains ordered Job evidence and its joined
  display value is stored on `Job.location` (`TEXT`), never copied into
  `Company.location`. The CTgoodjobs company mapper omits `location`, so an
  existing Company location is preserved.
- CTgoodjobs continues only after modeled item-content rejection such as
  `InvalidIngestPayloadError`, after that item's isolated transaction has
  rolled back and its listing is marked failed. `DetailPersistenceError`,
  SQL/database availability failures, rollback failures, cancellation,
  manual action, and unknown Python exceptions stop before the next target.
- During a current-schema cutover window, CTgoodjobs checks an oversized Job
  location against the actually deployed `jobs.location` type before any
  Company or Job flush. A finite deployed limit produces item-scoped
  `persistence_value_too_long` evidence containing only `field`, `limit`, and
  `value_length`; it never logs the full value. A deployed `TEXT` column has no
  limit and permits normal publication. Missing-column or introspection errors
  are unknown infrastructure errors and remain run-fatal.
- Keep committed/staged output. Cancelled listing metrics are partial and not
  naturally complete. Only detail rows owned by the task and still `running`
  return to `pending`; settled rows remain unchanged.
- Browser adapters own the final pre-navigation gate. A caller-only check is
  insufficient because cancellation can arrive between the caller and `goto`,
  `evaluate(fetch)`, or an adapter retry.

### 4. Validation & Error Matrix

| Condition | Required result |
|---|---|
| Queued/manual-action task has no active execution | Emit request event, then acknowledge `cancelled`; never launch |
| Active worker exits during grace period | Record execution exit, then acknowledge cancellation |
| Worker remains alive for 30 seconds | Terminate descendants and parent; acknowledge only after confirmed exit |
| PID create time or command differs | Treat as reused/unowned PID; never signal it |
| PID exists but identity access is denied | Keep `cancelling`; never infer process exit |
| API restarts after cancel intent commit | Recover supervision from the database generation |
| Popen or PID registration fails | Stop any created process; mark execution launch failed; settle CrawlJob as failed or cancelled |
| Scheduled task requests Cancel | Reject without state or event changes |
| Late worker reports failure/completion | Preserve cancelling/cancelled state; metrics may still merge |
| Detail persistence interface/programming error | Fail after the first target; release only unresolved owned rows and preserve settled output |
| CTgoodjobs modeled invalid item payload | Roll back and mark only that listing failed; record progress and continue |
| CTgoodjobs Job has a multi-location value longer than 255 characters | Preserve the full ordered raw evidence and full joined `Job.location`; do not write Company.location |
| CTgoodjobs oversized Job location while deployed column is still finite | Record safe `persistence_value_too_long`, fail only the item, and continue later snapshot targets |
| CTgoodjobs storage introspection fails or the deployed location column is absent | Stop the run as an unknown persistence/infrastructure failure |

### 5. Good / Base / Bad Cases

- **Good:** A detail request finishes after Cancel, the next adapter gate raises,
  the worker exits, remaining owned `running` rows return to `pending`, and the
  UI changes from Cancelling to Cancelled.
- **Base:** A queued task has no execution row and reaches Cancelled immediately
  with ordered request/acknowledgement events.
- **Bad:** The API writes Cancelled immediately while Playwright continues
  fetching more jobs.
- **Bad:** Startup recovery trusts a reused PID or acknowledges an access-denied
  PID as already exited.

### 6. Tests Required

- State tests cover cancellable/manual-only inputs and protected late
  transitions.
- Dispatch tests cover queued/no-execution acknowledgement, repeated Cancel,
  scheduled rejection, and request-before-acknowledgement event order.
- Launcher tests cover generation command propagation, create-time/command PID
  validation, unverifiable identity, 30-second escalation, process-tree kill,
  launch cleanup, and restart recovery.
- Token/adapter tests assert one-second-or-shorter sleep slices and zero
  navigation/fetch calls after the final cancellation gate for JobsDB,
  CTGoodJobs, and OfferToday.
- Cancellation-service tests assert listing partialness, settled-output
  preservation, owned-running detail recovery, and idempotent events.
- Cross-source detail tests assert JobsDB and CTGoodJobs use the current ingest
  projection interface, stop after the first unexpected persistence failure,
  and preserve modeled target-content behavior.
- Snapshot/frontend tests assert Cancelling filtering/polling, disabled repeated
  Cancel, no terminal Cancel, and no Resume for cancelled tasks.

### 7. Wrong vs Correct

#### Wrong

```python
crawl_job.status = "cancelled"
db.commit()
process.terminate()  # PID alone; exit not confirmed
```

This publishes a false terminal state and can signal an unrelated reused PID.

#### Correct

```python
crawl_job.status = "cancelling"
append_event("crawl.cancel_requested")
request_stop(execution_generation)

if validated_owned_process_has_exited(execution_generation):
    acknowledge_cancelled(crawl_job_id, execution_generation)
```

The durable generation owns process validation, restart recovery, and the only
transition that may publish `crawl.cancelled`.

---

## Scenario: JobsDB unstable listing-count pagination

### 1. Scope / Trigger

Use this contract when a JobsDB listing Run probes page 1, derives reverse
pagination from `totalCount`, and later encounters empty computed tail pages.
JobsDB may return different `totalCount` values for otherwise identical
requests, so one response's calculated last page is not authoritative evidence
that the classification is empty.

### 2. Signatures

```python
CategoryListScraper.scrape_category(
    classification_id,
    max_pages,
    on_progress,
    page_sink,
    on_page_start,
) -> dict[str, Any]

JobsDBListingPaginationInconsistentError(
    *, total_count: int, total_pages: int, pages_scraped: int
)
```

### 3. Contracts

- The page-1 probe counts against the reviewed request budget.
- When `reuse_first_page=true`, its response is staged exactly once and is
  never fetched again. If an empty tail stops the reverse walk before page 1,
  stage the cached response after the stop without another budget claim.
- Stable multi-page runs retain tail-to-page-1 order and remain bounded by the
  frozen page depth and aggregate run page cap.
- `totalCount == 0` is authoritative empty scope and completes with no staged
  pages.
- `totalCount > 0` with zero observed Job identities after the cached page-1
  boundary is processed raises `JobsDBListingPaginationInconsistentError`.
  The executor records `crawl.failed`; it must not emit `listing_completed` or
  enter `manual_action_required`.
- The error contains only bounded counts. Never persist response bodies or an
  unbounded identity collection.

### 4. Validation & Error Matrix

| Condition | Required result |
|---|---|
| Stable non-empty pages | Stage each page once in reverse order; complete normally |
| Computed tail becomes empty, cached page 1 has Jobs | Stage empty evidence, then cached page 1 exactly once; continue normally |
| `totalCount > 0`, every observed page has zero identities | Raise pagination inconsistency; Crawl Job becomes `failed` |
| `totalCount == 0` | Successful no-work completion; zero staged pages |
| Page contains only published Job identities | Successful completion with non-zero raw/skipped metrics and zero new rows |
| Cached page 1 is reused | Consume no second page-1 request-budget claim |

### 5. Good / Base / Bad Cases

- **Good:** page 1 advertises 123 pages and contains Jobs; pages 123 and 122
  are empty after the Source count drifts. The run records those empty pages,
  stages cached page 1 once, and retains truthful identity metrics.
- **Base:** page 1 returns `totalCount=0`; the run completes successfully with
  no listing page or Job evidence.
- **Bad:** the reverse walk breaks on an empty tail and reports completed with
  collected, staged, and skipped counts all zero.

### 6. Tests Required

- `backend/tests/test_jobsdb_listing_pagination.py` reproduces request order
  `[1, 123, 122]`, proves cached page 1 is staged exactly once, verifies bounded
  inconsistency failure, preserves authoritative empty completion, and proves
  the outer executor records failed rather than completed.
- Existing request-budget and IP-recovery tests must continue to prove cached
  page-1 reuse, frozen caps, committed-prefix preservation, and no duplicate
  requests.

### 7. Wrong vs Correct

```python
# Wrong: an empty unstable tail discards the already-confirmed first page.
if not jobs:
    break
return completed(job_ids=[])

# Correct: preserve the cached boundary, then reject contradictory zero work.
if reverse_walk_stopped_before_page_one:
    stage(cached_first_page)
if total_count > 0 and not job_ids:
    raise JobsDBListingPaginationInconsistentError(...)
```
