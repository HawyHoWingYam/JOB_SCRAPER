# OfferToday Manual-Action Integration Design

Date: 2026-07-08
Status: Approved direction in chat, pending user review of this written spec
Primary files:
- `backend/app/config.py`
- `backend/app/scraper/manual_action.py`
- `backend/app/manual_actions/live_browser_registry.py`
- `backend/app/services/crawl_job_dispatch_service.py`
- `backend/app/services/headed_crawl_runtime.py`
- `backend/app/scraper/offertoday_browser_detail_scraper.py`
- `backend/scripts/offertoday_auth_setup.py`
- `backend/scripts/offertoday_standalone_crawl.py`
- `backend/scripts/offertoday_transport_bakeoff.py`
- `backend/tests/test_offertoday_canonical_and_identity.py`
- `backend/tests/test_crawl_job_regressions.py`

## Overall Objective

Integrate OfferToday into the repo's existing manual-action and reusable-browser runtime instead of keeping it as a special-case `storage_state` flow.

The practical goal is to make OfferToday behave more like the existing JobsDB and CTGoodJobs headed/manual paths:

- a crawl or repair run can reuse an already-open browser session
- the system can attach to a live browser over CDP
- WAF and `-1000035` failures are surfaced as session-health and manual-action problems, not only as crawler failures
- operators get explicit setup, check, and smoke-test commands before running long OfferToday jobs

This design is informed by `docs/2026-07-08-offertoday-boss-zhipin-research.md` and the session-management patterns in `eatmoreduck/boss-zhipin-scraper`, but the implementation should fit this repo's current control plane rather than introduce a parallel scraper architecture.

## Iteration Scope

This iteration is a backend/runtime integration for OfferToday.

In scope:
- OfferToday support for the existing resume strategies: `fresh_profile` and `reuse_open_browser`
- OfferToday-specific browser configuration and automation profile paths
- a shared OfferToday browser-session runtime that can either launch a fresh Playwright context or attach to an already-open browser via CDP
- integration of that shared runtime into `offertoday_standalone_crawl.py`
- integration of that shared runtime into `OfferTodayBrowserDetailScraper`
- operational commands for OfferToday browser setup, session check, and smoke testing
- regression tests for new resume-strategy and argument-routing behavior

Out of scope:
- changing OfferToday coverage strategy, category search space, or keyword families
- changing OfferToday canonical parsing, company identity parsing, or repair semantics outside session/runtime wiring
- adding a brand-new frontend surface for OfferToday
- removing `storage_state` support entirely in this iteration

## Current State

OfferToday already has useful pieces, but they are split across several partially overlapping flows.

### Current OfferToday flow

- `backend/scripts/offertoday_auth_setup.py` creates a Playwright `storage_state` file after manual login
- `backend/scripts/offertoday_standalone_crawl.py` can preload that `storage_state` file and run headed or headless listing/detail fetches inside a newly launched Playwright browser
- `backend/app/scraper/offertoday_browser_detail_scraper.py` can fetch details in a browser context and wait for manual WAF verification in headed mode

### Current repo-wide manual-action flow

The repo already has a richer runtime for reusable manual sessions:

- `app.scraper.manual_action.ManualActionRequiredError` carries standardized payloads, resume strategies, and instructions
- `app.manual_actions.live_browser_registry` stores reusable browser sessions keyed by automation profile path
- JobsDB and CTGoodJobs scrapers can attach to a live browser with `connect_over_cdp(...)` when `resume_strategy == "reuse_open_browser"`
- `CrawlJobDispatchService.resume_crawl_job(...)` already persists `resume_strategy` and `resume_context`

### Current gap

OfferToday is not using that richer runtime.

Today it still depends mainly on:

- a single `storage_state` artifact
- newly launched Playwright browser contexts
- ad hoc WAF handling inside crawl/detail code

That means the repo already has the abstraction we need, but OfferToday is not yet plugged into it.

## Problem Statement

The current OfferToday flow is serviceable for one-off runs, but weak for sustained or resumable operations.

Main problems:

1. `storage_state` is treated as the primary session mechanism rather than as a compatibility fallback.
2. OfferToday headed recovery does not yet share the repo's reusable-browser model.
3. Listing crawl and detail repair each manage browser/session behavior independently.
4. Operators do not have a clear "is this session healthy enough to run?" command before starting a longer crawl.
5. WAF outcomes such as `-1000035` are still too easy to misread as a parser or crawl bug instead of a session-health problem.

## Design Summary

OfferToday should join the repo's existing manual-action system instead of growing a parallel CLI-only session model.

The stable design is:

- keep the existing manual-action payload contract
- add OfferToday-specific browser settings and profile defaults
- introduce one OfferToday browser-session runtime module that encapsulates fresh launch, CDP attach, warmup, and health probes
- route both the standalone crawl path and the browser detail scraper through that shared runtime
- upgrade the operational scripts so setup, check, and smoke testing become first-class steps

`storage_state` remains supported as a fallback input, but not the main architectural center.

## Proposed Architecture

### 1. OfferToday browser settings

Add OfferToday-specific runtime settings in `backend/app/config.py` instead of reusing `jobsdb_headed_*` names.

Recommended settings:

- `offertoday_headed_browser_channel`
- `offertoday_headed_browser_user_data_dir`
- `offertoday_headed_browser_executable_path`
- `offertoday_headed_navigation_timeout_ms`

Rationale:

- JobsDB naming is already too specific to reuse cleanly
- OfferToday should have its own automation profile path so live sessions can be reused safely and independently
- the existing generic live-browser registry can still be reused because it is keyed by profile path, not source site

### 2. Shared OfferToday browser-session runtime

Introduce a focused OfferToday runtime module under `backend/app/scraper/` that owns browser-session behavior.

Responsibilities:

- resolve `fresh_profile` vs `reuse_open_browser`
- start Playwright runtime when using a fresh profile
- attach with `connect_over_cdp(...)` when reusing an open browser
- optionally preload `storage_state` when a fallback file is supplied
- perform OfferToday warmup navigation to `/hk/search`
- detect WAF challenge URLs
- expose helper methods for listing fetch, detail fetch, and health checks

This runtime should centralize the logic that is currently duplicated between:

- `offertoday_standalone_crawl.py`
- `OfferTodayBrowserDetailScraper`

### 3. Manual-action compatibility

OfferToday should emit and consume the same manual-action semantics used elsewhere.

Requirements:

- when a reusable browser is requested but unavailable, raise `ManualActionRequiredError` with OfferToday-specific message text and reuse instructions
- when WAF or equivalent session failure blocks progress in a resumable flow, emit a standardized manual-action payload rather than only logging progress events
- preserve `resume_context` so resumed detail work can target the same crawl phase and listing scope

The repo already supports generic resume dispatch in `CrawlJobDispatchService`; this design reuses that existing machinery instead of replacing it.

### 4. Standalone crawl integration

`backend/scripts/offertoday_standalone_crawl.py` should stop owning session wiring directly.

Instead it should:

- accept resume/session-related arguments
- build an OfferToday browser runtime from those arguments
- call that runtime for warmup, listing requests, detail requests, and health probes

New or clarified arguments:

- `--resume-strategy fresh_profile|reuse_open_browser`
- `--auth-state <path>` as a fallback compatibility option
- `--check` for a session health probe
- `--smoke-test` for a short listing/detail probe without starting a long crawl

Existing listing/detail crawl behavior remains, but the session layer becomes replaceable and testable.

### 5. Detail scraper integration

`backend/app/scraper/offertoday_browser_detail_scraper.py` should use the same OfferToday runtime abstraction.

Behavioral goals:

- support `request_payload["resume_strategy"]`
- reuse the OfferToday automation profile when the user selects `reuse_open_browser`
- keep current `OfferTodayIPBlockedError` semantics for hard `-1000035` outcomes
- treat reusable-browser unavailability as a manual-action/runtime issue, not as a raw Playwright failure

This aligns OfferToday detail recovery with the rest of the repo's resumable scraper behavior.

### 6. Operational scripts

Upgrade the OfferToday scripts so operators can prepare and validate sessions explicitly.

#### `offertoday_auth_setup.py`

Evolve from "write one storage_state file" to "prepare or reuse an OfferToday automation browser".

Expected capabilities:

- initialize or reuse a dedicated OfferToday browser profile
- optionally launch with remote debugging enabled
- optionally copy or save a fallback `storage_state`
- register the launched session in the live-browser registry when remote debugging is enabled

#### `offertoday_transport_bakeoff.py`

Turn it into a real comparison and diagnostics tool.

Candidate modes:

- fresh Playwright profile
- Playwright with `storage_state`
- live-browser attach via CDP

Recorded metrics:

- listing success
- detail success
- `-1000035` or WAF outcomes
- elapsed time

#### `check` and `smoke` commands

The setup/check/smoke trio should become explicit operator steps:

1. `setup`: prepare session and browser profile
2. `check`: verify listing endpoint access and session readiness
3. `smoke`: run a small listing probe plus a few detail probes

This is the most directly reusable insight from the Boss reference repo.

## Data Flow

### Fresh-profile path

1. operator launches OfferToday setup or a headed crawl
2. runtime opens the dedicated OfferToday automation profile
3. runtime warms up `/hk/search`
4. crawl/detail fetches execute through that runtime
5. if WAF blocks a resumable flow, the job can move to manual-action-required state

### Reuse-open-browser path

1. operator launches or keeps open the OfferToday automation browser with remote debugging enabled
2. live session is present in `live_browser_registry`
3. resumed crawl or detail recovery selects `resume_strategy = reuse_open_browser`
4. runtime attaches over CDP to the existing browser session
5. crawl/detail fetches reuse the already-warmed authenticated context

### Storage-state fallback

1. a fallback `storage_state` file is supplied
2. runtime loads it into a fresh Playwright context
3. runtime still uses the same warmup and health checks
4. if it proves insufficient, operators can move to reusable-browser mode without changing the higher-level crawl contract

## Error Handling

### Reusable browser unavailable

If `reuse_open_browser` is selected and no live session exists for the configured OfferToday profile:

- raise a standardized manual-action/runtime error
- do not silently downgrade to `fresh_profile`

Reason:

- silent fallback hides the actual operator state and makes debugging harder

### Attached browser has no reusable context

Treat this as the same class of failure as an unreachable live browser:

- emit a clear OfferToday-specific reuse failure
- instruct the operator to relaunch the visible automation browser

### Listing check fails

If the check path cannot complete a small listing request:

- mark the session unhealthy
- do not treat the setup as valid for long-running crawl work

### Detail probe returns `-1000035`

Treat this as session/WAF health evidence first.

Implication:

- the smoke test should report it explicitly
- operational guidance should steer the user toward headed/manual verification or browser reuse, not parser changes

## Testing and Verification

### Backend unit and regression coverage

Add focused tests for:

1. OfferToday runtime choosing `reuse_open_browser` when requested
2. OfferToday runtime failing clearly when no live reusable browser exists
3. OfferToday detail scraper honoring `resume_strategy`
4. OfferToday standalone crawl or API dispatch passing new resume/check/smoke arguments correctly
5. existing OfferToday IP-block classification behavior still raising `OfferTodayIPBlockedError`

Likely test files:

- `backend/tests/test_offertoday_canonical_and_identity.py`
- `backend/tests/test_crawl_job_regressions.py`
- add a new OfferToday runtime test module if the shared runtime is large enough to justify it

### Script-level verification

Required command-level checks after implementation:

- `python -m pytest -q backend/tests/test_offertoday_canonical_and_identity.py`
- `python -m pytest -q backend/tests/test_crawl_job_regressions.py`

If a new test module is added:

- `python -m pytest -q backend/tests/<new-offertoday-runtime-test-file>.py`

### Live verification

Before calling the work complete, verify the new path with a real OfferToday browser session.

Minimum live checks:

1. run OfferToday setup against the dedicated automation profile
2. run OfferToday check and confirm listing access succeeds
3. run OfferToday smoke test and confirm it reports listing/detail outcomes with clear WAF classification

This verification does not need to prove that OfferToday never blocks again. It does need to prove that the repo now has a first-class reusable-browser and preflight workflow for OfferToday.

## Implementation Steps

1. add OfferToday-specific browser settings
2. extract shared OfferToday browser runtime logic
3. integrate that runtime into `OfferTodayBrowserDetailScraper`
4. integrate that runtime into `offertoday_standalone_crawl.py`
5. upgrade `offertoday_auth_setup.py` into a profile-first setup path
6. expand `offertoday_transport_bakeoff.py` into a real check/smoke comparison tool
7. add regression tests for resume strategy and runtime-selection behavior
8. run focused pytest verification
9. run live OfferToday setup/check/smoke verification

## Risks

- OfferToday still runs headed crawls inside the same container rather than through the host-side headed worker, so the integration must not assume the JobsDB host worker model
- retrofitting manual-action semantics into the standalone OfferToday path may surface state-management gaps that were previously hidden by ad hoc script behavior
- if the new shared runtime is too script-shaped, it will just move duplication into a different file

Mitigations:

- keep the runtime focused on browser/session concerns only
- leave search-space logic and canonical parsing alone
- keep `storage_state` as a compatibility fallback while proving out the reusable-browser path

## Success Criteria

This iteration is successful when all of the following are true:

- OfferToday has a documented and implemented reusable-browser path based on the repo's existing manual-action runtime
- OfferToday detail recovery and standalone crawl no longer manage browser reuse as unrelated one-off flows
- operators have explicit setup, check, and smoke steps before long OfferToday jobs
- the codebase still supports `storage_state`, but it is no longer the architectural center
- focused tests and a real OfferToday session check provide evidence that the new path works in the current repo
