# Implementation plan: Make OfferToday listing coverage adaptive and verifiable

Implement in the order below. Each section is a reviewable checkpoint; do not
enable new OfferToday plan emission until the taxonomy, catalog, dispatch, and
runner contracts are all compatible.

## 1. Contract tests and persistence

- [ ] Add failing database/model tests for verified taxonomy snapshots,
  ordinary-current keyword entries, normalized uniqueness, CSV reviews,
  mutation logs, and latest runtime evidence.
- [ ] Add SQLAlchemy models, table registries, empty-schema bootstrap/cutover
  participation, constraints, indexes, and relationships without introducing a
  catalog release/version identity.
- [ ] Add deterministic normalization and fingerprint value objects shared by
  CSV catalog mutation and plan resolution; reject case/whitespace duplicate
  identities.
- [ ] Add idempotent bootstrap for exactly the reviewed 127 enabled IT terms,
  excluding A-Z/0-9 and leaving other top-level packs empty.
- [ ] Verify retained-data and empty-schema database paths before proceeding.

Rollback point: new tables/bootstrap can remain inert; no production call site
uses them yet.

## 2. Live taxonomy resolution

- [ ] Add a scripted adapter test for complete live OfferToday root/child
  discovery, provenance, timeout/failure, and payload fingerprinting.
- [ ] Implement bounded live discovery behind the existing OfferToday catalog
  adapter interface; retain bundled data only for bootstrap/compatibility.
- [ ] Extend complete Source Classification synchronization to inactivate
  missing OfferToday children transactionally while preserving incomplete
  `observe_path()` behavior and other sources' semantics.
- [ ] Implement `refresh_or_last_verified()` with atomic verified snapshot
  persistence, latest-snapshot fallback, stale warning, and no-snapshot block.
- [ ] Add tests proving child addition, removal, reactivation, malformed partial
  discovery rejection, and historical snapshot immutability.

Rollback point: switch preview resolution back to the bundled adapter; retained
verified snapshots remain diagnostic and current rows can be resynchronized.

## 3. Keyword catalog and CSV review

- [ ] Add failing module tests for CSV round-trip, required columns, booleans,
  labels versus authoritative ids, row errors, evidence-column protection,
  merge/upsert omission behavior, disabling, 150-enabled limit, and atomic
  rollback.
- [ ] Implement keyword catalog reads and latest completed execution evidence
  projection without per-row query amplification.
- [ ] Implement non-mutating `preview_csv()` returning full diff, errors,
  per-classification counts, workload impact, expiry, and single-use token.
- [ ] Implement `confirm_csv()` with row lock, token/hash/fingerprint fencing,
  stale/consumed rejection, one atomic merge, and one non-restorable mutation
  log entry.
- [ ] Add authenticated CSV export, preview, and confirm endpoints with stable
  error payloads and `Content-Disposition` handling.
- [ ] Test concurrent catalog mutation, confirmation replay, expired review,
  direct endpoint calls, and exact unchanged round-trip.

Rollback point: hide/disable mutation endpoints; ordinary-current rows remain
safe and can be disabled through a reviewed CSV when re-enabled.

## 4. Adaptive plan resolution and dispatch freezing

- [ ] Add resolver tests for stable ordering: root native, active children,
  root-plus-enabled-keywords; prove absence of child-keyword Cartesian targets.
- [ ] Implement native/keyword/total workload arithmetic and enforce authored
  Page Depth plus aggregate Run Page Cap.
- [ ] Extend one-off review to attempt taxonomy refresh and expose fresh/stale
  provenance, target counts, keyword catalog time/fingerprint, workload, and
  warnings.
- [ ] Extend scheduled automation review/dispatch to use current inputs and
  block as review-required when its saved cap is insufficient.
- [ ] Extend listing Dispatch Plan persistence/preparation to freeze ordered
  Query Target payloads and include all reviewed inputs in the plan fingerprint.
- [ ] Reject confirmation when a prepared review fingerprint/token is stale;
  once prepared, dispatch must execute the frozen targets without re-resolving
  current taxonomy or keywords.
- [ ] Add compatibility tests proving historical empty-keyword and A-Z/0-9
  frozen plans remain readable/executable and new plans never emit A-Z/0-9.

Rollback point: stop preparing new adaptive plans. Already prepared plans remain
valid immutable authorities; do not rewrite them.

## 5. Evidence-bounded listing execution

- [ ] Add scripted transport tests for healthy growth, non-empty
  `hasMore=false`, two-empty exhaustion, reset after intervening non-empty page,
  and depth/run-cap partial outcomes.
- [ ] Add failing tests for three `hasMore=true` no-growth pages, exactly one
  fresh-session recovery, retained identity deduplication, repeated stall
  partial outcome, and continuation to later targets.
- [ ] Implement target-local growth/terminal counters, one stall-recovery
  budget, and the separate existing browser-loss-recovery budget; record and
  bound both independently.
- [ ] Persist optional new per-page/per-target evidence without changing frozen
  historical research payloads; update readers and smoke verification for new
  policy/stop reasons.
- [ ] Project native and keyword completion separately and make any partial
  Query Target produce an overall partial task while retaining valid listings.
- [ ] Update latest keyword contribution evidence only from completed execution
  evidence; runtime statistics remain non-authoritative catalog columns.
- [ ] Test cancellation, infrastructure failure, cross-target deduplication,
  task progress, and unchanged published Job/Detail Backlog semantics.

Rollback point: disable new adaptive plan emission. Keep recorded evidence and
valid staged listings; never downgrade a partial run to complete.

## 6. Operator UI

- [ ] Add route, sidebar entry, API client, and read-only/filterable OfferToday
  Keyword Packs page.
- [ ] Implement CSV download, upload validation/diff/workload preview,
  row-error display, explicit confirmation, and visible preview invalidation
  after a new file or catalog change.
- [ ] Show enabled counts, update times, and latest contribution evidence with
  no inline create/edit/disable controls.
- [ ] Extend Task Control review UI with taxonomy freshness, frozen
  root/child/keyword counts, native/keyword/total workload, cap validity,
  warnings, and management-page link.
- [ ] Add route/navigation, loading/error/empty, upload, stale preview,
  single-use confirmation, accessibility, and blocked-dispatch tests.

Rollback point: remove the navigation entry and adaptive review controls while
leaving backend reads and frozen plans intact.

## 7. Integration, rollout, and documentation

- [ ] Run targeted backend tests for models, source classification registry,
  OfferToday adapter/runner/research, dispatch plans, automation lifecycle, and
  crawl-control APIs.
- [ ] Run backend Ruff, Mypy, and the relevant full backend suite; record any
  pre-existing baseline separately from new failures.
- [ ] Run targeted frontend tests, full Vitest, ESLint, and production build.
- [ ] Validate empty-schema bootstrap and retained-data sandbox cutover with the
  new tables and 127-keyword seed.
- [ ] Run a bounded headed OfferToday smoke: verify live taxonomy provenance,
  preview workload/fingerprint, one frozen dispatch, terminal/stall evidence,
  and retained listings without asserting an absolute inventory count.
- [ ] Confirm legacy frozen A-Z/0-9 plan replay before enabling new adaptive plan
  emission.
- [ ] Update backend OfferToday production, ordinary Source Classification,
  crawl-control review, database, and frontend Task Control specs. Record the
  new operator procedure for CSV maintenance and partial-run interpretation.
- [ ] Run `trellis-check`, inspect the complete diff, and obtain manual operator
  QA for CSV round-trip, preview/confirm, crawl review, and a partial outcome.

Final rollback: turn off new adaptive plan preparation and UI entry, retain all
catalog/snapshot/evidence data, and execute already frozen plans under their
recorded contracts. Do not delete history or repair state with direct SQL.
