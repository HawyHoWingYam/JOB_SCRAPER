# Design: Make OfferToday listing coverage adaptive and verifiable

## Design shape

Keep this as one complex task because taxonomy resolution, keyword review,
Dispatch Plan freezing, and listing outcomes form one reviewed-to-executed
contract. Splitting them into separately releasable tasks would temporarily
allow previews that execution cannot honor. Implementation remains divided into
independently testable checkpoints in `implement.md`.

The design uses four deep modules. Their interfaces are the test surfaces; HTTP,
SQLAlchemy, browser transport, and React details stay behind their respective
seams.

1. `OfferTodayTaxonomyResolver.refresh_or_last_verified()` returns one complete,
   fingerprinted current snapshot plus fresh/stale provenance, or a blocking
   no-snapshot result.
2. `OfferTodayKeywordCatalog.preview_csv()` and `confirm_csv()` own CSV parsing,
   normalization, limits, diffs, evidence-column protection, preview expiry,
   stale detection, atomic mutation, and audit logging.
3. `OfferTodayListingPlanResolver.resolve()` turns authored top-level scope,
   frozen taxonomy, current enabled keywords, and listing settings into ordered
   Query Targets, workload arithmetic, warnings, and one deterministic input
   fingerprint.
4. `OfferTodayListingRunner.run()` owns target-local pagination, identity
   growth, terminal confirmation, one fresh-session recovery, evidence, and
   complete/partial outcomes.

Callers do not reproduce normalization, target multiplication, or completion
rules. Production adapters and deterministic test adapters sit at the external
OfferToday seam.

## Live taxonomy and verified snapshots

Replace the OfferToday adapter's bundled-registry discovery path with bounded
live discovery through the existing `DiscoveredCatalog` /
`CatalogNodeSnapshot` interface. Keep the bundled registry only as bootstrap
and compatibility data; it is not proof of current source state. Live discovery
must return a complete root-and-child tree, source retrieval time, payload hash,
and source provenance before it can be marked verified.

A one-off preview attempts one bounded refresh. A successful refresh is
validated with the existing adapter compiler and synchronized in one
transaction. Complete synchronization inactivates every missing OfferToday
classification, including children; incomplete `observe_path()` calls continue
to reactivate or update observed paths without inactivating anything. The
complete-sync behavior must remain source-scoped so other adapters are not
silently changed.

Persist verified snapshot metadata independently of mutable current
`source_classifications`: snapshot id/fingerprint, source site, verified time,
provenance, and the complete normalized tree payload. Current rows remain the
ordinary browse/read model. Historical plans retain their own frozen resolved
scope rather than joining back to current rows.

If live refresh fails, resolution uses the newest verified snapshot and returns
a stale warning containing its verified time and fingerprint. With no verified
snapshot, preview/dispatch is blocked. Scheduled automation performs the same
resolution before dispatch.

## Ordinary-current keyword catalog

Add ordinary-current OfferToday tables with no release/version identity:

- keyword entry: top-level `classification_id`, display `classification_label`,
  authored `keyword`, normalized identity, `enabled`, notes, created/updated
  actor and timestamps;
- mutation log: actor, timestamp, SHA-256 of the uploaded CSV bytes, and
  added/updated/disabled counts;
- single-use CSV review: expiry, token hash, reviewed CSV hash, catalog-state
  fingerprint, normalized change set/diff, resulting enabled counts, workload
  impact, consumed time;
- latest keyword execution evidence: either a projection derived from persisted
  completed target evidence or a compact current projection keyed by keyword
  entry. It is runtime-owned and never accepted as mutable CSV input.

The unique identity is `(classification_id, normalized_keyword)`, where
normalization trims, collapses internal whitespace, and case-folds. Authored
spelling remains the request/display value. Only active top-level OfferToday
classification identities are accepted. `enabled` must parse explicitly; notes
are bounded text. The resulting current state may contain at most 150 enabled
entries per classification.

CSV columns are:

```csv
classification_id,classification_label,keyword,enabled,notes,last_new_job_ids,last_duplicate_rate,last_run_at
```

The first five columns are authored, although `classification_label` is checked
and stored only as informational display data; `classification_id` is
authoritative. The last three columns round-trip but are ignored for mutation.
Duplicate normalized identities, malformed rows, unknown/non-top-level
classifications, and post-merge limit violations reject the whole file with
row-level errors.

`preview_csv()` performs no catalog mutation. It stores the exact normalized
change set and returns a short-lived single-use confirmation token, full diff,
per-classification enabled counts, and workload impact. `confirm_csv()` locks
the review and catalog identities, verifies token, expiry, unconsumed state,
CSV hash, and current catalog fingerprint, then applies the reviewed merge and
one mutation-log row atomically. Omitted rows remain unchanged; `enabled=false`
disables; no CSV operation deletes an entry. A stale review must be regenerated.

Bootstrap idempotently inserts the 127 reviewed IT terms for
`offertoday:118000`. It does not insert A-Z/0-9 and leaves other packs empty.

## Listing plan resolution and immutable dispatch

For each authored top-level classification, resolve Query Targets in this
stable order:

1. top-level classification with no keyword;
2. active child classifications from the frozen verified snapshot, sorted by
   stable source identity, each with no keyword;
3. enabled top-level keyword entries, sorted by normalized identity.

There is no child-by-keyword multiplication. The resolver records target kind
(`native_top_level`, `native_child`, or `keyword`), top-level owner, resolved
classification id/code/label, authored keyword and normalized keyword identity,
selection order, taxonomy snapshot fingerprint, and keyword-catalog fingerprint.

For page depth `D`, with `R` selected roots, `C` resolved children, and `K`
enabled keywords, maximum pages are:

- native: `(R + C) × D`;
- keyword: `K × D`;
- total: `(R + C + K) × D`.

Preview shows all three values and rejects confirmation when Run Page Cap is
below total maximum. Scheduled automation blocks as review-required if current
resolved work exceeds its saved cap; it never raises that cap.

Extend listing `CrawlDispatchPlan` preparation so its immutable `resolved_scope`
and ordered frozen target payload contain the exact taxonomy and keywords
reviewed. Include the complete target payload, workload, snapshot fingerprints,
warnings, and listing settings in `plan_fingerprint`. Confirmation rechecks the
prepared fingerprint/token only; it does not re-resolve current catalog state.
This uses Dispatch Plan immutability as execution history and deliberately does
not create keyword catalog versions.

## Pagination, recovery, and evidence

Retain the existing per-condition identity set and cross-condition staging
deduplication. For each successful page, record both raw row count and newly
observed identities for that target. A non-empty page with `hasMore=false`
enters terminal confirmation and does not complete the target. Two consecutive
successful empty pages establish natural exhaustion even if OfferToday's
unstable `hasMore` value remains true; terminal-empty evidence takes precedence
over no-growth stall evaluation. Any intervening non-empty page resets the empty
count.

When `hasMore=true` and three consecutive successful pages contribute zero new
identities, mark the attempt `stalled`. Restart once with a genuinely fresh
browser/source session, reset cursor/page-local terminal counters, retain the
target's already-seen identity set, and continue without staging duplicates. A
second stall marks that Query Target partial with reason
`stalled_after_session_recovery`; later targets still run. Stall recovery has
its own exactly-once budget and is not consumed by the existing exactly-once
browser-loss recovery. Both counters are recorded, so a target can perform at
most one recovery of each bounded kind.

Reaching target depth or aggregate Run Page Cap before two-empty confirmation
marks the affected target partial with a machine-readable reason. Valid listings
remain staged. Every planned target produces one complete or partial outcome;
only infrastructure gaps/conflicts that invalidate execution retain the
existing non-partial failure path.

Per-page evidence adds target kind, raw/distinct/new counts, duplicate ratio,
consecutive-no-growth count, terminal-empty count, session/recovery index, and
transition reason. Per-target evidence summarizes pages, observed identities,
newly contributed cross-plan identities, duplicate ratio, recovery attempts,
terminal evidence, and final reason. Overall projection reports native and
keyword complete/partial counts separately; any partial target makes the task
`partial`.

Historical research payloads keep their frozen field set. New optional evidence
is emitted only by the new plan/policy contract and readers default absent
fields. Source-reported totals remain diagnostic only.

## Operator interfaces

Add a global `OfferToday Keyword Packs` route and sidebar entry. The page is
read-only/filterable and shows enabled counts, update times, and latest keyword
contribution evidence. It supports CSV download, upload preview, error/diff and
workload review, and explicit confirmation. Any new upload or catalog change
invalidates the visible preview. There are no inline row controls.

The crawl review flow continues through the existing review/prepare/dispatch
interface. OfferToday review adds taxonomy freshness, frozen root/child/keyword
counts, catalog update time, native/keyword/total maximum pages, cap validity,
warnings, and a link to keyword management. Crawl authoring never accepts a CSV.

## Compatibility and rollout

- Existing frozen A-Z/0-9 plans remain readable and executable according to
  their recorded endpoint/request policy. New plan resolution never emits them.
- Search and browse cursor contracts remain distinct; compatibility readers do
  not inject cursor fields into historical stateless targets.
- Published Job identity, Detail Backlog, and cross-target staging deduplication
  do not change.
- Roll out schema/bootstrap, catalog management, taxonomy refresh, plan
  resolution, runner policy, and UI in guarded checkpoints. Do not enable new
  plan emission until the full review-to-execution path is available.
- Rollback disables new plan emission, keeps existing immutable plans readable,
  and reverts to the prior compiler for newly authored work. New catalog and
  evidence tables may remain inert; no destructive data rollback is required.

## Verification strategy

Test through the four module interfaces with a deterministic live-taxonomy
adapter, database transactions, fake clock/token source, and scripted listing
transport. Cover complete and stale taxonomy resolution, child add/remove,
atomic CSV preview/confirm, normalization and limits, target ordering and
workload arithmetic, plan fingerprint invalidation, scheduled cap blocking,
healthy exhaustion, false terminal signals, repeated cohorts, shared recovery
budget, page caps, cross-target deduplication, partial projection, and historical
target compatibility.

API tests cover CSV content disposition, row errors, stale/single-use reviews,
review/dispatch payloads, and direct-call enforcement. Frontend tests cover
routing, filtering, download, upload preview invalidation, confirmation,
read-only behavior, workload rendering, and blocked dispatch. Finish with
targeted backend/frontend suites, backend lint/type checks, frontend lint/build,
and a bounded headed OfferToday smoke that records taxonomy provenance and
pagination evidence without treating source totals as completion proof.
