# Implementation plan: Clarify scoped Job Intelligence Governance review selection

Do not begin Phase 2 until this plan and `design.md` have been reviewed and the
task has been activated with `task.py start`.

## Phase 1 — Backend read contract

- [x] Extend `CanonicalReviewItemView` and `CanonicalReviewItemSchema` with
      nullable `job_title` and `company_name` fields.
- [x] Add a read-model helper that bulk-loads Job title and Company name for a
      set of review Job IDs, and compose those values into list/detail views
      without per-item queries or changes to pagination/count semantics.
- [x] Keep missing/deleted display data safe: use nullable API fields and make
      the frontend fallback non-empty while retaining the exact Job UUID in
      technical detail.
- [x] Update the canonical backend/frontend fixtures and contract schemas so
      fixture equality remains exact.
- [x] Add backend assertions for list/detail labels and stable pagination/filter
      behavior in the existing canonical API/read-model tests.

## Phase 2 — Preserve readable scope context

- [x] Extend `governanceScope()` to carry the exclusion detail's human-readable
      source classification name as display-only metadata.
- [x] Extend `parseGovernanceHash()` / `governanceHash()` to safely parse and
      serialize the label without treating it as an API filter or repair input.
- [x] Update the AI Enrichment link tests and governance route tests to verify
      the label survives deep links alongside the authoritative IDs, reason,
      dates, pending limit, and bounded Job IDs.

## Phase 3 — Queue/detail guidance

- [x] Update the canonical queue adapter to render Job title as the primary
      label and Company name/reason as metadata, with a readable fallback.
- [x] Update `EvidencePanel` to show title/company as the human identity and
      move the exact UUID into the existing collapsed technical evidence area.
- [x] Extend the scoped banner to show the source, human category label,
      technical category ID, reason, and explicit batch-entry guidance.
- [x] Replace the generic scoped idle detail copy with the approved short
      explanation; keep unscoped behavior understandable and unchanged.
- [x] Do not auto-select the first row; retain current route/focus, narrow Back,
      page, empty-scope, provenance inspect/apply, and decision behavior.
- [x] Add or update frontend tests for title/company rows, UUID technical detail,
      scoped banner/idle guidance, no first-row selection, and fallback labels.

## Phase 4 — Quality gate

- [x] Run focused frontend tests for AI Enrichment, governance routing, and
      Job Intelligence Governance page.
- [x] Run focused backend canonical API/read-model and fixture contract tests
      in the project's disposable `*_test` PostgreSQL environment.
- [x] Run frontend lint and build.
- [x] Run the relevant backend test files individually if collection causes the
      documented incompatible-fixture interaction.
- [x] Perform browser-level verification of the exact Issue 13 path:
      AI Enrichment → OfferToday → IT exclusion → scoped governance queue →
      readable title/company rows → scoped guidance → select any row → inspect
      evidence/technical UUID → verify batch-level provenance action context.
- [x] Check desktop and narrow layouts, long CJK/English labels, empty/missing
      display labels, direct deep links, page navigation, keyboard focus, and
      zero horizontal overflow.

## Quality gate evidence

- Frontend focused tests: 47 passed; full suite: 37 files / 211 tests passed.
- Frontend lint and production build passed.
- Backend canonical API and response-contract tests passed in the project
  container with `/frontend:ro` mounted: 9 passed, 22 skipped; backend Ruff
  passed.
- Browser QA covered the direct scoped deep link, display-only label absence
  from queue API requests, no-first-row selection, fallback labels, technical
  UUID disclosure, CJK scope copy, narrow Back focus restoration, and zero
  horizontal overflow. The AI Enrichment link serialization is covered by the
  focused AI Enrichment and route tests.
- During browser QA, explicit narrow Back focus restoration exposed a timing
  race; the page now defers that one focus target until the route has returned
  to the queue. Decision-completion search focus remains unchanged.
- Read-only local verification found that `offertoday:118000` is the actual
  OfferToday Information Technology category (37 eligible recovery Reviews),
  while `offertoday:121000` is Manufacturing / Logistics (0 eligible recovery
  Reviews). The scoped QA fixture was corrected accordingly. Persisted run
  exclusion links now retain the source-qualified category ID instead of
  falling back to source site plus a display label.

## Risk points and rollback

- Risk: adding Job/Company labels introduces N+1 reads. Mitigation: assert the
      read model uses one bulk projection lookup for list pages and one lookup
      for detail; do not dereference `row.job` in a loop.
- Risk: display label is mistaken for scope authority. Mitigation: keep it out
      of `GOVERNANCE_AREA_ADAPTERS.loadQueue()` and backend scope filters; test
      request arguments explicitly.
- Risk: removing UUID from queue harms exact support. Mitigation: retain it in
      selected-item technical evidence and assert it in detail tests.
- Risk: prominent guidance duplicates or obscures context. Mitigation: reuse
      the existing scope banner, keep copy concise, and retain the queue's live
      `Showing N of M matching items` count.
- Rollback: revert the additive API/view/fixture and presentation changes.
      No database, pending-selection, or provenance-repair state needs rollback.

## Validation commands

From `frontend/` (use the repository's package manager scripts):

```bash
npm test -- src/components/ai/AIEnrichmentPage.test.jsx src/components/jobIntelligence/governanceRoute.test.js src/components/jobIntelligence/JobIntelligenceGovernancePage.test.jsx
npm run lint
npm run build
```

From the repository root, run the focused backend canonical API/read-model and
response-contract tests using the normal backend environment. PostgreSQL tests
must use `JOB_INTELLIGENCE_TEST_DATABASE_URL` pointing to a disposable database
whose name ends in `_test`.

## Approved follow-up implementation plan

### Phase 5 — Classifier provenance and failure taxonomy

- [x] Expose an explicit stable model version in the Job LLM runtime status;
      use a pinned model identifier only when it is the version authority.
- [x] Keep classifier provenance fail-closed when provider, model name, model
      version, or evidence references are absent.
- [x] Preserve bounded upstream retries and expose a distinct
      `ai_upstream_failed` diagnostic instead of converting provider failures
      into `classifier_output_invalid`.
- [x] Add tests for complete provenance, missing provenance, malformed JSON,
      semantic invalid output, transient retry exhaustion, and exact replay.

### Phase 6 — Canonical-only historical re-evaluation

- [x] Add a read-only preview that groups the selected scope by stable reason
      and returns a sample plus taxonomy/mapping/scope fingerprints.
- [x] Add a trusted-local preview/confirm/apply operation for only
      `classifier_output_invalid` and `classifier_provenance_missing`.
- [x] Reuse current Job title/description and governed target slices; do not
      rerun Skills, Summary, or Experience enrichment.
- [x] Process the confirmed snapshot asynchronously in bounded chunks with
      progress, resumability, per-Job idempotency, audit, outbox, and stale
      scope protection.
- [x] Automatically assign only valid existing governed targets with complete
      provenance. Leave unresolved Jobs active in Review.
- [x] Provide a retry-failed-items operation for `ai_upstream_failed` only.
- [x] Do not add bulk `insufficient evidence` or direct source crawling.

### Phase 7 — Guided recovery UI and verification

- [x] Add one AI Taxonomy Recovery entry point that presents reason counts,
      preview/confirm, progress, and retry-failed controls.
- [x] Keep Source Catalog provenance repair separate and report-first; make
      missing Source paths informational with an external recollection/rebuild
      instruction.
- [x] Verify source-qualified IDs remain the sole scope authority, display
      labels remain informational, and existing Governance decisions and peer
      areas are unchanged.
- [x] Run focused backend/frontend tests, lint/build, and migration checks.
- [ ] Perform browser QA for a mixed-reason scope, drift, partial failure,
      retry, and narrow layout.

### Follow-up quality evidence

- Frontend focused recovery/API/Governance tests: 32 passed; full frontend
  suite: 37 files / 211 tests passed.
- Frontend lint and production build passed.
- Backend recovery plus Canonical/AI/foundation/contract tests: 39 passed;
  response-contract tests with `/frontend:ro` mounted: 8 passed, 16 skipped.
- After the scoped-queue investigation, backend AI-enrichment and recovery
  regressions passed: 20 tests; targeted Ruff and `git diff --check` passed.
- Read-only current-corpus preview: `offertoday:118000` selected 37 eligible
  Reviews (10 invalid output, 27 missing provenance); `offertoday:121000`
  selected 0. No recovery run was confirmed or dispatched.
- Exclusion summaries now derive category identity from the preserved Source
  Classification Path root and use legacy Job scalar fields only as fallback;
  regressions cover both preview and persisted run detail payloads.
- Backend Ruff, Python compilation, and Alembic head discovery passed.

### Scoped transport regression evidence

- Frontend full suite: 37 files / 216 tests passed; targeted ESLint and
  production build passed.
- Disposable PostgreSQL canonical API suite: 7 passed, including GET/POST
  parity, title/company labels, and all-invalid bounded scope returning an
  explicit empty page.
- Live backend smoke: Governance summary GET, canonical review GET, and a
  19.5KB POST body containing 500 bounded Job IDs all returned HTTP 200.
- The host Python environment has no `pytest`; backend verification used the
  project `backend-api` container and a dedicated `jobsdb_test` database.
