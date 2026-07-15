# Implementation plan

## 1. Build the recovery component

- Add `frontend/src/components/scraper/ManualActionRecoveryPanel.jsx`.
- Normalize capability defaults using the existing constants from
  `crawlTaskActions.js`.
- Implement independent helper/reuse connectivity state and a pure derived
  recommended-step calculation.
- Implement clipboard command copy, helper polling with cleanup, initial reuse
  discovery, explicit browser opening, manual reuse recheck, explicit reuse
  resume, and secondary fresh-profile resume.
- Add the collapsed diagnostic section and confirmed profile cleanup.

## 2. Integrate Task Detail safely

- Replace the current inline helper note/manual-action button cluster in
  `CrawlTasksPage.jsx` with the recovery component.
- Remove helper state and imports that move into the component.
- Preserve generic non-manual resume behavior.
- Move cancellation to a visually separate danger section and gate it with a
  crawl-job-ID confirmation.
- Keep task metadata, payloads, events, notices, and refresh behavior intact.

## 3. Style the workflow

- Extend `CrawlTasksPage.css` with scoped recovery-card, step, primary/secondary,
  advanced, diagnostic, and danger styles using existing design tokens.
- Verify wrapping and stacking in the narrow detail column and at the existing
  800px breakpoint.

## 4. Update automated coverage

- Update `CrawlTasksPage.test.jsx` fixtures and assertions for the guided flow.
- Cover helper offline -> command copy -> automatic health recovery -> explicit
  browser open -> connected-but-not-verified wording -> explicit resume.
- Assert that browser opening and resume are not triggered by polling alone.
- Cover fresh fallback availability/warning, advanced disclosure, cleanup and
  cancel confirmations, and a manual-action task without reuse support.
- Use fake timers only around the bounded polling assertions and restore them in
  test cleanup.

## 5. Validation gates

Run from `frontend/`:

1. `npm test -- --run src/components/scraper/CrawlTasksPage.test.jsx`
2. `npm run lint`
3. `npm run build`
4. `npm test`

Then inspect `git diff --check` and the scoped diff. If a local frontend runtime
is available, perform a browser smoke of helper-offline and helper-online Task
Detail states without invoking resume on a production crawl.

## Risk and rollback points

- Clipboard APIs vary by browser context; failure must remain actionable and
  must not start polling as if copy succeeded.
- Polling effects can leak or act on a newly selected task; cleanup on task ID
  change is a required review gate.
- Existing files are already modified in the worktree. Preserve unrelated user
  changes and keep this task's edits scoped to the component, Task Detail CSS,
  tests, and Trellis artifacts.
- No backend contract changes are permitted without returning to planning.
