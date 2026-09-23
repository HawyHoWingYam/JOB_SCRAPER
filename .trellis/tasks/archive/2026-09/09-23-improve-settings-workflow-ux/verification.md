# Settings verification — 2026-09-23

## Delivered

- Validated section/profile/AI-return routing and browser history restoration.
- Visited Settings sections remain mounted, preserving unsaved drafts in memory. No credential storage was added.
- AI saved/draft indicator, explicit discard, retry after initial loading failure, retained input after failed save, and focused feedback.
- Runtime configuration navigation stays above the summary; laptop metrics fit one compact row. All configuration controls remain directly reachable.
- Provider test copy distinguishes draft testing from saving; after testing, refresh the saved runtime status without replacing the draft.
- Per-source pacing discard, read retry and confirmation before reset overwrites unsaved edits.

## Checks

- 33 Settings component/route tests passed.
- Full frontend: 260 tests across 36 files passed; lint and production build passed.
- 15 isolated browser workflows cover all four pages. Settings paths run at 1366, 1440 and 760 pixels and include keyboard activation, back/forward draft preservation, save validation/retry, provider test, reload and exact AI return.
- Existing fake-provider browser integration: 22 passed across Jev settings and usability. Dedicated `jobsdb_jev_operations_ux_test` database was created and removed; provider calls targeted loopback only.
- Focused Settings backend regression: 20 passed. Full backend, with disposable PostgreSQL suites enabled: 746 passed, with the two initially skipped cutover rehearsals separately passing against their own disposable PostgreSQL/Redis resources. Aggregate: 748 tests passed, no remaining unexecuted cases from that run.

## Evidence and limits

`research/before-1366.png` comes from an isolated archive of HEAD with the same intercepted fixtures. `after-overview-1366.png` shows runtime navigation; other after images show pacing and the tested return flow. Browser interception checks frontend state and payloads; real fake-provider tests separately cover server persistence and receipts. No real paid provider or live crawl was used. Existing Python/Node deprecation warnings remain. Manual QA and GitHub closure are pending.
