# Automated Classification QA report

> Historical note: Job Taxonomy evidence in this completed QA record is kept
> for traceability but its active product scope is superseded by
> `07-29-remove-canonical-job-taxonomy`. Company Industry, Skill, and shared
> lifecycle findings remain active.

## Overall result

**Fail — three confirmed product defects (#36, #37, #38).** Shared batch
lifecycle safety, Stop, active-run exclusion, cross-domain
independence, failure isolation, Retry lineage, and transaction rollback all
behaved correctly in the exercised sandbox paths.

## Scope

Backend classification-batch behavior exercised primarily through the local
Automated Classification UI. GitHub umbrella: #32.

## Environment baseline

- Started: `2026-07-27T22:14:40+08:00`
- Branch: `codex/offertoday-it-coverage-20260702`
- Frontend: `http://localhost:3000` (`200`, Docker service healthy)
- Backend: `http://localhost:8000` (`/docs` returned `200`, Docker service
  healthy)
- Database: local PostgreSQL `jobsdb` on port 5433 (healthy)
- LLM: selected Jobs provider `custom`; selected key present; last connection
  status `passed` at `2026-07-27 13:51:43.914836`
- Active classification runs at readiness: none
- Worktree was already dirty with unrelated user changes before QA. Product
  files are not to be modified by this task.

### Candidate inventory at execution start

| Domain | Source/scope | Eligible count |
|---|---|---:|
| Job Taxonomy | jobsdb | 4,278 |
| Job Taxonomy | offertoday | 11,921 |
| Job Taxonomy | ctgoodjobs | 3,429 |
| Company Industry | jobsdb | 1,205 |
| Company Industry | offertoday | 3,081 |
| Company Industry | ctgoodjobs | 1,017 |
| Skills | unresolved at threshold 20 | 527 |

The Settings threshold changed from the planning-time value of 5 to 20 before
execution. All execution evidence uses the current value 20; this state drift
is not itself treated as a defect.

## Automated baseline

| Check | Result | Evidence |
|---|---|---|
| Focused Classification UI component test | Pass | 3/3 tests, Vitest, 1.02s |
| Core classification batch backend tests | Pass | 10/10 tests, pytest in `backend-api`, 0.71s |
| Current taxonomy backend tests | Pass | 14/14 tests, pytest in `backend-api`, 2.67s |

## Contract matrix

| Area | Contract | Result | Evidence/run ID |
|---|---|---|---|
| Shared | Preview payload/filter/limit | Pass | E-003; requests 41-55 |
| Shared | Unchanged-scope preview/start parity and stable snapshot | Pass | E-004; run `6d9a8bd7...` |
| Shared | Preview invalidation after scope edit | Fail | E-009; issue #37 |
| Shared | Same-domain active-run exclusion | Pass | E-007; 409 names run `daba1aba...` |
| Shared | Cross-domain independence | Pass | E-007; overlapping Job/Skill runs |
| Shared | Cooperative Stop/count consistency | Pass | E-007; run `daba1aba...` |
| Shared | Failure isolation and failed-only Retry | Pass | E-005; runs `ad241aa3...`, `5e9c8c9f...` |
| Job Taxonomy | Eligible Source-filtered selection | Pass | E-003; requests 41-44 |
| Job Taxonomy | Current assignment/no fallback | Pass | E-004; `6d9a8bd7...` |
| Company Industry | Eligible Source-filtered selection | Pass | E-003; requests 46-49 |
| Company Industry | Mapped Source evidence/no guessing | Pass/limited | E-005; no eligible mapped-evidence success exists |
| Company Industry | Supported mapping setup/operability | Fail | E-010; issue #38 |
| Skills | Threshold selection/no Source filter | Pass | E-003; request 51 and SQL cross-check |
| Skills | Reuse/reject/create atomic behavior | Fail/limited | E-006/E-008; issue #36 |
| UI persistence | Polling, terminal history, reload | Pass | E-004/E-007 |

## Evidence log

### E-001 — Readiness gate

- All core Docker services were running; frontend, backend, and PostgreSQL were
  healthy.
- Chrome DevTools, Playwright, PostgreSQL, and GitHub connections were verified.
- No active classification run existed at the start of execution.
- Candidate inventory was sufficient for all three real domain attempts.

### E-002 — Automated baseline

- `cd frontend && npm test -- --run src/components/classification/ClassificationBatchesPage.test.jsx`
  passed all three tests. Vitest emitted only the environment warning that
  `localStorage` was unavailable.
- The host did not provide a `pytest` executable, so the backend suite was run
  in the mounted `backend-api` container:
  `docker compose exec -T backend-api pytest -q tests/test_classification_batch_runtime.py`.
  All ten tests passed. Two SQLAlchemy warnings concerned deprecated
  `datetime.utcnow()` behavior and were not failures.
- The broader taxonomy suite was run in the same container:
  `docker compose exec -T backend-api pytest -q tests/test_current_taxonomies.py`.
  All fourteen tests passed.

### E-003 — UI-driven preview, Source, threshold, and limit matrix

- Job Taxonomy preview with limit 3 returned three candidates for all Sources,
  jobsdb, offertoday, and ctgoodjobs. Requests 41-44 sent respectively
  `source_sites: []`, `["jobsdb"]`, `["offertoday"]`, and `["ctgoodjobs"]`;
  every returned item matched the requested Source.
- Company Industry requests 46-49 repeated the same matrix and every returned
  Company matched the requested Source.
- Skills request 51 sent `filters: {}` even though the preceding Company view
  had ctgoodjobs selected. The returned IDs exactly matched the first three
  unresolved candidates from the read-only threshold/order query. Live ingest
  increased two distinct-Job counts between preview and SQL inspection, but
  candidate identity and order remained stable.
- Limit 1 returned one item. Limit 5000 was accepted and returned the current
  bounded Skill candidate count (530 at request time).
- Limits 0 and 5001 produced HTTP 422 and visible assertive alerts with the
  backend validation messages. Preview was cleared and Start stayed disabled.
- The browser reported one non-blocking accessibility issue: the numeric form
  field has no `id` or `name`. This is outside the backend-focused scope unless
  it impedes later interaction.

### E-004 — Real Job Taxonomy run

- UI preview request 58 selected one jobsdb Job,
  `c3b1dd78-ab77-4926-927b-5af3230e66c8` (Network Operations Center Manager),
  which the baseline query proved had no current assignment.
- UI start request 59 repeated the same filter and limit and persisted the same
  subject as the sole stable run item in run
  `6d9a8bd7-5a8e-4f5c-8799-3ffaf0097bbc`.
- The UI moved from running 0/1 to completed 1/1. PostgreSQL agreed on completed
  counts and one attempt.
- The Job received active, assignable current code
  `information_communication_technology.infrastructure_support.network_engineering`
  (`Network Engineering`) with method `constrained_ai` and a non-empty evidence
  hash. No fallback node was involved.

### E-005 — Real Company Industry failure and failed-only Retry

- UI preview request 64 selected jobsdb Company
  `6bbb9dab-063c-417e-af28-e64295239464` (Ricoh Hong Kong Limited), which had no
  current assignment. Its three preserved Jobs had neither
  `company_industry` nor `industry.name` Source evidence.
- Run `ad241aa3-4061-4c5d-a839-8b255c99fea3` failed exactly one item with
  `Company has no mapped source-industry evidence`. The UI exposed the same
  reason and enabled failed-only Retry; no Company assignment was written.
- UI Retry created run `5e9c8c9f-468b-4310-98d2-174abb622305` with
  `retry_of_run_id` pointing to the original run, the same sole subject, and the
  same filters. It failed cleanly again with no assignment.
- Read-only inspection found no currently eligible unassigned Company in any
  Source whose preserved Job label resolves through a current Company Industry
  mapping. Consequently the no-guess failure path is fully proven, while the
  successful mapped-evidence path is limited to automated coverage for this
  dataset.

### E-006 — Real Skill confirmed-path creation

- UI preview request 72 selected unresolved candidate
  `27d47e84-08af-44f9-8667-bf2b4939ece5` (SQL服務器管理, normalized `sql`) above
  threshold 20. Baseline inspection found no exact active Skill name/code/alias
  match.
- Run `ad6ee2a6-7928-4177-bcf2-c61c80ed76e4` completed 1/1 through the real
  configured LLM path.
- The transaction created active assignable Skill `database.sql.sql` (`SQL`)
  beneath active Technology `database.sql` and Category `database`, resolved
  the Candidate, resolved 488 active origin Mentions, and projected 492 Jobs.
  The UI and database both reported one completed item and no failures.

### E-007 — Active-run exclusion, cross-domain independence, and Stop

- Two independent UI sessions previewed the same 20-item jobsdb Job Taxonomy
  scope before either started. The first created run
  `daba1aba-f424-403a-aaca-c4d00936a427`.
- The second UI session attempted the same-domain Start and received HTTP 409
  with code `active_classification_batch_exists`, domain `job_taxonomy`, and the
  exact active run ID. No duplicate run was created.
- While the Job run was active, a third isolated UI session successfully created
  Skill run `99612684-6f9e-452b-a5f2-1b403aa9495c`. It started and completed
  execution in a terminal `failed` state before the Job run completed, proving
  cross-domain independence despite its item-level classification failure.
- Stop was requested about 1.6 seconds after the Job run started. The UI exposed
  `stopping` and then terminal `cancelled`, with 1 completed and 19 cancelled.
  PostgreSQL contained exactly 20 stable item rows, one assignment for the
  completed item, and no assignment for any cancelled item. Count sums matched
  the total.
- Reloading the UI recovered the same cancelled run ID and 1/0/19 aggregate
  counts, proving terminal history persistence.

### E-008 — Localized generic Skill failure

- The cross-domain run selected candidate
  `f77f0b89-09b6-451f-84eb-30b5b51f922a` (`項目管理`, 266 distinct Jobs).
  Project Management is an explicit generic-term contract, but this localized
  form entered the LLM/create path and failed with
  `Skill candidate name cannot produce a stable code`.
- Failed-only Retry created run `42f1e31c-67bf-457e-8c25-c29a25eb23d9` with
  correct lineage but failed again, this time as uncertain placement. The
  Candidate remained unresolved and no partial Skill node was written.
- Confirmed defect filed as #36:
  `https://github.com/HawyHoWingYam/JOB_SCRAPER/issues/36`.

### E-009 — Stale preview can start a different scope

- UI preview request 147 selected jobsdb Job
  `c684409d-9629-4f69-b65b-09baf4e59a16` with limit 1.
- Without previewing again, the Source selection was changed to OfferToday. The
  old `这次会处理 1 项` message remained and Start stayed enabled.
- UI Start request 148 sent the newly edited OfferToday scope and run
  `b21a89e2-5b62-43f2-91f2-1f5c7db1c624` snapshotted different Job
  `00286319-5aa2-4831-b733-e19a20ec86c3` (`programmer`). It completed and wrote
  active assignable current code
  `information_communication_technology.software_development.full_stack_development`.
- Backend snapshotting was correct; the operator confirmation was stale.
  Confirmed defect filed as #37:
  `https://github.com/HawyHoWingYam/JOB_SCRAPER/issues/37`.

### E-010 — Company Industry has no mapping setup path

- Current state contains 5,303 eligible unassigned Companies, 4,194 OfferToday
  Jobs with preserved raw industry labels, zero Company Industry mappings, and
  zero Company Industry assignments.
- Production projection consumes current mappings but no production seed,
  import, API, or UI creates them; only tests insert mappings. Therefore every
  current Company candidate is guaranteed to fail even though the no-guess
  transaction behavior is correct.
- Confirmed defect filed as #38:
  `https://github.com/HawyHoWingYam/JOB_SCRAPER/issues/38`.

### E-011 — Additional localized Skill batch

- A final approved three-item UI run
  `d8239112-2688-4c74-a26b-8d258f82bb23` selected 項目管理, 銷售, and 客戶服務.
  All three failed; two were uncertain placements and 客戶服務 could not produce
  a stable code. All remained unresolved and no partial Skill nodes were written.
- This corroborates #36 as a broader durable-outcome problem for localized
  high-frequency candidates; the evidence was appended to that issue.

### E-012 — Completion verification

- Focused UI tests were rerun after interactive QA: 3/3 passed in 1.38s.
- Core batch tests were rerun: 10/10 passed in 1.38s, with the same two
  `datetime.utcnow()` deprecation warnings.
- Broader current taxonomy tests passed 14/14 in 2.67s.
- All nine QA-created runs were terminal at completion: three completed, five
  failed by explicit item contracts, and one cooperatively cancelled. No
  `pending`, `running`, or `stopping` run remained.
- Console review found only deliberately triggered HTTP 422 monitoring entries
  and the non-blocking missing `id`/`name` form-field issue; no unexplained
  runtime error remained.

## Confirmed defects

- #36 — Localized generic Skill candidates remain in the retry loop.
- #37 — Classification settings can change after Preview without invalidating
  Start.
- #38 — Company Industry batches have no supported source-mapping setup path.

Each issue body records #32 as its Parent issue; #32 also contains the final QA
summary and links to all three defects.

## Blocked or limited scenarios

- Company Industry success could not be exercised interactively because the
  sandbox has zero mappings and no supported setup path (#38). The
  failure/no-guess contract was exercised; success remains covered by automated
  taxonomy tests.
- Skill exact-alias reuse was not encountered. Confirmed-path atomic creation
  succeeded; localized generic rejection was encountered and failed as #36.

## Residual risks

- Pending-run Stop could not be timed through the UI because background
  execution starts immediately; the focused backend test covers it.
- An empty preview could not be produced naturally with the current abundant
  sandbox data; Start gating was verified before preview and after 422 errors.
- Skill exact-name/code/alias reuse was not naturally selected; focused backend
  tests cover it.
- Company mapped-evidence success remains blocked by #38 and is covered only by
  automated taxonomy tests.
- Browser UI tests are interactive evidence only; the repository still has no
  real-backend Playwright/Cypress regression suite.
