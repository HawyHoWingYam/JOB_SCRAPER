# Repair CTGoodJobs expired-detail recovery loop

## Goal

Classify explicit CTGoodJobs expired-job pages as terminally unavailable before parsing or ingest, so one expired job does not pause the entire detail crawl or send the operator through a browser-resume loop.

## User Value

Expired job IDs are an expected terminal outcome. The crawler should record that outcome for the individual target and continue the batch without asking the operator to resolve a browser problem that does not exist.

## Confirmed Evidence

- Crawl job `3a271e44-370d-430e-8677-fb36ad4cf524` is a CTGoodJobs headless detail task.
- Its `reuse_open_browser` recovery successfully attached to the live browser, then returned to `manual_action_required` after two consecutive `missing_company_identity` outcomes.
- The live DOM for `https://jobs.ctgoodjobs.hk/job/10185476/network-engineer` explicitly contains `<section class="jd--edge jd--expired">` and the message `Sorry, this job has expired.`
- The expired page retains the historical job title and company name for display, but exposes no company ID, employer ID, or employer URL. Missing durable company identity is therefore expected for this terminal page.
- `backend/app/scraper/ctgoodjobs/page_state.py:8-28` already models expired jobs as `terminal_unavailable`, but its explicit state tokens do not recognize CTGoodJobs' live `jd--expired` class.
- `backend/app/scraper/ctgoodjobs/page_state.py:115-149` intentionally limits expiry detection to HTTP 404/410, document title, and explicit page-state containers so job-description prose cannot create false positives.
- Because the live expired container is missed, the page reaches `backend/app/sources/ctgoodjobs/parsers.py:511-552`, where the absent active-job payload becomes `missing_job_content` and missing company identity.
- `backend/scripts/ctgoodjobs_standalone_crawl.py:1011-1028` turns two consecutive matching content anomalies into whole-crawl `manual_action_required`; unchanged Resume therefore loops deterministically.
- The existing CTGoodJobs terminal-unavailable path records the individual target as terminal and continues the batch. No parser fallback or fabricated company identity is required for an expired page.
- Cross-source inspection found different maturity levels: OfferToday has an explicit terminal-unavailable detail response, while JobsDB does not yet have an equivalent confirmed expired-page contract.
- Cross-source parity is tracked separately in `../07-25-cross-source-expired-detail-contract`; it does not block this P1 regression fix.

## Requirements

- R1. Recognize CTGoodJobs' explicit live expired-page container/state as `terminal_unavailable` before detail parsing.
- R2. Record the affected detail target as terminally unavailable and continue processing the remaining batch.
- R3. Do not send an explicit expired page through ingest, company fallback identity generation, content-anomaly counting, or manual browser recovery.
- R4. Preserve the conservative page-state boundary: ordinary job-description text mentioning expiration must not classify an active job as terminal.
- R5. Preserve existing HTTP 404/410, explicit state-token, access-block, WAF, and genuinely unknown-page behavior.
- R6. Add a deterministic regression fixture matching the observed `jd--expired` page shape and a crawl-level test proving the batch continues without manual action.
- R7. Keep the current crawl scope and completed-target checkpoint unchanged; the fix must work when the same task resumes.

## Acceptance Criteria

- [ ] An HTTP 200 page containing the observed top-level `jd--expired` state and message classifies as `terminal_unavailable` with a stable reason.
- [ ] The diagnosed expired job is not passed to the parser or ingest worker.
- [ ] An expired target increments terminal-unavailable progress and the next detail target is attempted.
- [ ] The expired target does not contribute to the consecutive content-anomaly threshold and does not produce `manual_action_required`.
- [ ] Expiration wording inside an ordinary job description remains non-terminal.
- [ ] Existing CTGoodJobs page-state, browser-fetch, crawl-runtime, access-block, and recovery tests pass.

## Out of Scope

- Synthesizing company identity for an expired job.
- General active-page schema fallback without a separately observed valid-page failure.
- Shared Host Helper/browser-profile redesign or stale registry metadata cleanup.
- JobsDB/OfferToday expired-detail parity work owned by the separate P2 audit task.
