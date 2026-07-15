# Verification

## Acceptance evidence

- AC1-AC4: `CrawlTasksPage.test.jsx` covers helper offline, exact PowerShell
  clipboard content, automatic helper polling, no automatic browser/resume side
  effects, explicit browser opening, honest connected wording, explicit reuse
  resume, and the warned fresh-profile fallback.
- AC5: tests prove profile cleanup and crawl cancellation do not call their APIs
  until confirmation; browser smoke confirmed diagnostics are collapsed.
- AC6-AC7: tests cover a capability-driven OfferToday task, a JobsDB task without
  browser reuse, and existing non-manual metric/detail behavior.

## Commands

- Focused ESLint on `CrawlTasksPage.jsx`, `ManualActionRecoveryPanel.jsx`, and
  `CrawlTasksPage.test.jsx`: passed.
- `npm run build`: passed; 1,798 modules transformed.
- `npm test`: passed; 13 test files, 114 tests.
- `git diff --check`: passed.
- `npm run lint`: repository baseline failed with 16 errors and 3 warnings in
  unrelated files (`Dashboard.jsx`, `SkillTags.jsx`, AI files,
  `ScrapeProgressPanel.jsx`, and `AISettingsPage.jsx`). The task-scoped ESLint
  command is green; these unrelated files were not changed for this issue.

## Browser smoke

- Ran the current worktree through a temporary Vite server against the live
  local API and inspected the real OfferToday task
  `88ff0eb8-5c27-4a24-bf61-0a917727a67a` without invoking side effects.
- Confirmed the guided recovery panel, helper-offline primary action, warned
  fresh fallback, collapsed advanced disclosure, and separate danger zone.
- Stopped the temporary Vite process after inspection.

## Spec update decision

No shared `.trellis/spec/` update was made. This task changes no API or persisted
contract, and the active `00-bootstrap-guidelines` task currently owns the blank
frontend spec bootstrap. The durable behavioral contract remains in this task's
PRD/design plus regression tests rather than colliding with that task.

## GitHub

- Issue: https://github.com/HawyHoWingYam/JOB_SCRAPER/issues/6
- Work commit: `eedb732d feat(scraper): guide manual-action task recovery`.
- The closing comment includes the commit and command evidence.
