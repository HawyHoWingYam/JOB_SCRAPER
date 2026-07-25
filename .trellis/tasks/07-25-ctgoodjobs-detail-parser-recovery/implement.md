# Implementation plan

1. Load backend scraper, error-handling, and test specs before editing.
2. Add a minimal sanitized fixture representing the observed HTTP 200 `<section class="jd--edge jd--expired">` page with its top-level expiration message and historical display fields.
3. Add a red classifier regression test asserting `classification=terminal_unavailable` and `reason=job_expired` for the fixture.
4. Extend CTGoodJobs' explicit page-state token recognition so the owned expired container is captured while the known-message check remains mandatory.
5. Verify the regression test turns green and that ordinary job-description expiration prose remains non-terminal.
6. Re-run the existing crawl-level terminal test proving the target is marked terminal and the next target is attempted without manual action.
7. Run targeted CTGoodJobs page-state, browser/detail, cross-source crawl logging, lint/type/compile checks required by the loaded specs.
8. Perform a read-only/manual validation against the diagnosed expired page or captured live HTML: it must classify as `job_expired` before parser/ingest. Do not resume the production task until the fixed container is deployed.
9. Run `trellis-check`, update relevant specs if the explicit-state contract is not already recorded, then commit and finish through the normal Trellis flow.

## Risk and rollback points

- Primary risk: broad state capture could misclassify ordinary content. Keep the new token source-owned and retain the marker requirement.
- The pure classifier test is the tight feedback loop; the existing crawl-level test protects downstream transition semantics.
- No data migration or cleanup should be needed. Existing manual-action events remain historical evidence.

## Current validation

- Red: the observed `jd--expired` classifier fixture failed with `evidence is None` before the implementation change.
- Green: `backend/tests/test_ctgoodjobs_page_state.py` passes (5 tests).
- Focused recovery suite passes (50 tests): CTGoodJobs page state, browser scraper, cross-source crawl logging, and cross-source IP/WAF recovery.
- Canonical backend suite passes with the two frontend-fixture mount checks excluded: 484 passed, 161 skipped, 2 deselected. Running those checks inside `backend-api` fails only because the Compose container does not mount the repository frontend at `/frontend`; no product assertion fails.
- Ruff, Python compileall, and `git diff --check` pass for the touched implementation and test files.
- Read-only CDP validation against crawl job `3a271e44-370d-430e-8677-fb36ad4cf524` returns `classification=terminal_unavailable`, `reason=job_expired`, and HTTP status `200` for the diagnosed URL.
