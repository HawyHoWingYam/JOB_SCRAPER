# Harden crawl quality and task metrics

GitHub issue: [#8](https://github.com/HawyHoWingYam/JOB_SCRAPER/issues/8)

## Goal

Prevent CTGoodJobs verification pages from becoming long runs of ordinary detail failures, distinguish unavailable jobs from failures and manual action, and give CTGoodJobs, JobsDB, and OfferToday detail tasks a truthful common metrics vocabulary.

## Background

- CTGoodJobs detail task `5f6aa0bf-ec22-4f49-94c6-179667ec9316` was resumed after a valid `headed_display_unavailable` manual action, then accumulated 143 consecutive `InvalidIngestPayloadError` outcomes with the identical message `Missing source company id and company name for source_site=ctgoodjobs`. The same run later succeeded again. The user directly observed a verification page during the failure burst, so these were not credibly 143 independent expired jobs.
- The browser adapter only converts recognized IP/WAF evidence into manual action (`backend/app/scraper/ctgoodjobs_browser_page_scraper.py:101-188`). The detail loop stops on `ManualActionRequiredError`, but treats every other exception as `failed` and continues (`backend/scripts/ctgoodjobs_standalone_crawl.py:579-614,646-699`).
- The parser records `missing_job_content` and missing identity coverage but does not classify page state (`backend/app/sources/ctgoodjobs/parsers.py:505-639`). The repository has no captured CTGoodJobs verification or expired-detail HTML fixture, so missing fields alone are not positive WAF, IP, or expiry evidence.
- Crawl Tasks currently shows CTGoodJobs metrics such as `Detail targets 2,296 | Failed 95`, while OfferToday can show targets, segment/backlog, fetched, and saved. Runtime transitions already maintain detail-run status counts (`backend/app/services/crawl_job_runtime.py:1154-1210,1386-1490`), but the generic snapshot fallback does not use `detail_run_completed` for fetched progress (`backend/app/services/crawl_task_snapshot_service.py:800-913`). CTGoodJobs and JobsDB progress events also expose `detail_ok/detail_fail` rather than the normalized UI fields (`backend/scripts/ctgoodjobs_standalone_crawl.py:731-746`, `backend/scripts/jobsdb_standalone_crawl.py:662-677`).
- The frontend hides most zero-valued detail metrics and renders OfferToday continuation fields conditionally (`frontend/src/components/scraper/CrawlTasksPage.jsx:185-234`).

## Requirements

### R1. CTGoodJobs page-outcome classification

- Classify positive CTGoodJobs access evidence before parsing. A recognized verification challenge must immediately produce resumable manual action on its first occurrence.
- Classify a target as `terminal_unavailable` only from authoritative evidence: HTTP 404/410, an explicit removed/closed/not-found page state, or an equivalent structured CTGoodJobs unavailable response.
- Missing company identity, job content, or other parsed fields alone must never be treated as IP block, WAF challenge, or expiry.
- Preserve the shared positive-evidence boundary: generic network, parser, and ingest failures must not be relabelled as `ip_blocked`.

### R2. Structural-anomaly circuit breaker

- Treat the first supported CTGoodJobs structural anomaly signature as a retryable `failed` target.
- If the immediately following target produces the same supported anomaly signature, classify the second target as resumable `content_anomaly`, mark it `manual_action_required`, and stop all later detail requests.
- A successful valid detail resets the consecutive anomaly state.
- Resume must retry the first failed anomaly target, the manual-action target, and remaining pending targets while excluding completed and terminally unavailable targets.
- Preserve completed work and require explicit operator resume; no polling or automatic resume is allowed.

### R3. Distinct outcome metrics

- Keep `Failed`, `Unavailable`, and `Manual action` separate. `Unavailable` and `Manual action` must not inflate `Failed`.
- `Remaining` means unresolved targets in the current frozen/selected target set. It includes the manual-action target while it still requires work; `Manual action` is therefore a diagnostic subset, not an additive conservation term.
- `Saved` is persistence progress and is not additive with target outcomes; a saved item is also a fetched/successful item.

### R4. Common detail-task metrics contract

- Every CTGoodJobs, JobsDB, and OfferToday detail snapshot must expose an ordered common core: `Detail targets`, `Fetched`, `Saved`, `Failed`, and `Remaining`.
- Render all five common values even when zero, so an observed zero cannot be confused with missing telemetry.
- Show nonzero `Unavailable` and `Manual action` counts separately.
- Retain real OfferToday-only `Segment targets` and continuation `Backlog remaining` metrics. Do not synthesize segment/backlog concepts for CTGoodJobs or JobsDB.
- Preserve existing snapshot fields for compatibility; normalized common fields are additive projections.

### R5. Safety and scope

- Preserve unrelated dirty-worktree changes.
- Do not persist or log response bodies, cookies, auth state, or other sensitive challenge content. Durable evidence must remain bounded to status, final URL, title/reason identifiers, and compact anomaly signatures.

## Acceptance Criteria

- [ ] AC1: A synthetic positive CTGoodJobs verification page enters resumable manual action on the first target and issues no later detail request.
- [ ] AC2: A first supported structural anomaly is recorded as `failed`; a consecutive identical anomaly makes the second target `manual_action_required`, emits `classification=content_anomaly`, and stops later targets.
- [ ] AC3: A valid detail between two anomalies resets the circuit breaker, so the later anomaly is again only the first failure.
- [ ] AC4: Resume after `content_anomaly` selects the earlier failed target, the manual-action target, and pending targets, but excludes completed and `terminal_unavailable` targets.
- [ ] AC5: HTTP 404/410 and explicit unavailable-page fixtures become `terminal_unavailable`; missing fields without unavailable evidence do not.
- [ ] AC6: Tests prove network/parser/ingest failures without positive access evidence are never relabelled `ip_blocked` or `waf_challenge`.
- [ ] AC7: Snapshots for all three sources expose common target, fetched, saved, failed, remaining, unavailable, and manual-action counts with the documented semantics.
- [ ] AC8: Crawl Tasks always renders the five common core metrics for detail tasks, including zero values; optional outcome chips and OfferToday-only continuation metrics render only when applicable.
- [ ] AC9: Focused backend tests, Ruff, Python compilation, focused frontend tests, the frontend production build, and scoped diff checks pass.
- [ ] AC10: A rebuilt local runtime returns the new normalized snapshot fields for existing CTGoodJobs, JobsDB, and OfferToday detail-task records without a database migration.

## Constraints

- This is one complex cross-layer task rather than a parent/child split: CTGoodJobs outcome transitions feed the same runtime metrics, snapshot projection, and frontend contract changed by the metrics work. Splitting them would duplicate the central contract and integration gate.
- Planning requires `design.md` and `implement.md`; implementation begins only after user review and task activation.
- Live verification must not deliberately trigger a block or CAPTCHA. Synthetic page fixtures provide the deterministic classification gate; runtime smoke may only observe naturally occurring external state.

## Out of Scope

- OfferToday non-IT result auditing or filtering. The user explicitly cancelled this deliverable during planning.
- Replacing the existing OfferToday distinct-progress or segment/backlog model.
- Automatic browser interaction that attempts to solve a verification challenge.
