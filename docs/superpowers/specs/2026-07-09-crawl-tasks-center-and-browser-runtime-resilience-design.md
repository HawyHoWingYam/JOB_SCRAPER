# Crawl Tasks Center and Browser Runtime Resilience Design

> Date: 2026-07-09
> Status: Approved for planning

## Objective

Ship a durable crawl-operations surface that separates live progress from historical task management, while also removing the container-side headed-browser dependency on Microsoft Edge so headed crawl jobs stop failing with missing-browser errors.

## Why This Iteration Exists

Two operator problems are colliding today:

1. Container-side headed crawl flows can fail immediately because the runtime is configured for `msedge`, but the Docker image only guarantees Playwright browsers, not branded Microsoft Edge binaries.
2. The current `Scraping Progress` panel is trying to do two jobs at once: live stream monitoring and task history. That makes short-lived failures easy to miss and blocks the product from supporting long-lived history, pagination, and filters cleanly.

The approved direction is to stop stretching the live progress panel into a task-history tool. Instead, the product should have one dedicated task center for running, completed, failed, cancelled, stale, and manual-action work across the full retained history.

## Approved Product Decisions

- Add a new Sidebar entry: `Crawl Tasks`.
- Remove the task-list area from the current `Scraping Progress` panel.
- Make `Crawl Tasks` the single task-list surface for running, expired, completed, failed, cancelled, backlog, and manual-action work.
- Default the new page to all history, ordered by most recently updated.
- First-iteration filters are limited to:
  - `status`
  - `source site`
  - `crawl mode`
  - `time range`
- The first iteration uses `10` tasks per page with pagination.
- The new page refreshes automatically in a controlled polling model instead of binding the full historical list to SSE.

## Scope

### In Scope

- New frontend `Crawl Tasks` page and Sidebar navigation entry.
- Removal of task rows from the current `Scraping Progress` panel.
- A paginated backend task-list endpoint over durable crawl-job history.
- First-iteration filters for status, source site, crawl mode, and time range.
- Reuse of existing crawl-job detail, event, resume, cancel, and manual-action flows inside the new page.
- Refactoring shared crawl-task snapshot logic so the progress API and task-history API derive consistent task summaries.
- Container-safe headed browser launch behavior for CTGoodJobs, JobsDB, and OfferToday fresh-profile flows.
- Docker defaults and error reporting updates needed to stop missing-`msedge` crashes from surfacing as opaque Playwright failures.

### Out of Scope

- A full route hierarchy for individual crawl-task pages.
- New database tables or a separate archival system.
- New filters beyond the approved first set.
- Replacing the existing progress SSE stream with a general-purpose live query system.
- Reworking host-side manual-action helper flows that intentionally target real installed browsers on Windows.

## Success Criteria

An operator should be able to:

- Open `Crawl Tasks` from the main Sidebar and see all crawl jobs, newest first.
- Filter the list by status, source, crawl mode, and time range without losing pagination stability.
- Page through results `10` at a time.
- Inspect running and failed tasks without relying on the live progress panel.
- Continue using resume, cancel, and manual-action workflows from the new task center.
- Run a headed CTGoodJobs or JobsDB crawl inside Docker without failing just because `msedge` is absent.
- Read a normalized browser-launch failure message when the runtime still cannot launch, instead of digging through a raw Playwright traceback.

## Design Overview

The product will split crawl observability into two layers:

- `Scraping Progress` remains a live-status shell for stream connection, recovery, and quick health awareness.
- `Crawl Tasks` becomes the durable operator workspace for task discovery, review, filtering, and action.

The backend mirrors that split:

- `/scrape/progress` stays optimized for live work and recovery behavior.
- A new paginated crawl-task query path serves durable history from `crawl_jobs` plus derived snapshot metadata.

The browser-launch fix follows the same principle: preserve explicit operator intent where the runtime is host-specific, but remove avoidable container assumptions where the runtime is automation-only.

## Frontend Design

### Navigation and Route Model

- Add a new Sidebar item labeled `Crawl Tasks`.
- Use the existing hash-based navigation model with a new view key such as `crawl-tasks`.
- Keep `Scheduler` focused on schedule creation, manual runs, and operational controls.

### `Scraping Progress` Panel After the Change

The panel should no longer render per-task sections such as `Needs Attention`, `Running or Queued`, `Backlog Follow-up`, or `Recent Terminal`.

It should instead become a compact live-status surface that can show:

- stream connection state
- recovery state when reconnecting after a direct override
- a short summary of whether live crawl work is present
- a direct `Open Crawl Tasks` command

This keeps the panel useful without turning it into a second task list.

### `Crawl Tasks` Page Layout

The new page should look like a dense operations view rather than a card grid.

Recommended structure:

1. Page header
   - title
   - short operator summary
   - refresh control
   - last refreshed timestamp

2. Filter row
   - status select
   - source-site select
   - crawl-mode select
   - time-range select

3. Results area
   - total count
   - paginated task list
   - `10` rows per page

4. Task detail surface
   - expand inline or open a detail pane beside/below the list
   - show task metrics, timing, error state, manual-action payload, and links/actions for deeper inspection

### Task Row Content

Each row should expose enough information for scanning without opening the detail pane:

- effective status badge
- source site
- crawl mode
- crawl phase or scope hint
- queued / started / updated timestamps
- short metrics summary
- abbreviated error or manual-action reason when applicable

The row should favor concise structured fields over prose.

### Detail Interaction

The first iteration should reuse existing crawl-job interaction paths instead of inventing a parallel action model. The detail surface should be able to surface:

- base crawl-job metadata
- the derived progress snapshot
- latest error / manual-action payload
- event history entry point
- resume
- cancel
- manual browser open / attach status / close profile windows where supported

### Refresh Model

For stability, the page should use controlled polling rather than a full-page SSE feed.

Recommended behavior:

- always allow manual refresh
- when the page is visible, auto-refresh every `10s`
- if there are no active or actionable tasks in the current filtered result set, the UI may back off or simply keep the same `10s` cadence if that proves simpler and stable

The critical constraint is that the full historical list must not depend on the progress SSE stream to stay correct.

## Backend Design

### Durable Task Query API

Add a new paginated crawl-task endpoint under the existing crawl-job API family. A representative shape is:

- `GET /api/v1/crawl-jobs/tasks`

Required query parameters and defaults:

- `page=1`
- `page_size=10`
- `status` optional
- `source_site` optional
- `crawl_mode` optional
- `time_range=all`

The response should include:

- paginated list items
- total count
- current page
- page size
- filter echo
- refresh timestamp

### Filter Semantics

#### Status

The first iteration should filter on persisted crawl-job lifecycle statuses because they are durable and SQL-friendly:

- `queued`
- `dispatching`
- `running`
- `manual_action_required`
- `completed`
- `failed`
- `cancelled`

Derived display states such as `ai_running` or `completed_with_ai_failures` remain presentation details on top of the persisted status rather than separate first-iteration filter buckets.

#### Source Site

Filter directly on `crawl_jobs.source_site`.

#### Crawl Mode

The filter must be source-aware. The effective mode is derived from `request_payload.crawl_mode` when present, otherwise from the source default. The backend should enforce that logic server-side so pagination remains correct and no page is built from post-pagination Python filtering.

#### Time Range

Time range applies to `updated_at`, with `all` as the default. First-iteration options should be constrained and explicit, for example:

- `all`
- `24h`
- `7d`
- `30d`

### Shared Snapshot Builder

The new task list and the existing progress API should not maintain separate status-derivation logic.

Extract the snapshot-construction and derived-status helpers from the current progress route into a shared service that can:

- build a frontend-facing crawl-task snapshot for one crawl job
- batch-build snapshots for a set of crawl jobs
- preserve current logic for operator state, metric scope, AI completion overlays, backlog overlays, and timing fields

This shared service becomes the source of truth for:

- `/scrape/progress`
- `/crawl-jobs/tasks`
- any future crawl-task detail summary surface

### Reuse of Existing Detail APIs

The new page does not need a bespoke full-detail endpoint in the first iteration if the existing APIs are sufficient.

The task list can be served by the new paginated endpoint, while deeper inspection can continue to use:

- existing single crawl-job fetch
- existing crawl-job events fetch
- existing resume / cancel / manual-action helper interactions

If the first iteration needs a thin detail-summary endpoint for frontend simplicity, it should wrap existing data rather than invent a second persistence model.

### Progress API Role After the Split

`/scrape/progress` should remain live-only. It is no longer responsible for making failed tasks visible for hours or days.

That means:

- the historical retention requirement moves to the new durable task query path
- the progress stream can stay focused on active, actionable, and short-lived recovery use cases
- any terminal-window logic can remain short or be simplified later without violating the product requirement for durable failure visibility

## Browser Runtime Resilience Design

### Targeted Runtime Fix

The missing-`msedge` problem affects container-side fresh-profile launches in:

- CTGoodJobs browser page scraping
- JobsDB headed browser detail scraping
- OfferToday headed browser runtime

These flows should stop assuming a branded browser binary exists.

### Launch Resolution Rules

For container-side automation launches:

1. If `executable_path` is explicitly configured, use it as-is.
2. Otherwise try the configured browser channel.
3. If the configured branded Chromium channel is unavailable and the failure is specifically a missing-browser-distribution case, retry with Playwright's bundled `chromium` channel.
4. Log both the requested browser target and the fallback target.
5. If fallback also fails, raise a normalized, short operator-facing error message.

This fallback should apply only to automation-owned browser launches. It should not silently rewrite the host manual-action helper, which is intentionally tied to real installed Edge/Chrome processes on Windows.

### Default Container Configuration

In addition to runtime fallback, Docker defaults should stop pointing at `msedge` by default where the container is expected to own the browser runtime.

That means the container configuration should prefer `chromium` defaults for headed automation profiles so the steady-state path does not emit avoidable fallback noise.

### Error Normalization

When browser launch fails, the crawl job should capture a concise failure summary that tells the operator what failed in configuration terms, for example:

- requested browser target
- resolved browser target
- whether fallback was attempted
- short remediation hint

The goal is to stop forcing operators to interpret raw Playwright stack traces to understand a missing browser binary.

## Testing and Verification Requirements

### Backend

- unit tests for the browser-launch resolver
  - explicit executable path
  - branded channel success
  - branded channel missing and successful `chromium` fallback
  - branded channel missing and fallback failure
- progress/task snapshot tests proving the shared builder preserves current status semantics
- task-list endpoint tests covering:
  - default sort
  - pagination
  - status filter
  - source-site filter
  - crawl-mode filter
  - time-range filter

### Frontend

- App and Sidebar tests for the new `Crawl Tasks` route
- `ScrapeProgressPanel` tests proving task sections are removed and the panel still supports live status / reconnect / open-task-center behavior
- new page tests for:
  - empty state
  - filter interactions
  - pagination
  - refresh behavior
  - detail-pane rendering

### Manual Verification

- start Docker services and confirm headed CTGoodJobs / JobsDB fresh-profile launches no longer fail solely because `msedge` is missing
- verify a failed crawl job remains discoverable through `Crawl Tasks` long after the live progress panel would have dropped it
- verify running jobs appear in `Crawl Tasks` during auto-refresh and can still be resumed/cancelled where appropriate
- verify the `Scraping Progress` panel no longer shows duplicated per-task history

## Risks and Mitigations

### Risk: Duplicated status semantics across APIs

Mitigation: extract a shared crawl-task snapshot service before building the new task endpoint.

### Risk: Pagination becomes unstable when filtering by crawl mode

Mitigation: keep crawl-mode filtering server-side with source-aware resolution logic rather than filtering after pagination in the frontend.

### Risk: The new page and old progress panel diverge in action behavior

Mitigation: move task actions into reusable task-detail helpers instead of re-implementing resume/cancel/manual-action flows twice.

### Risk: Browser fallback masks real environment errors

Mitigation: only retry on the known missing-browser-distribution failure case, and log the original target plus fallback result explicitly.

## Rollout Notes

- No new persistence model is required for the first iteration.
- Historical visibility should come from durable crawl-job rows, not longer-lived SSE snapshots.
- The design intentionally favors stable polling and paginated history over a more ambitious live-streamed task center.
