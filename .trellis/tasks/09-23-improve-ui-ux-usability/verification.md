# Verification and delivery

## Automated results

- Frontend lint: passed (`npm run lint`).
- Frontend production build: passed (`npm run build`).
- Frontend Vitest: 34 files, 232 tests passed (86.40 seconds with one Vitest worker during the embedding rebuild). Coverage includes independent maintenance failure, collection action deduplication, and existing search/run/governance contracts.
- Browser E2E: 22 passed, zero failures (`npm run e2e`, 1.3 minutes under embedding rebuild load). Fifteen existing scenarios exercise actual FastAPI/PostgreSQL test routes and a local fake Jev provider. Seven added scenarios cover both laptop result geometries, explicit search application and failed-apply result retention, all navigation destinations, empty AI queue guidance, and keyword failure recovery, valid CSV confirmation, and invalid CSV refusal. Fault conditions use browser network interception. Tests do not call paid production providers.
- Backend: `docker exec backend-api python -m pytest -q tests` completed with 689 passed, 59 skipped, 329 warnings in 22.92 seconds on the rebuilt backend. Skipped tests are not claimed as passed. No backend source or database schema was changed.
- `git diff --check`: passed.
- Updated muted text token `#a0aab9` has calculated contrast ratios 8.04:1, 7.50:1, 6.64:1, and 6.22:1 against the four shared dark backgrounds. This is a token check, not a full accessibility certification.

## Browser evidence

Local source checkout served at http://127.0.0.1:5175. Read-only review covered Dashboard, Job Browser, Add Job, Companies, Scheduler, Crawl Tasks, OfferToday Keywords, AI Enrichment, Classification, and Settings at 1366×768 and 1440×900. No main-page horizontal overflow was observed across those twenty route/viewport combinations.

After screenshots and structured findings: `/tmp/uiux-screens/`, including `audit.json`, `jobs-1366.png`, `scheduler-1366.png`, and `ai-1366.png`. Initial screenshots were captured under `.playwright-mcp/` during planning. Temporary screenshots are local evidence, not committed product assets.

- Dashboard, Companies, and Settings use improved shared contrast/navigation without an unnecessary page rewrite. Dashboard and Companies received clearer purpose descriptions. Component tests cover their loading/error/state behavior; Companies now distinguishes failed list requests from successful empty results and supports same-query retry.
- Add Job now links successful intake to AI Enrichment and Job Browser; the result banner wraps on laptop widths.
- Classification uses English labels, more room for review, restored field focus outlines, and independent maintenance availability.
- Keyword management has English instructions, visible file input for keyboard access, loading feedback, retry, download errors, and successful-apply acknowledgement.
- Job Browser puts filters beside results and Jev below the main list. A failed new search leaves prior rows visible with an error instead of replacing the list.

## Coordinated live replacement — authorized and deployed

The user authorized replacing old services while retaining the business corpus, with an empty database only as a fallback if retention proved impossible. Retention succeeded, so the fallback was not used.

- Built all current Docker images before stopping old services.
- Disposable PostgreSQL/Redis rehearsal completed both required clean-start cycles (1 test passed).
- Real corpus exported/imported into `jobsdb_uiux_cutover_test`; all 20 retained table counts and content hashes matched, and current schema verification passed.
- Stopped all persistent application services and host Vite; saved a full restricted PostgreSQL dump, validated its archive manifest, then exported the quiescent corpus.
- Cleared runtime streams/schema using the existing operator commands; bootstrapped the current schema, imported retained rows, and verified exact retained identity/content plus empty runtime state before startup.
- Recreated the complete app/worker/sidecar/frontend containers. Bootstrap is a one-shot operation: Compose `start` attempted to repeat it on the imported database and correctly refused without mutation. After successful explicit bootstrap/retention verification, services were started with `up -d --no-deps`; no in-place schema bypass was introduced.
- Post-start immutable retained-table verification matched exactly. Source catalogs are the only contract-permitted mutable tables.
- Jobs: 15,537; Companies: 3,460; Skill assignments: 80,927; Skill mentions: 109,048; Skill Candidates: 12,964. JobsDB 7,209; CTGoodJobs 6,548; OfferToday 1,780.
- All ten live pages at both laptop viewports loaded without API HTTP failures, page exceptions, or main horizontal overflow. Primary controls were traversed with Tab and displayed focus indicators. Evidence: `/tmp/uiux-live-screens/audit.json` and page screenshots.
- Live health, maintenance status and Jev run routes return 200. Source-filtered lexical searches return exactly the three source counts above.
- Embedding rebuild uses the actual local all-MiniLM-L6-v2 model and current document builder/indexer, in disjoint Job-ID partitions, with per-batch commits. All 15,537 embeddings completed. Finalization verified immutable retention, exact schema, canonical registry and complete 384-dimensional embeddings, then deleted the transient artifact. No paid provider calls were used for this cutover.

Historical tasks/runs, schedules, queue state and database runtime settings were reset by the existing cutover contract. The business corpus was retained. `.env` remains unchanged. A full old database backup, including old settings, remains at `/Users/karashawy/.local/share/job-scraper/backups/2026-09-23-uiux/jobsdb-before-cutover.dump` (mode 0600, parent mode 0700). This is an operator safety copy, not a new application rollback/migration command.

## Page state coverage

| Surface | Evidence |
|---|---|
| Dashboard | Initial loading/failure/empty/recovery tests, partial stale refresh tests, live charts and navigation |
| Job Browser/detail | Explicit apply, pending edits, error retention, facet failures, page/layer restoration, manual detail save and related-job contracts; laptop E2E geometry |
| Add Job | Required fields, pending save, server failure with retained draft/idempotency, duplicate confirmation, successful links and reset |
| Companies | Initial loading/failure vs empty, same-query retry, list filtering/paging, run lifecycle and polling recovery, Web Search and regenerate confirmation |
| Scheduler/Crawl Tasks | Board/action and wizard tests, exact Task links, failures/cancellation acknowledgement, live empty runtime state |
| AI Enrichment | Empty eligibility E2E plus existing pending/active/failed/retry/stop tests, live retained-corpus counters |
| Classification | Loading/error/empty queue, missing taxonomy, independent maintenance failure, decision validation and success, maintenance/backfill E2E |
| OfferToday Keywords | Network failure/retry, filter-empty, valid/invalid CSV preview, explicit confirmation and success, download failure English copy |
| Settings | Initial loading/failure excludes editable form; provider save/422/probe tests, Jev and scraper-pacing E2E |

Live checks are read-only. Destructive actions, failure injection, and paid-provider outcomes are tested using disposable databases, component mocks, or network interception. No claim is made that every possible server failure or all external source/browser authentication paths were exercised live.

## Final review

API request shapes, route identities, storage keys, search semantics, server-owned actions, and paid-run confirmation behavior remain unchanged. The main session implemented and checked directly. Main UI commit is 6d686d00. Follow-up acceptance fixes and rollout evidence are ready for final commit; technical acceptance is complete. No GitHub issue closure or user manual QA approval is claimed.

## Regression findings during acceptance

- Keyword download failure had a remaining Chinese API-client message; translated to actionable English and asserted in E2E.
- Companies list failure also rendered the successful no-match message. The empty message is now suppressed while error is present; both list/poll errors use alert semantics. Search with an unchanged query on page one now reissues the read, allowing recovery. A regression exercises loading, failure, retry and empty success without starting enrichment.
- Two existing Jev rerank E2E scenarios read titles synchronously while an async list refresh was in flight under CPU load. Replaced snapshots with Playwright web-first exact-text/membership assertions and waited for the seeded baseline before recording it. Keyword success assertions now target the success status explicitly, since catalog loading can legitimately render a second status simultaneously. The expected titles/provider-call count were not relaxed.
- A 5-second Settings test timed out during concurrent suites and embedding computation; its unchanged behavior passed in a serialized focused run and the full 232-test serialized suite.

## Final live acceptance

- Final cutover result: `retention.matched=true`, `target.clean=true`, `artifact_deleted=true`. The full PostgreSQL safety backup remains in the persistent restricted directory.
- With rebuild jobs exited, semantic and hybrid Python searches both returned HTTP 200 with total 15,537; source-filtered lexical counts remained exact. Job detail returned 200 and related jobs returned five recommendations.
- During concurrent rebuilding, hybrid queries twice exceeded the existing 30-second proxy timeout; no timeout or ranking semantics were changed. Full-corpus hybrid ranking eagerly loads source graphs and embedding document text, a future optimization opportunity. Idle-state live verification passed.
- All persistent app services were replaced; API, frontend, retrieval, recommendation, Scrapyd, PostgreSQL and Redis health checks are healthy and all four workers are running. No old app process remains.
- No new external crawl or paid AI run was launched. External authentication/manual browser setup and provider configuration remain operator-dependent.
