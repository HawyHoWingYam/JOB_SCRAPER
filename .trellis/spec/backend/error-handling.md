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
- Synthetic responses are required for CTGoodJobs/JobsDB block tests. Do not
  deliberately ban the live public IP. Live OfferToday resume verification
  requires an actual operator IP change and explicit Resume.

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
