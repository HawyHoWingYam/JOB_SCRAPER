# Honor headless mode in JobsDB detail crawling

## Goal

Make JobsDB detail execution honor the reviewed `crawl_mode` instead of forcing a visible persistent browser, while preserving an explicit headed verification-browser escape hatch for manual recovery.

## Background

`backend/app/scraper/jobsdb_browser_detail_scraper.py:192-208` currently passes `headless=False` to every fresh persistent launch. This caused a task recorded as headless to fail with a message about closing Edge. The existing `reuse_open_browser` path attaches to a separately registered browser and is intentionally an operator opt-in, not normal headless execution.

## Requirements

- H1. Keep the existing Playwright-based detail extraction and parser for the MVP.
- H2. Derive fresh-browser launch visibility from the reviewed task/request `crawl_mode`: `headless` → `headless=True`; `headed` → `headless=False`.
- H3. Preserve explicit `reuse_open_browser` attach behavior for manual recovery. This path may use a headed verification browser even when the task’s normal mode is headless, but it must be recorded as the selected recovery strategy.
- H4. Do not make normal headless execution depend on a local desktop, Host Helper, or visible Edge window.
- H5. Keep browser channel/executable fallback and existing detail parsing behavior unchanged except for launch-mode selection.

## Acceptance criteria

- [ ] Unit tests assert the Playwright launch receives `headless=True` for a fresh headless request and `headless=False` for a fresh headed request.
- [ ] Unit tests assert `reuse_open_browser` attaches through the live-browser registry without launching a fresh context.
- [ ] A headless manual-action recovery can still explicitly select `reuse_open_browser`; the normal fresh path remains headless.
- [ ] Existing parser, interstitial classification, cancellation, and cleanup tests pass.
- [ ] Profile-launch errors no longer produce a local-Edge instruction for a normal headless fresh launch; they use the profile-recovery contract from the sibling task.

## Dependency and scope

The profile-recovery child consumes this launch contract. HTTP/API extraction, listing behavior, and non-JobsDB source behavior are out of scope.
