# Restore Crawl Tasks recovery buttons

## Goal

Restore the guided manual-action recovery controls when a crawl task's latest
manual-action event declares that the task supports resume, so an operator who
has changed IP/network can continue the same crawl without losing completed
progress.

## Background

- GitHub issue: https://github.com/HawyHoWingYam/JOB_SCRAPER/issues/7
- Live task `88ff0eb8-5c27-4a24-bf61-0a917727a67a` is persisted as
  `manual_action_required` after an OfferToday `ip_blocked` detail outcome.
- Its latest `crawl.manual_action_required` event contains
  `resume_supported=true`, `reuse_open_browser_supported=true`, an Edge browser
  profile, and `preferred_resume_strategy=reuse_open_browser`.
- The Crawl Tasks snapshot for the same task returns `manual_action=null` and
  `manual_action_resolution=null`.
- `ManualActionRecoveryPanel` intentionally displays the guided buttons only
  from `task.manual_action.resume_supported` and
  `task.manual_action.reuse_open_browser_supported`; request-payload resume
  fields are not a capability contract.
- The host helper and the task's reusable Edge session are currently reachable.
- The previous manual-action UX task deliberately relied on normalized backend
  snapshots and retained an operator-review fallback for genuinely unsupported
  tasks. The present defect is therefore in the snapshot contract, not the
  panel's capability gate.

## Requirements

- **R1 — Event-derived capability:** A `manual_action_required` crawl-task
  snapshot must expose the normalized latest manual-action payload when the
  latest stored manual-action event is resumable, even when a later non-manual
  event is the job's overall latest event.
- **R2 — Honest gating:** The frontend must continue to hide recovery controls
  for tasks whose normalized manual action is genuinely non-resumable; do not
  infer support merely from `request_payload.resume_strategy`.
- **R3 — Source-correct metadata:** Normalization must preserve or derive the
  task's actual source/browser recovery metadata and must not inject JobsDB-only
  defaults into OfferToday snapshots.
- **R4 — Progress safety:** The fix must not create a new crawl, resume a crawl,
  open a browser, or mutate the selected production task during verification.
- **R5 — Compatibility:** Preserve existing Crawl Tasks filters, paging,
  metadata, event access, non-manual layouts, fresh-profile fallback, and guided
  helper/browser/resume workflow.
- **R6 — Regression protection:** Add a deterministic regression test where a
  resumable `crawl.manual_action_required` event is followed by another event;
  the task snapshot must still carry the normalized recovery capability.
- **R7 — Generic behavior:** Apply the event-derived projection rule to every
  crawl source and task that satisfies the normalized resumability contract;
  do not special-case OfferToday or a crawl-job ID.

## Acceptance Criteria

- [x] **AC1 (R1, R2, R7):** The focused regression test fails on the current code
      because the resumable event is not projected, then passes after the fix.
- [x] **AC2 (R1, R3):** The live snapshot for task `88ff0eb8-...` returns a
      non-null `manual_action` with `resume_supported=true`,
      `reuse_open_browser_supported=true`, and OfferToday/Edge recovery fields.
- [x] **AC3 (R2, R5):** Existing tests for unsupported/legacy manual actions and
      non-manual Task Detail behavior remain green.
- [x] **AC4 (R4):** Verification performs only reads/status checks against the
      live task; its status remains `manual_action_required` until the operator
      explicitly resumes it later.
- [x] **AC5 (R5):** The focused backend snapshot tests, focused frontend Crawl
      Tasks tests, frontend build, and scoped quality checks pass, with unrelated
      worktree changes left untouched.

## Out of Scope

- Automatically resuming the production crawl after this UI repair.
- Replacing the guided recovery panel or weakening its capability checks.
- Adding new browser/helper endpoints or redesigning manual-action persistence.
- Source-specific or crawl-job-ID-specific recovery exceptions.
- Fixing unrelated lint failures or dirty-worktree changes.
