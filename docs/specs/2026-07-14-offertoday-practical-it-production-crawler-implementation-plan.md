# OfferToday Practical IT Production Crawler Implementation Plan

**Date:** 2026-07-14

**Status:** Implemented; deterministic quality gate passed

**Authoritative specification:**
`docs/specs/2026-07-14-offertoday-practical-it-production-crawler-spec.md`

## 1. Outcome

Replace the abandoned Phase D-H research route with one production path that:

- discovers the practical IT result cohort with the response cursor;
- retains validated page-cap prefixes and continues later conditions;
- stages only new and repair candidates;
- skips complete and code-2520 canonical IDs;
- starts detail only after listing has finished across all conditions; and
- isolates production from the preserved research replay infrastructure after
  shared production code is separated.

No shadow, canary, soak, repeated census, or live research artifact is required
for adoption. Deterministic tests and the full backend quality gate are the
activation gate.

## 2. Implementation Principles

1. Keep the validated cursor parser, exact scalar checks, identity authority,
   response classification, and detail transaction behavior.
2. Keep candidate/artifact/repeat/window/stability machinery frozen for
   historical replay instead of adapting production to it.
3. Make production policies explicit at the standalone-crawl boundary.
4. Do not use a page cap as exhaustion evidence; report it as partial success.
5. Validate a page before any staging write.
6. Use bulk reads and one transaction per validated page; never query existence
   once per canonical ID.
7. Keep unrelated dirty-worktree changes untouched. In particular, do not
   delete or overwrite an already-modified file merely because it resembles
   research coverage.

## 3. Target Data Flow

```text
deterministic IT conditions
  -> search request page 1 (pageSize=10, rcdType omitted)
  -> validated response cursor
  -> page 2+ with exact cursor fields
  -> result/supplement cohort split
  -> result identity + response validation
  -> bulk DB classification
  -> immediate new/repair staging transaction
  -> natural exhaustion OR allowed page-cap partial
  -> next condition with fresh cursor
  -> all conditions finished
  -> one deduplicated new/repair detail cohort
  -> existing detail pipeline
  -> completed metrics
```

Any hard stop exits before the detail-cohort boundary.

## 4. Ordered Implementation Tasks

### Task 1. Replace the planning route and lock regression expectations

**Files:**

- `.trellis/tasks/07-13-offertoday-phase-d-cursor-census/{prd,design,implement}.md`
- `.trellis/tasks/07-13-offertoday-completeness-stability/{prd,design,implement}.md`
- the two 2026-07-14 production spec/plan documents
- `backend/tests/test_offertoday_search_space.py`
- `backend/tests/test_offertoday_listing_contract.py`
- `backend/tests/test_offertoday_listing_runner.py`
- `backend/tests/test_offertoday_standalone_crawl.py`
- `backend/tests/test_crawl_job_runtime.py`

**Work:**

1. Record that the old Phase D-H route is superseded, frozen, and retained only
   for historical replay.
2. Add failing production tests before changing behavior.
3. Preserve golden tests for the shared cursor parser, response classifier,
   identity authority, and detail transaction boundary.
4. Do not add or run a live research command.

**Gate:** The new tests precisely describe the production contract and fail for
the expected current gaps.

### Task 2. Freeze the production IT condition and request policy

**Files:**

- `backend/app/sources/offertoday/search_space.py`
- `backend/app/sources/offertoday/constants.py`
- `backend/app/sources/offertoday/listing_contract.py`
- `backend/scripts/offertoday_standalone_crawl.py`
- focused search-space/contract tests

**Work:**

1. Make default production IT categories, keywords, hybrids, and explicit
   keywords use the search endpoint.
2. Omit `rcdType` and request page size 10.
3. Add a small production cursor-policy factory or simplify the production
   request-policy path without changing preserved research callers. Production
   must not require research-only `repeat_index`, candidate, or artifact inputs.
4. Pass the explicit response-cursor policy and
   `result-transition-confirmation-v1` behavior to the listing runner.
5. Remove `DEFAULT_IT_UNIQUE_JOB_TARGET` and pass `unique_job_cap=None`.
6. Keep `max_pages=100` as the standalone default and interpret it per
   condition.
7. Update the runtime probe payload to use the same endpoint/size/`rcdType`
   policy, without turning the probe into an adoption gate.

**Tests:**

- every default IT family has `endpoint="search"` and `rcd_type is None`;
- page 1 has `pageSize=10` and no cursor fields;
- page 2 has exactly the prior page's four cursor fields;
- cursor state is reset between category, keyword, and hybrid conditions;
- production no longer constructs a 5,000-ID target cap; and
- a non-production diagnostic override must be explicit.

**Gate:** Production policy is one explicit code path and no default stateless
page-size-50 request remains.

### Task 3. Add explicit page-cap partial and immediate staging semantics

**Files:**

- `backend/app/sources/offertoday/listing_runner.py`
- `backend/app/sources/offertoday/listing_contract.py` as needed
- `backend/tests/test_offertoday_listing_runner.py`
- `backend/tests/test_offertoday_standalone_crawl.py`

**Work:**

1. Add `page_cap_behavior` to `ListingStopPolicy` with exact values
   `reject` and `retain-and-continue`; default to `reject`.
2. Add explicit run evidence for capped conditions, including condition IDs and
   counts. Preserve `is_complete=false` for a capped condition so it is never
   confused with natural exhaustion; expose a separate run-level partial-success
   predicate.
3. In production retain mode, stage each validated result page immediately.
   Do not hold all pages until natural condition completion.
4. On page cap, keep the condition's accepted IDs and staged rows, record the
   partial outcome, reset the cursor, and continue with the next condition.
5. Continue only for page cap. Every auth, WAF, IP, endpoint, cursor, identity,
   gap, or persistence stop remains terminal for the run.
6. Keep supplemental rows in observation evidence but exclude them from
   staging and accepted result IDs. Supplemental identity issues/conflicts are
   counted and excluded from supplemental sets; they do not stop production.
7. Ensure two cursor-continuous empty `resultList` pages produce natural
   completion even when supplemental rows are non-empty.

**Tests:**

- research/default `reject` still stops on page cap during the transition;
- production retain mode stages pages 1..100, marks exactly one capped
  condition, and runs the next condition from page 1 with no prior cursor;
- an early condition cap followed by later natural exhaustion produces one
  partial run with the union of both validated result cohorts;
- supplemental-only confirmation pages do not stage rows;
- malformed/conflicting supplemental rows increment observation counters but
  do not stop or defer a result ID;
- cursor, identity, and unresolved-gap stops never continue; and
- a late hard stop retains prior committed diagnostics but creates no detail
  cohort.

**Gate:** Page cap is the only incomplete condition that can continue and later
finish the crawl as partial-completed.

### Task 4. Move and simplify the production staging sink

**Files:**

- create `backend/app/services/offertoday_listing_staging_service.py`
- `backend/app/services/offertoday_research_staging_service.py`
- `backend/scripts/offertoday_standalone_crawl.py`
- `backend/app/services/crawl_job_runtime.py`
- staging/runtime tests

**Work:**

1. Move `build_offertoday_listing_staging_payload`, reconciliation evidence,
   and `OfferTodayReconciledListingStagingSink` into the production-named
   module.
2. Rename the production alias so no production file imports a
   `*_research_*` module.
3. Extend the sink result with distinct canonical classifications and counters.
4. Keep the advisory transaction lock and one commit/rollback boundary per
   batch.
5. Leave `ResearchNoop*` staging classes available to historical replay; the
   production crawler must not import them.

**Gate:** The standalone crawler has no runtime dependency on a research-named
service.

### Task 5. Implement bulk complete/terminal/new/repair classification

**Files:**

- `backend/app/services/crawl_job_runtime.py`
- `backend/app/repositories/job_repository.py`
- `backend/app/repositories/crawl_job_listing_repository.py`
- `backend/app/sources/offertoday/completeness.py`
- `backend/app/models/crawl_job_listing.py` only if a later reviewed migration
  becomes necessary
- `backend/tests/test_crawl_job_runtime.py`

**Work:**

1. Add one batch-classification operation for canonical OfferToday IDs.
2. Perform exactly one `JobRepository.list_existing_jobs_by_source_ids()` call
   per page batch.
3. Bulk-load current-crawl staging IDs and historical terminal/identity blockers
   without per-ID reads.
4. Apply precedence: identity conflict -> code-2520 terminal -> complete
   existing -> repair -> new.
5. Use `is_complete_offertoday_job()` for published Job completeness.
6. Stop treating every historical staged ID as an unconditional skip. Only a
   current-crawl duplicate, terminal outcome, identity conflict, or complete Job
   blocks a new current-crawl pending row.
7. Insert or update one current-crawl pending row for each new or repair ID.
8. Add `detail_target_kind` (`new` or `repair`) to staging JSON metadata and
   return exact canonical ID sets/counters.
9. Fail the transaction on database lookup errors; never turn an exception into
   "nothing exists".
10. Keep the implementation migration-free unless a concrete query/recovery
    invariant cannot be represented in existing staging JSON.

**Tests:**

- one bulk Job lookup for ten IDs and zero calls to per-ID lookup helpers;
- one bulk blocker/current-staging lookup path, not ten individual queries;
- complete existing creates no current row;
- historical terminal 2520 creates no current row;
- new creates one pending `detail_target_kind=new` row;
- incomplete existing creates one pending `detail_target_kind=repair` row;
- eligible failed history produces repair, while identity-conflict history
  hard-stops;
- duplicates across pages/conditions create one current-crawl row; and
- lookup/write/event failure rolls back the whole page batch.

**Gate:** Every validated canonical ID has one deterministic classification and
the classification counters conserve the batch union.

### Task 6. Freeze detail targets only after all listing conditions

**Files:**

- `backend/scripts/offertoday_standalone_crawl.py`
- `backend/app/services/crawl_job_runtime.py`
- `backend/app/services/offertoday_detail_pipeline.py` only for regression
  guards, not an API redesign
- standalone/runtime/detail tests

**Work:**

1. Remove detail-target loading from any per-condition or early-return path.
2. After all conditions are natural or page-cap partial, query current-crawl
   eligible rows once and group by canonical ID.
3. Preserve one network target per canonical ID after identity authority audit.
4. Expose `new_detail_targets` and `repair_detail_targets` on
   `DetailTargetLoadResult` and production metrics.
5. Ensure complete, terminal, supplemental-only, duplicate, and conflict IDs
   have zero network requests.
6. Allow a page-cap-partial full crawl to proceed to detail.
7. Prevent every hard-stopped crawl from loading or executing detail.

**Tests:**

- runner/condition events for all conditions precede the first detail-target
  lookup;
- a partial listing run loads new and repair targets after the final condition;
- new and repair each produce exactly one target;
- complete and terminal IDs produce zero targets;
- identity conflict stops before target freeze; and
- listing-only mode completes without detail while retaining the same listing
  metrics.

**Gate:** The listing/detail boundary is explicit and test-observable.

### Task 7. Add partial and incremental observability

**Files:**

- `backend/scripts/offertoday_standalone_crawl.py`
- `backend/app/services/crawl_job_runtime.py`
- `backend/app/repositories/crawl_job_repository.py` only if generic metric
  merging needs a correction
- production progress/status tests

**Work:**

1. Populate every metric required by the specification.
2. Emit capped-condition outcomes and one final `listing_completed` event with
   partial summary.
3. Mark page-cap-only runs `completed`, not `failed`.
4. Preserve manual-action status for auth/WAF/IP and identity audit.
5. Preserve failed status for cursor/endpoint/page, unresolved-gap, and staging
   failures.
6. Report detail success/failure separately from terminal unavailable and manual
   action.
7. Keep the existing untyped JSON metrics schema; do not add a migration merely
   for counters.

**Gate:** Status, event order, and counters match the exact accepted ID and
detail-target sets in tests.

### Task 8. Preserve historical research and isolate production

**Precondition:** Tasks 2-7 pass focused production tests and the standalone
crawler imports no research module.

**Preserve:**

- `backend/app/sources/offertoday/research/`;
- `backend/app/services/offertoday_research_live_service.py`;
- `backend/app/services/offertoday_research_observation_service.py`;
- `backend/app/repositories/offertoday_research_repository.py`;
- `backend/scripts/offertoday_research.py`;
- `backend/scripts/offertoday_research_census.py`;
- research-only Phase A-H, pagination, partition, census, dual-cohort, artifact,
  stage-gate, schema, verifier, and replay tests;
- superseded 2026-07-13 research specifications and task content; and
- ignored local `backend/runtime/offertoday-research/` artifacts.

**Work:**

1. Search production imports and CLI references to prove the standalone path
   does not depend on a research-named package, service, schema, or verifier.
2. Keep production cursor, response, identity, staging, and status regressions
   in production test modules while leaving historical research tests intact.
3. Restore any historical research spec or decision document accidentally
   deleted while the earlier deletion route was being considered.
4. Keep research self-dependencies and exact experiment/verifier wiring so
   saved artifacts remain replayable; do not add new phases or production use.
5. Update only stale production documentation that still instructs deletion.
6. Preserve unrelated modified files and all ignored runtime evidence. Do not
   issue a live research request.

**Consequence:** Historical runtime artifacts remain replayable by the current
checkout, while the production crawler has a smaller and auditable import
surface.

**Gate:** No production import points at research-only code; Python import and
collection succeed; targeted reference checks show research references only
inside the preserved replay stack, its tests, and historical documentation.

### Task 9. Final deterministic quality gate and activation

Run, in order:

```powershell
python -m pytest -q `
  backend/tests/test_offertoday_search_space.py `
  backend/tests/test_offertoday_listing_contract.py `
  backend/tests/test_offertoday_listing_runner.py `
  backend/tests/test_offertoday_browser_runtime.py `
  backend/tests/test_offertoday_detail_pipeline.py `
  backend/tests/test_offertoday_canonical_and_identity.py `
  backend/tests/test_crawl_job_runtime.py `
  backend/tests/test_offertoday_standalone_crawl.py

python -m ruff check <touched-python-files>
python -m py_compile <touched-python-source-files>
python -m pytest -q backend/tests
git diff --check
```

Also verify:

- no production caller constructs page size 50/stateless IT listing defaults;
- no production caller imports OfferToday research services or packages, while
  the historical replay stack and ignored artifacts remain present;
- no migration, frontend, Compose, or detail API file changed unless an explicit
  implementation amendment documents why; and
- unrelated worktree changes remain byte-for-byte untouched.

There is no live canary or soak gate. After this deterministic gate passes, the
changed standalone path becomes the development production default.

## 5. Recommended Commit Boundaries

1. `docs(offertoday): replace census research with practical IT crawl`
2. `feat(offertoday): use production cursor listing and partial caps`
3. `feat(offertoday): classify incremental detail targets in bulk`
4. `refactor(offertoday): isolate preserved research infrastructure`

Each commit must pass its focused tests. Run the complete backend suite after
the final isolation/refactor commit.

## 6. Rollback

No runtime feature flag is introduced. Rollback is a normal Git revert of the
production behavior commits. The database schema remains unchanged by default,
so rollback requires no down migration.

If implementation later adds a reviewed migration, it must include an explicit
downgrade and data-preservation note before merge.

## 7. Completion Definition

The task is complete only when:

1. production listing uses search + omitted `rcdType` + page size 10 + the
   response cursor for every IT condition;
2. page caps are retained, continued, and reported partial without swallowing a
   hard stop;
3. every page batch is classified without N+1 reads;
4. complete and terminal IDs are skipped while new and incomplete/failed IDs
   each receive one detail target;
5. detail begins only after all listing conditions finish naturally or
   partially;
6. required status and metrics are correct;
7. historical research code, tests, schemas, verifier, specs, and artifacts are
   preserved after production is isolated from them; and
8. focused tests, full backend tests, Ruff, compilation, and diff checks pass.
