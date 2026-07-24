# Recover stale JobsDB browser profiles

## Goal

Make JobsDB profile-lock and manual-action recovery actionable in container/headless environments, including safe stale-lock cleanup, isolated fresh profiles, and explicit frontend controls.

## User value

When a JobsDB task is blocked, the operator can tell whether the worker profile is safe to reset, open a verification browser when human action is needed, and resume the same task without losing completed detail targets.

## Confirmed evidence

- `backend/app/scraper/jobsdb_browser_detail_scraper.py:200-208` currently launches a persistent context against the configured shared profile with `headless=False`.
- `backend/app/scraper/jobsdb_browser_detail_scraper.py:373-388` maps launch failure to “Close all Edge windows using the automation profile…”, even when the profile is inside a container.
- `backend/app/services/crawl_job_dispatch_service.py:635-690` already accepts `fresh_profile` and `reuse_open_browser`; fresh profile is the API default and completed-target filtering is classification-driven at `:719-720`.
- The affected task used `/app/.host_browser_profiles/chromium`; the user had no visible desktop Edge to close.
- `frontend/src/components/scraper/ManualActionRecoveryPanel.jsx:297-567` already has helper/open/reuse/fresh controls, while `frontend/src/components/scraper/CrawlTaskDetails.jsx:46` submits one generic Resume action.

## Requirements

- P1. `fresh_profile` uses an isolated task/run-owned profile; a fixed profile is reserved for explicit `reuse_open_browser` verification flows.
- P2. A profile lock may be automatically cleaned only after the backend proves no matching browser process is alive and no live-browser registry session is reachable. If liveness is unknown, fail closed.
- P3. Reset is explicit and idempotent: temporary profiles may be deleted/recreated; fixed headed profiles retain cookies/login data and only stale lock markers plus registry state are cleared.
- P4. Normal headless execution remains browser-invisible, but a supported manual challenge may explicitly open a separate headed verification browser and then resume with `reuse_open_browser` for that recovery attempt.
- P5. If the Host Helper is unavailable, the task remains `manual_action_required`; the UI shows helper health/start instructions and never silently changes strategy.
- P6. Task Details exposes explicit open-browser, reuse, fresh-profile, and conditionally safe Reset actions rather than one ambiguous default Resume.
- P7. Resume/Reset preserve the same task scope and completed-target checkpoint. Each Resume performs at most one automatic stale-lock cleanup/retry; a second failure returns to `manual_action_required` with structured diagnostics.
- P8. Existing tasks are recovered through read/resume-time legacy normalization where scope/checkpoint data is trustworthy; no database migration is required. Unrecoverable historical records may direct the operator to create a new task.
- P9. Temporary profiles remain while a task is active or awaiting manual action, are cleaned at terminal outcome, and are eligible for lazy orphan cleanup on the next profile allocation after a default 24-hour TTL. Fixed reuse profiles are never task-owned for deletion.
- P10. Scope is JobsDB detail and shared recovery primitives only; other source behavior is out of scope.

## Acceptance criteria

- [ ] A stale or unavailable profile no longer leaves a resumable task with only the local-Edge instruction.
- [ ] With a proven-dead profile, Reset clears only the safe profile state and makes the same task resumable; with uncertain liveness, Reset is disabled and exposes the diagnostic blocker.
- [ ] Concurrent or crashed runs do not contend for one shared profile in the default fresh-resume path.
- [ ] A headless manual challenge can open a separate verification browser when the operator explicitly chooses it; normal headless execution remains unaffected.
- [ ] Host Helper unavailability is visible and actionable, and no fake browser connection is reported.
- [ ] Existing task progress and retry status are preserved across Resume/Reset, including legacy manual-action events.
- [ ] Backend, frontend, and integration tests cover safe cleanup, fail-closed behavior, explicit strategies, and the rendered controls.

## Dependency

This child depends on the headless child’s launch-mode contract for normal execution. It can be tested independently with a fake process lister, registry, Playwright launcher, and frontend API responses.
