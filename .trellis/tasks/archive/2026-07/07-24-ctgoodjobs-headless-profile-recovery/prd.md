# CTGoodJobs headless profile recovery

## Goal

Make CTGoodJobs routine crawling headless-first while retaining an explicit
operator-driven headed browser for real verification challenges, and prevent
browser runs from contending for one shared Chromium profile.

## User value

CTGoodJobs listing, detail, and catalog-validation work can run invisibly and
independently. When the source genuinely requires human action, the operator
gets safe, explicit recovery controls instead of a generic `RUN_FAILED` or an
instruction to close an unrelated browser.

## Confirmed facts

- `backend/app/crawl_modes.py:7-19` currently declares CTGoodJobs headed-only
  and upgrades legacy `headless` requests to `headed`.
- `backend/app/scraper/ctgoodjobs_browser_page_scraper.py:267-293` hard-codes
  `headless=False`, and `:541-549` resolves every fresh launch to the configured
  fixed profile rather than a task-owned directory.
- `backend/app/source_catalog/adapters/ctgoodjobs.py:83-90` constructs a headed
  catalog-validation browser without a crawl job identity.
- Historical run `a454498d-7954-4039-82f0-ae0f06882e4e` failed against
  `/app/.host_browser_profiles/chromium` with `SingletonLock: File exists`,
  `readlink(.../SingletonLock) failed: Invalid argument`, and
  `Failed to create a ProcessSingleton`. A no-browser reproduction proved that
  a stale regular `SingletonLock` alone causes the same failure.
- `backend/app/scraper/ctgoodjobs_browser_page_scraper.py:499-504` recognizes
  only the older `Target page, context or browser has been closed` wording, so
  the real ProcessSingleton failure bypasses manual recovery.
- The bounded four-arm experiment preserved in commit `d8fce3af` recorded
  116/116 parser-valid observations: plain HTTP, fresh headless, stateful
  headless, and headed each passed 29/29. It did not prove long-term behavior
  across networks, IPs, or time windows.
- `backend/app/scraper/jobsdb_profile_recovery.py` already implements most of
  the required liveness, lock cleanup, task ownership, and orphan-reaping
  primitives, but its interface and ownership are JobsDB-specific.

## Requirements

- P1. CTGoodJobs supports a real `headless` crawl mode across listing, detail,
  dispatch contracts, CLI/runtime plans, and source-catalog validation. Headed
  remains an explicit debug and manual-recovery mode.
- P2. Routine CTGoodJobs automation uses headless Chromium. It does not
  silently cascade from plain HTTP to browser or from headless to headed.
  Positive IP/WAF/human-verification evidence pauses work for explicit operator
  action.
- P3. A fresh crawl run uses a task-owned profile keyed by `crawl_job_id`.
  Catalog validation uses a separately owned ephemeral operation profile so it
  cannot contend with a crawl or the fixed verification profile.
- P4. Extract source-neutral browser-profile primitives for allocation,
  liveness inspection, safe lock cleanup, registry coordination, terminal
  cleanup, and lazy orphan reaping. JobsDB and CTGoodJobs consume the shared
  implementation without changing the established JobsDB behavior.
- P5. A profile may be reset only after the backend proves that no matching
  browser process is alive and no registered CDP session is reachable. Unknown
  liveness fails closed. Fixed verification profiles are never task-owned for
  deletion.
- P6. Recognize both the legacy closed-context wording and real Chromium
  profile-lock evidence, including `ProcessSingleton`, `SingletonLock: File
  exists`, and equivalent wrapped Playwright launch errors.
- P7. A fresh resume may perform at most one automatic safe stale-profile
  cleanup and relaunch. A second failure pauses with structured diagnostics;
  retries preserve the original scope, backlog snapshot, completed targets,
  and crawl limits.
- P8. CTGoodJobs Task Details exposes capability-gated Reset, Fresh Profile,
  Open Browser, and Reuse Open Browser actions. Disabled Reset explains the
  live or unknown-liveness blocker. Host Helper failure never produces a fake
  reusable session or silently changes strategy.
- P9. Temporary run profiles survive while work is active or awaiting manual
  action, are removed on terminal outcome, and are eligible for lazy orphan
  cleanup after the shared default TTL. Ephemeral catalog profiles are cleaned
  after validation and are also orphan-reapable after crashes.
- P10. Listing, detail, and catalog validation must all pass automated coverage
  and live canary validation before the CTGoodJobs default changes to headless.
  If any canary is blocked or structurally invalid, keep headed as the default
  and treat rollout as incomplete.
- P11. Existing historical failed records are left unchanged. New failures use
  the structured recovery behavior.

## Acceptance criteria

- [ ] A requested CTGoodJobs headless run remains headless through validation,
  dispatch, runtime planning, and browser launch; it is not upgraded to headed.
- [ ] Concurrent listing/detail runs and catalog validation receive distinct
  owned profiles and do not use the fixed verification-profile root.
- [ ] A real stale regular `SingletonLock`/ProcessSingleton reproduction enters
  safe recovery, performs no more than one automatic reset/retry, and never
  becomes an unclassified `RUN_FAILED`.
- [ ] Live, dead, and unknown profile liveness produce respectively blocked,
  allowed, and fail-closed Reset results with structured diagnostics.
- [ ] Terminal and orphan cleanup delete only owned temporary profiles; fixed
  headed verification data, cookies, and login state remain intact.
- [ ] IP/WAF/human-verification evidence leaves the same task paused and offers
  explicit headed-browser verification followed by `reuse_open_browser`.
- [ ] Task Details renders explicit CTGoodJobs recovery strategies and helper
  status without a generic ambiguous Resume action.
- [ ] Existing JobsDB profile-recovery tests and behavior remain green after
  the shared-module extraction.
- [ ] Automated backend/frontend coverage passes for listing, detail, catalog,
  profile safety, retry limits, checkpoint preservation, and rendered controls.
- [ ] Live CTGoodJobs canaries for listing, detail, and catalog validation all
  pass before the default flips to headless; otherwise headed remains default.

## Out of scope

- Rewriting or migrating historical failed crawl records.
- Automatic CAPTCHA solving, challenge evasion, or unattended resume after a
  human-verification signal.
- A plain-HTTP-first or automatic HTTP-to-browser transport cascade.
- Changing non-CTGoodJobs source behavior beyond preserving JobsDB compatibility
  while extracting the shared profile manager.
- A database migration solely for profile metadata.
