# Crawl Tasks verification — 2026-09-23

Implemented validated route context; in-app bounded audit events and retry; off-page identity explanation; truthful refresh feedback; latest-detail request protection; mapped recovery receipt with duplicate-resume guard; monitoring-first hierarchy; source-scoped Scheduler follow-up for terminal backlog.

## Checks

- Full frontend: 247 tests / 34 files passed.
- Frontend lint and production build passed.
- Isolated Scheduler + Crawl browser suite: 9 passed. After final CSS/evidence updates, 4 Crawl browser journeys passed again.
- Backend via existing container: `python -m pytest -q tests/test_crawl_control_api.py tests/test_crawl_task_snapshot_service.py tests/test_crawl_job_runtime.py`: 43 passed, 16 deprecation warnings.
- Host Python lacked pytest; used the project container's installed dependencies. Tests use isolated fixtures/stubs and did not launch live crawls.
- Inspected rendered 1366px screenshot; captures also retained at 1440 and 760px. Browser screenshots explicitly reset the app scroll container before capture.

## Evidence limits and remaining integration

API-intercepted browser tests verify frontend behavior and payloads, not real worker/provider connectivity. Backend projection/action regressions are separate. Before/after screenshots were subsequently captured with the same intercepted fixtures under research/. Manual QA and GitHub closure remain pending. Final four-page automated integration is complete; parent verification.md records the full results.

The browser fixtures hold failures/cancellation until explicitly released by the scenario, so automatic HTTP retries and immediate status refresh cannot accidentally skip the state under test. Scheduler screenshot output now goes to /tmp rather than recreating the archived task path.

Baseline evidence was subsequently captured from an isolated `git archive HEAD frontend` checkout with the same intercepted fixtures, at 1366×768. The working implementation was not reverted to capture it. See research/before-1366.png.

Final integration: 260 frontend tests passed; lint/build passed; 15 isolated browser workflows and 22 fake-provider integration/browser journeys passed. Backend full suite plus isolated PostgreSQL/Redis supplements covered all 748 collected cases successfully. See parent verification.md for evidence and test-environment limits.
