# Four-page operational UX acceptance — 2026-09-23

## Delivery map

| Child | Issue | Delivery |
|---|---|---|
| Scheduler | #75 | Previously committed as 43b245e1, archived, manual QA pending |
| Crawl Tasks | #76 | Route context, exact audit handoff, recovery/cancellation feedback, monitoring hierarchy |
| AI Enrichment | #77 | Current preview authority, actual receipts, exact-run history/items, crawl/runtime handoffs |
| Settings | #78 | Draft continuity, saved/discard/retry states, direct section navigation, AI return context |

## Final automated evidence

- `cd frontend && npm test`: **260 passed, 36 files**.
- `npm run lint`, `npm run build`, `git diff --check`: passed.
- `npx playwright test --config playwright.scheduler.config.js`: **15 passed**. Includes Scheduler authoring/review, exact task/log handoff, Crawl events/retry/cancellation, AI launch/actual receipt/history/stop/retry/waiting handoff, Settings keyboard/back-forward drafts/save/test/reload/return. Settings-only **3 passed** again after final visual compaction.
- `JEV_E2E_TEST_DATABASE=jobsdb_jev_operations_ux_test npx playwright test --config playwright.config.js --ignore-snapshots e2e/jev-settings.spec.js e2e/usability.spec.js`: **22 passed** against disposable PostgreSQL and loopback fake provider.
- Initial `docker compose exec -T backend-api python -m pytest -q tests`: **689 passed, 59 skipped** because isolated integration URLs were absent.
- Enabled seven isolated PostgreSQL test databases for dispatch/bootstrap/Jev duplicate/quality/search/triage/Job intelligence suites: **746 passed, 2 skipped**. All seven databases were removed after execution.
- The two remaining sandbox cutover rehearsals ran separately against another disposable PostgreSQL database and a dedicated Redis container/database 15: **2 passed**; both resources removed. **All 748 collected backend cases have passed across these runs.**

No real provider, live crawl, production data rebuild or production Redis flush was used. Backend warnings were existing datetime.utcnow deprecations; Node emitted existing runtime/deprecation warnings. Host Python lacked pytest; the project backend container supplied its test dependencies.

## Rendered evidence

Each remaining child has before/after evidence under research/. Before views were captured from an isolated `git archive HEAD frontend` checkout using intercepted APIs. Comparable overview captures are 1366×768; workflow evidence additionally covers 1440 and 760 widths. Main agent visually inspected Crawl, AI and Settings views. The frontend uses an internal scrolling main container, so captures explicitly reset that scroll before screenshots.

## Final review

- Backend authority and schemas unchanged; mutations still require existing reviewed/capability/active-slot rules.
- Existing Scheduler task links remain valid. Filters, run identity and Settings return identity remain bounded and shareable.
- AI keeps exactly two monitor slots; separate history includes waiting/older runs and item evidence. Exclusions never enable failed-item retry.
- Settings drafts remain memory-only across section switches. Credentials are not persisted to browser storage.
- Delayed task reads are fenced; explicit pending cancellation/recovery remains distinct from terminal completion.
- Main session implemented and checked all changes. Scouts supplied read-only findings only.

## Remaining lifecycle

Implementation and automated integration are complete. The concrete commit batch is in commit-plan.md. User approved this batch; UI work is committed as 3b460795. Documentation commit, archive of these three children plus the parent, and journal follow. Issues #74–#78 stay open until explicit manual QA acceptance. No push is included.
