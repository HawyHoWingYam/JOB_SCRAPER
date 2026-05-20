# Crawl Manual-Action Resume Design

> Last updated: 2026-05-20
> Scope: durable crawl jobs, progress API, frontend scrape progress panel

## Goal

Turn anti-bot human-verification interruptions into a first-class recoverable crawl state instead of a generic failure.

The system should tell the operator exactly when manual work is required, what URL/profile to use, and how to resume the same crawl job after the challenge is cleared.

## Problem

CTGoodJobs headed crawls can be blocked mid-run by human-verification interstitials on registry, category, or detail pages. Today the worker collapses those interruptions into a generic `failed` state.

That behavior has three problems:

1. The operator cannot tell whether a crawl truly failed or just needs manual intervention.
2. The system loses the distinction between recoverable anti-bot interruptions and unrecoverable runtime errors.
3. The operator must infer the next step from logs instead of getting explicit UI guidance.

## Non-Goals

- No automatic retry loop in the first version.
- No backend-driven browser launch in the first version.
- No multi-job batch resume in the first version.
- No source integration beyond CTGoodJobs in the first version, although the framework must be reusable.

## Recommended Approach

Introduce a new durable crawl-job status, `manual_action_required`, plus a structured `manual_action` payload carried through crawl-job events, progress snapshots, and the scrape progress UI.

When a recoverable anti-bot interstitial is detected, the worker should stop treating it as a generic failure. Instead it should persist a resumable state that tells the operator:

- which source was blocked
- which stage was blocked
- which URL should be opened manually
- which browser profile/channel should be used
- whether the crawl can be resumed in place

The operator then clears the challenge manually and clicks `Resume`. The same `crawl_job_id` is re-queued and continues from a bounded checkpoint rather than starting over as a brand-new job.

## User Experience

### Normal automatic states

- `queued`
- `dispatching`
- `running`
- `completed`

These mean the system is handling the crawl without operator involvement.

### Actionable manual state

- `manual_action_required`

This means the crawl is paused and waiting on an operator action. It is not a generic failure and should remain visible in the progress panel until the operator resumes or cancels it.

### Operator flow

1. Crawl runs normally.
2. Worker detects a recoverable human-verification interstitial.
3. Progress panel switches the crawl card to `Manual Action Required`.
4. Card shows the blocked URL, browser profile path, browser channel, and short instructions.
5. Operator opens the listed URL with the listed profile, clears the challenge, closes the manual browser window, and clicks `Resume`.
6. The same crawl job re-enters `dispatching` then `running`.

## Runtime State Model

### Crawl job statuses

Add:

- `manual_action_required`

Keep existing terminal statuses:

- `completed`
- `failed`
- `cancelled`

### Crawl job event types

Add:

- `crawl.manual_action_required`
- `crawl.resume_requested`

### Status transitions

- `queued -> dispatching -> running`
- `running -> manual_action_required`
- `manual_action_required -> dispatching`
- `dispatching -> running`
- `running -> completed`
- `running -> failed`
- `manual_action_required -> cancelled`

If a resumed crawl hits another recoverable interstitial, it loops back to `manual_action_required` instead of becoming `failed`.

## Backend Design

### 1. Structured recoverable exception

Add a dedicated exception type for recoverable anti-bot interruptions, for example `ManualActionRequiredError`.

Required fields:

- `source_site`
- `stage`
- `blocked_url`
- `referer`
- `message`
- `resume_context`

Optional fields:

- `action_type` defaulting to `human_verification`
- `screenshot_path` for a future diagnostics extension
- `instructions` override if a source needs special handling

This exception becomes the boundary between scraper/runtime detection and control-plane recovery behavior.

### 2. Worker behavior

`CrawlWorkerService` should catch `ManualActionRequiredError` before the generic `except Exception` branch.

On catch:

- publish progress event `crawl.manual_action_required`
- persist runtime event with status `manual_action_required`
- store `error_message` as a concise operator-facing summary
- store a structured `manual_action` payload in the event payload
- do not mark the crawl job as `failed`
- ack the stream message so the worker does not spin on the same event

The persisted payload should include:

- `action_type`
- `source_site`
- `stage`
- `blocked_url`
- `referer`
- `crawl_mode`
- `browser_channel`
- `browser_profile_path`
- `resume_supported`
- `message`
- `instructions`
- `resume_context`

### 3. Resume API

Add:

- `POST /api/v1/crawl-jobs/{crawl_job_id}/resume`

Validation rules:

- crawl job must exist
- crawl job status must be `manual_action_required`
- latest actionable event must be `crawl.manual_action_required`
- latest event payload must contain `resume_supported: true`

Resume behavior:

1. Append `crawl.resume_requested`
2. Reset crawl job status to `dispatching`
3. Clear `completed_at`
4. Clear `error_message`
5. Re-enqueue a new `crawl.requested` outbox event for the same `crawl_job_id`
6. Carry forward the original `request_payload`
7. Add:
   - `is_resume: true`
   - `resume_context`

No new crawl job is created.

### 4. Dispatch service changes

`CrawlJobDispatchService` should gain a dedicated resume path rather than reusing `dispatch_manual_crawl_job`.

Reason:

- manual dispatch creates a new crawl job
- resume must preserve the existing `crawl_job_id`, event history, and schedule linkage

Recommended service entry point:

- `resume_crawl_job(db, crawl_job_id, requested_by="api")`

### 5. Progress API changes

`_build_progress_snapshot` should surface:

- `status="manual_action_required"`
- `manual_action={...}`

`_is_snapshot_active` must treat `manual_action_required` as actionable and keep it visible.

SSE idle shutdown must not close while any crawl job is in `manual_action_required`, because the operator is still in the middle of a recoverable workflow.

### 6. Startup recovery changes

`StartupRecoveryService` must not convert `manual_action_required` crawl jobs into `failed`.

Recovery should continue to treat only:

- `dispatching`
- `running`

as interrupted in-flight work.

## Resume Semantics

### Listing phase

Listing resume should continue from the blocked page, not restart the entire listing crawl from page 1.

First-version `resume_context` for listing should contain:

- `crawl_phase="listing"`
- `category_id`
- `category_index`
- `page`
- `page_direction`

Why this is sufficient:

- listing-stage rows are already durably staged
- listing upserts are already idempotent by `(crawl_job_id, source_site, source_job_id)`
- replaying the blocked page is acceptable because duplicates collapse into upserts

The spider should accept optional listing resume hints and start the active category from the blocked page.

### Detail phase

Detail resume should preserve the interrupted target as recoverable work instead of collapsing it into ordinary failure.

First-version change:

- extend `crawl_job_listings.detail_status` with `manual_action_required`

When a detail target hits a recoverable interstitial:

- mark the row as `manual_action_required`
- preserve `last_detail_crawl_job_id`
- persist the detail error message

When a resumed detail crawl loads candidates, priority order should be:

1. `manual_action_required`
2. `pending`

and never re-process:

- `completed`

This keeps the blocked detail target at the front of the resume path while preserving current durable staging behavior.

## Frontend Design

### Progress card state

`ScrapeProgressPanel` should render a dedicated `manual_action_required` presentation instead of mapping it onto `failed`.

Status badge:

- `Manual Action Required`

Body content:

- source label
- crawl mode label
- blocked stage
- blocked URL
- browser profile path
- browser channel
- concise step list

### Operator actions

Required buttons:

- `Resume`
- `Cancel`
- `Copy URL`
- `Copy Profile Path`

Recommended first-version addition:

- `Copy PowerShell Command`

Generated command example:

```powershell
& 'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe' --user-data-dir='C:\...\backend\.host_browser_profiles\msedge' --new-window 'https://jobs.ctgoodjobs.hk/jobs/jobs-in-information-technology?page=52'
```

### Copy and messaging

Card instructions should be short and deterministic:

1. Open Edge using the listed profile.
2. Visit the blocked URL and complete the verification challenge.
3. Close the manual browser window.
4. Return here and click `Resume`.

### Panel lifetime

The progress panel must remain open for `manual_action_required` crawls and must not auto-dismiss as if the system were idle.

## CTGoodJobs First-Version Integration

The shared framework should be source-agnostic, but the first implementation should only wire it into CTGoodJobs.

First-version detection sources:

- headed category-page fetches
- headed registry fetches
- headed detail-page fetches

The existing CTGoodJobs interstitial detection logic should raise `ManualActionRequiredError` with structured context instead of returning a generic fetch error when the site is blocked by human verification.

The same framework can be adopted by JobsDB and any other source that needs recoverable operator intervention after the CTGoodJobs rollout proves stable.

## Data Model Changes

### Crawl jobs

No new table is required in the first version.

The existing `crawl_jobs.status`, `crawl_jobs.error_message`, and event payload history are sufficient if `manual_action` is stored in event payloads.

### Crawl job listings

Expand allowed `detail_status` values to include:

- `manual_action_required`

No new columns are required in the first version.

## Error Handling Rules

Treat these as recoverable manual-action conditions:

- known anti-bot human-verification interstitials
- recoverable source-specific browser gate pages that require operator action

Treat these as ordinary failures:

- unsupported source
- parser crashes
- database errors
- malformed resume state
- missing listing metadata that cannot be reconstructed

If resume state is invalid or missing, the resume API should reject the request with `409 Conflict` rather than silently creating a new crawl.

## Testing Strategy

### Backend tests

- worker converts `ManualActionRequiredError` into `manual_action_required`
- worker emits `crawl.manual_action_required` with structured payload
- progress snapshot includes `manual_action`
- `_is_snapshot_active` keeps `manual_action_required` jobs visible
- SSE idle logic does not close while manual action is pending
- resume API rejects invalid states
- resume API requeues the same `crawl_job_id`
- CTGoodJobs listing resume starts from the blocked page
- CTGoodJobs detail resume prioritizes `manual_action_required` staged rows
- startup recovery leaves `manual_action_required` untouched

### Frontend tests

- progress panel renders manual-action card correctly
- structured instructions appear without parsing the error string
- `Resume` button calls resume endpoint
- `Cancel` button still works
- copy buttons use the structured payload
- panel stays visible while manual action is pending

## Rollout Plan

### Phase 1

- add shared status, event, API, and UI support
- wire CTGoodJobs headed path into recoverable manual-action flow

### Phase 2

- add helper command generation and stronger operator guidance
- add JobsDB support using the same framework if needed

### Phase 3

- optionally add preflight session verification as a separate optimization, not as a replacement for runtime manual-action handling

## Risks

### Risk: resume context too weak

Mitigation:

- keep first-version resume context small and explicit
- lean on existing durable staging and upsert behavior
- cover listing and detail resume with focused tests

### Risk: progress panel still auto-hides

Mitigation:

- treat `manual_action_required` as actionable in both snapshot filtering and SSE idle logic

### Risk: manual-action state becomes a dumping ground for normal errors

Mitigation:

- require a dedicated exception type
- keep generic `Exception` handling mapped to ordinary failure

## Recommendation

Implement the shared `manual_action_required + Resume` framework now, but limit first-version source integration to CTGoodJobs headed crawls.

That gives the operator a durable, explicit workflow for anti-bot interruptions without adding speculative automation or broad new source complexity.
