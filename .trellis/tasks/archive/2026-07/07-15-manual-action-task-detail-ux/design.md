# Design: Guided manual-action recovery in Task Detail

## Boundary

This is a frontend-only change. The backend capability, health, helper-action,
reuse-status, resume, cleanup, and cancel contracts remain unchanged.

Add a dedicated `ManualActionRecoveryPanel` component under
`frontend/src/components/scraper/`. `CrawlTasksPage` continues to own task-list
loading, selection, metadata rendering, generic resume, event access, and crawl
cancellation. The panel owns manual-action recovery state and presentation.

## Component contract

`ManualActionRecoveryPanel` receives:

- `task`: the selected manual-action task snapshot.
- `capability`: runtime helper URL, health URL, start workdir, and start command.
- `onTaskChanged(reason)`: asks the parent to refresh task snapshots after a
  resume or other task-affecting action.

The panel imports existing functions from `crawlTaskActions.js`; it does not
duplicate HTTP or URL-building logic.

## State model

Keep two independent connectivity states:

- Helper: `checking | offline | online` plus diagnostic detail.
- Reusable browser: `unknown | checking | disconnected | connected`.

Derive the primary step rather than storing it separately:

1. Helper is not online -> `start_helper`.
2. Helper online and browser not connected -> `open_browser`.
3. Browser connected -> `resume_with_open_browser`.

`connected` means only that the existing helper contract found a reachable live
browser session. The copy must tell the operator to finish login/challenge work
in that browser before explicitly resuming.

## Polling and side effects

- Check helper health when a reusable-browser-capable task is selected.
- Copy a PowerShell-friendly command assembled from the capability workdir and
  start command. After a successful clipboard write, poll helper health at a
  short fixed interval until it becomes online or the selected task changes.
- When helper health becomes online, check task-specific reuse status once so an
  already-open browser can be discovered.
- `Open Browser` is always an explicit click. After it succeeds, refresh reuse
  status and advance the display when the browser is reachable.
- Crawl resume is always an explicit click. No effect may call open/resume based
  solely on a polling result.
- Every interval/effect must be cancelled on task change and component unmount.

## Presentation

The recovery panel appears before the generic Task Detail metadata and contains:

- A compact three-step progress row for Helper, Browser, and Resume.
- A problem/next-action heading and one primary button.
- Contextual copy using the formatted task source.
- A visibly secondary fresh-profile fallback with consequence text.
- A collapsed native `details` section for raw diagnostics, manual status check,
  and profile cleanup.

Use existing color and spacing variables in `CrawlTasksPage.css`. Add responsive
rules so the step row and actions stack in the existing narrow detail column.

## Dangerous operations

- Use an explicit confirmation before `Close Profile Windows`; the message names
  the dedicated profile behavior.
- Keep `Cancel Crawl Job` in `CrawlTasksPage`, outside the recovery panel, in a
  danger section below task information. Confirm with the crawl-job ID before
  calling the existing cancellation API.

Native confirmation is sufficient for this scoped change and avoids introducing
a new modal system.

## Compatibility and failures

- `resume_supported=true` without reuse support renders a compact manual-action
  panel with the fresh-profile action but no helper workflow.
- Non-resumable manual actions render operator-review guidance and instructions.
- Clipboard, health, helper-action, reuse-status, and resume failures stay in the
  panel and preserve the currently valid next action.
- Helper transport failures demote helper state to offline. A disconnected reuse
  response does not imply helper failure.
- Generic non-manual resume remains in the parent unchanged.

## Rollback

The change is isolated to a new component plus Task Detail composition, styles,
and tests. Rollback removes the component and restores the previous inline action
block; no API or persisted-data rollback is required.
