# Implementation plan

Status: awaiting final plan review. No implementation authorization or task activation is implied by these artifacts.

## Work map and dependencies

Create child tasks from this umbrella after plan approval, with scoped PRDs and testable acceptance. Keep issue #79 as integration/source requirements. Each child remains independently reviewable; parent linkage alone does not encode dependencies.

| Work package | Requirements | Dependencies | Acceptance focus |
| --- | --- | --- | --- |
| A: Independent AI Skills and provenance | R1, R5 | None | Usable AI baseline without Jev, corrections/manual precedence, unchanged/changed evidence |
| B: Manual Jev batch orchestration | R3, R6, R8, R9 | A for Skill adapter | Explicit dispatch, frozen preview/start, no local monetary gate, stop/restart/manual retry |
| C: Persisted Jev Related Jobs | R4 | A effective Skills; B dispatch | Bounded ranking/filtering, empty success, stale fallback and history |
| D: Unified Jev operations UI | R3, R6, R8 | B and C contracts | One-click selected Job operations; all other manual tools; no scattered execution controls |
| E: Experience labels and search contract | R2 | #61 for inferred windows/provenance, not explicit labels | Card/detail parity, original range evidence, unchanged overlap membership |
| F: Search consistency fixes and measured review | R7 | Independent baseline fixes; D for relocated Jev controls | Draft/applied mode, stale guards, capability failure, export/count parity |

Suggested sequence: A -> B -> C -> D. E/F can be developed separately; integrate all before parent acceptance. Do not silently mark #61 complete or absorb its repair work.

## Ordered checklist

- [x] Review/approve this plan; create scoped children and linked issues, recording the dependencies above.
- [x] For each child, load trellis-before-dev and exact affected layer specs; complete its PRD/design/checklist before activation.
- [x] A: regression for Jev-disabled ordinary enrichment; implement baseline persistence and effective projection precedence; protect manual additions/removals; verify stale-source races and empty results.
- [x] B: inspect current queue/run recovery and remove every implicit Jev initiation/retry path. Add durable operation composition, provider-free preview, idempotent bounded start, and per-item eligibility. Remove local monetary settings/ledger/gates while retaining provider receipts. Test stop/restart/force/retry and ambiguous provider failures.
- [x] C: add typed bounded Related Jobs judgment and durable read-state composition. Test successful empty versus failure, subject/candidate drift, deleted candidates, missing embeddings, invalid provider IDs, and failure after earlier success.
- [x] D: implement central authoring and monitoring with prefilled links, migrate independent tools and smoke execution, and remove old execution controls. Keep duplicate human review and advisory readouts accessible.
- [x] E: align with #61's authoritative provenance/window contract; add search-card fields and shared formatter; update filters and detail evidence; parameterize cross-mode/facet/export membership tests.
- [x] F: separate draft/applied mode, fence Jev previews/results, handle capability failures; retain progressive facets and successful scope restoration. Measure representative experience queries before any performance-specific changes.
- [x] Update Jev, taxonomy, enrichment, frontend operations, and search specs to reflect final implemented contracts, especially manual restart/retry and page ownership.
- [x] Run integrated fake-provider browser scenarios and full relevant quality checks; reconcile requirement coverage and #61-dependent limitations before final handoff.

## Validation commands and scenarios

Use the repository's configured Python environment; all persistence tests must target disposable PostgreSQL `_test` databases per backend database guidelines. Read each test harness configuration before invoking it. Commands below are an execution plan, not claims of tests already run.

From `backend/`:

```bash
python3 -m pytest tests/test_ai_enrichment_runs.py tests/test_jev_online_skill_runner.py tests/test_jev_duplicate_association.py tests/test_job_search_facets.py
python3 -m ruff check app tests
```

Add the new batch/projection/Related Jobs suites to the targeted invocation once their files exist. Expand to relevant suites after the targeted checks pass, rather than repeatedly running unrelated tests.

From `frontend/`:

```bash
npm test -- src/components/JobBrowser.test.jsx src/components/JobDetailModal.test.jsx src/components/FilterPanel.test.jsx
npm run lint
npm run build
```

Include new Jev console/shared formatter tests and isolated Playwright scenarios in the implementing child. Frontend has no dedicated typecheck script; build/lint are the existing gates, not substitutes for backend contract tests.

Mandatory scenarios: provider-call counters stay zero without manual start; all three Job operations in one bounded batch; explicit dispatch succeeds without local monetary configuration; partial failure with successful results retained; explicit retry only failed items; stop prevents new dispatch; service restart requires manual resume; provider receipt cost is optional audit data; effective Skills feed search/recommendations; unchanged and changed evidence; current empty recommendation result versus stale/failure; experience `[1,2]` and `[1,5]` against query `[3,4]`; mode draft/failure/export parity; stale preview arrival after new scope.

Read-only performance baseline (after confirming local API target):

```bash
python3 backend/scripts/benchmark_job_search.py --runs 3
```

Extend this benchmark for experience-window payloads as necessary and collect PostgreSQL plans; no invented budgets or before/after claims. Finish artifact/code review with `git diff --check` and Trellis task validation as applicable.

## Risk and rollback points

- Projection replacement currently supersedes mentions: protect historical AI/Jev/operator provenance before changing writes.
- Current scheduled/recovery paths may redispatch work: fence them before enabling new orchestration, including historical queued work.
- A combined batch is not one database transaction across network calls: checkpoint each safe outcome and keep operation dependencies explicit.
- A lost provider response may still cost money: preserve the ambiguous attempt receipt and avoid automatic replay; the provider console owns monetary accounting.
- Search card schema additions and mode changes must preserve existing consumers, independent facets, and export scope.
- Rollback disables new dispatch/UI while retaining data/receipts and manual-only restrictions. Do not restore automatic Jev work or drop source evidence.

## Final review gate

User review should cover Settings retaining credential/default configuration, unified-page execution ownership, inclusion of the three concrete search fixes, child-task boundaries, and #61 dependency. Once approved, perform PRD convergence against the approved artifacts before `task.py start` on the first implementation child.
