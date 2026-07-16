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
```

The only product continuation endpoint is explicit:

```http
POST /api/v1/crawl-jobs/{crawl_job_id}/resume
```

### 3. Contracts

#### Positive evidence boundary

| Source | `ip_blocked` evidence | Non-IP result |
|---|---|---|
| CTGoodJobs | HTTP 403/429 or explicit IP/rate-limit/access-block marker in bounded navigation evidence | Generic Cloudflare/human verification is `waf_challenge`; proxy/display/profile failures keep their own classes |
| JobsDB | HTTP 403/429 or explicit IP/rate-limit/access-block marker in listing/detail response evidence | Generic interstitial is `waf_challenge`; other HTTP/network/parser behavior remains transport/failure |
| OfferToday | Exact API code `-1000035` or verify URL query `code=-1000035` | Other verify URLs are `waf_challenge`; failed fetch on a normal URL is transient transport |

DNS, connection reset, timeout, malformed JSON/HTML, parser failure, and auth
failure must never become `ip_blocked` without separate positive evidence.
Classify IP evidence before generic WAF markers because a blocked response may
also render a challenge page. Never store or log the inspected response body.

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

### 4. Validation & Error Matrix

| Condition | Required result |
|---|---|
| HTTP 403/429 on CTGoodJobs/JobsDB | Typed `ip_blocked`; immediate manual action |
| Explicit IP/rate-limit marker on a 200 page | Typed `ip_blocked`; no generic challenge retry |
| Generic Cloudflare/human-verification page | `waf_challenge`, not IP |
| OfferToday exact code `-1000035` | Typed `ip_blocked`, code preserved, no transient retry |
| OfferToday other verify URL | `waf_challenge` |
| DNS/timeout/connection failure | Existing transient/failure behavior; never IP |
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
- **Bad:** The helper reports connected, so the frontend automatically resumes
  or allows repeated Resume clicks before the previous event has an outcome.

### 6. Tests Required

- `backend/tests/test_cross_source_ip_recovery.py` covers source-specific IP vs
  WAF/generic transport classification, immediate stop, committed page replay,
  same-task upsert behavior, compact/source-aware payloads, and completed-detail
  exclusion.
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
- `frontend/src/components/scraper/recoveryAttemptUtils.test.js` and
  `CrawlTasksPage.test.jsx` cover attempt ordering, durable returned outcome,
  local request pending state, and disabled repeated Resume actions while the
  event-derived attempt is unresolved.

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
  state evidence plus missing-field/body-text non-classification.
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
