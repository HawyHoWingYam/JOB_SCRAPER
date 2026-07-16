# Design: JobsDB reusable-browser recovery

## Design Summary

Repair the existing JobsDB browser adapter at its current seam and add durable,
event-derived recovery-attempt feedback to the shared Crawl Tasks detail panel.
The backend change is deliberately source-local: JobsDB will use the same
configured-host resolver already used by CTGoodJobs and OfferToday, without
extracting a new cross-source attach module. The frontend will read the existing
crawl event stream rather than widening the crawl-task snapshot schema.

## Backend Architecture

### Existing seam

`resolve_manual_action_cdp_connect_host(configured_host)` in
`backend/app/scraper/manual_action.py` already hides Docker-hostname resolution
from browser adapters. CTGoodJobs and OfferToday are existing adapters at this
seam. JobsDB currently bypasses it by connecting to container localhost.

`JobsDBBrowserDetailScraper._attach_to_live_browser()` will:

1. Resolve the live browser session by normalized profile path as it does now.
2. Select `settings.manual_action_cdp_host` with
   `settings.manual_action_helper_host` as fallback.
3. Resolve that configured host through
   `resolve_manual_action_cdp_connect_host(...)`.
4. Connect to `http://<resolved-host>:<session.debug_port>`.
5. Include `cdp_host` and `cdp_connect_host` in attempt, failure, and success
   structured log context.

The method will retain the current error interface:

- missing registry session/debug port -> `reuse_open_browser_unavailable`
- CDP exception -> `reuse_open_browser_unavailable`
- attached browser without a context -> `reuse_open_browser_unavailable`
- successful context attach -> reuse a page and continue the same detail scope

No cookies, page bodies, CDP response contents, or unbounded exception payloads
will be added to durable events.

### Why no new shared module

The resolver is already the useful seam. A new module wrapping the entire attach
flow would enlarge the urgent change across three working adapters, create a
migration problem, and require broader live validation. The deletion test does
not justify that work here: removing the existing resolver would immediately
re-spread host-resolution complexity, while the remaining adapter-specific
context ownership and error messages are intentionally source-local.

## Frontend Data Flow

### Event source

The selected task will load its existing event endpoint:

```text
GET /api/v1/crawl-jobs/{crawl_job_id}/events?limit=<bounded limit>
```

Events are ordered by `sequence_no` and already expose `event_type`, `payload`,
and `created_at`. No new backend snapshot field is needed.

The page will refresh selected-task events:

- when the selected task changes;
- after a recovery action refreshes the task;
- with the existing selected-task refresh cadence while the page remains open.

Event-fetch failure must not remove the recovery controls. It should degrade to
the current task/manual-action view plus a bounded feedback-unavailable message.

### Recovery-attempt projection

A pure frontend helper will derive the latest recovery attempt:

1. Find the newest `crawl.resume_requested` event by `sequence_no`.
2. Capture its strategy, timestamp, and sequence.
3. Find the first later event that resolves the attempt for operator display:
   - `crawl.manual_action_required` -> returned to manual action; show its new
     stage/classification/message.
   - a later running/completed/failed/cancelled task state supersedes the attempt
     in the normal task details.
4. If no later outcome exists, show the attempt as accepted/in progress.

Only the latest attempt is shown inline. Full history remains behind View Events.
The display should include a stable test id and accessible status text.

### Interaction contract

- Browser/helper connectivity never resumes a task automatically.
- Clicking Resume Task with Open Browser immediately enters local pending state.
- A successful POST displays an accepted message and refreshes task plus events.
- While the request is pending, both resume choices remain disabled.
- If the task rapidly returns to manual action, the panel displays the new event
  reason and timestamp instead of appearing unchanged.
- A resolved failure permits another explicit operator attempt; unresolved work
  does not generate automatic or repeated POSTs.

## Compatibility

- The resume endpoint and request body remain unchanged.
- Crawl-task snapshot schema remains unchanged.
- Existing CTGoodJobs and OfferToday browser recovery paths are untouched.
- Existing View Events behavior remains available.
- Historical tasks without a resume event simply omit recovery-attempt feedback.

## Operational Validation

After focused tests and Docker rebuild:

1. Confirm helper health and the JobsDB browser connection in Crawl Tasks.
2. Confirm JobsDB is accessible in the open browser after the operator's network
   change.
3. Explicitly resume task `37cb2cc5-16bc-45d2-bd1c-4b79ba84f464` using the open
   browser.
4. Require `manual_action_attach_success` in backend logs.
5. Require the task to process at least one of the preserved 3,805 targets, or
   stop with new positive access evidence that identifies the remaining blocker.

## Rollback

- Backend rollback restores the former JobsDB attach method; no data migration is
  involved.
- Frontend rollback removes event-derived feedback; resume API behavior is
  unchanged.
- If live validation fails, leave the task paused and retain its event history;
  do not cancel or recreate the 3,805-target task merely to obtain a clean run.
