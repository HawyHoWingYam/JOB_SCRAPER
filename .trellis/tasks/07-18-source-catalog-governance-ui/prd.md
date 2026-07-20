# Source Catalog governance UI

## Goal

Add a dedicated desktop governance page where an operator can discover, validate, compare, impact-review, publish, audit, and roll back Source Catalog Revisions without exposing candidates to crawl execution.

## Confirmed state

- Both backend dependencies are complete and archived. Live `jobsdb` is at
  `20260720_210000`, and JobsDB, CTgoodjobs, and OfferToday each have one active
  initial revision recorded in the CP10 evidence document.
- `/api/v1/source-catalogs/*` already owns summary, published tree, candidate,
  validation, publication review/publish, history, rollback review, and rollback
  contracts. This child consumes those contracts; it does not add a second
  eligibility or impact model in React.
- This is the first UI child in delivery order and therefore owns the small,
  backward-compatible shared API-client change that retains structured
  `code/message/details/requestId` for all three Crawl Control UI children.

## Requirements

- Add a `Source Catalogs` navigation destination separate from Task Control Board.
- Source summary shows the active revision/fingerprint, provenance, publication time, node/query-target counts, validation health, candidate state, and affected-Automation count without triggering discovery.
- `Check for updates` creates a non-executable candidate and never changes the active revision.
- Candidate review groups added, renamed, moved, removed, selectability/capability changed, alias changed, and query-semantics changed nodes using source-native hierarchy.
- Validation view separates full-catalog offline results from per-changed-target bounded live smoke and shows pending/running/passed/failed/manual-action-required evidence.
- Manual-action-required CTgoodjobs validation remains headed-only and provides an actionable resume/retry path.
- Automation impact shows each affected Exact/Subtree/all scope, before/after Query Target count, workload-cap effect, and whether it remains compatible or enters `Scope review required`.
- Publish is disabled until required validation passes and impact review is current. Confirmation sends the candidate fingerprint, active revision, and impact-review token.
- Publication failure leaves the prior revision active. Success atomically updates summary and history; stale responses force refresh rather than optimistic UI activation.
- Immutable history exposes prior revisions, provenance, validation summary, and publication/rollback actor/time.
- Rollback first produces current impact, then requires explicit confirmation; it cannot bypass validation or reactivate by mutating history.
- The page renders optional canonical `clean_match` annotations only as secondary information and never edits canonical mappings.
- Loading, no-candidate, unchanged-candidate, stale-candidate, validation failure, manual action, publication conflict, rollback conflict, and success states are explicit.
- Navigation, source tabs, diff filters/tree, validation details, impact table, and confirmations are keyboard/focus/screen-reader usable.
- Implement feature-local governance views/API state; do not create a speculative project-wide table/dialog/toast framework.

## Acceptance criteria

- [ ] Operator can inspect all three current revisions without network discovery.
- [ ] Checking for updates cannot affect category API validation, wizard scope, or crawler runtime.
- [ ] Diff accurately separates label/hierarchy/alias changes from executable-query changes.
- [ ] Offline and live validation evidence is durable, pollable, bounded, and retryable.
- [ ] CTgoodjobs manual-action validation never offers headless execution.
- [ ] Real Automation impact and cap consequences are shown before publish and rollback.
- [ ] No invalid, stale, automatically approved, or stale-impact candidate can publish.
- [ ] Publish/rollback success switches all consumers together and preserves immutable history.
- [ ] API failure and stale asynchronous responses never replace current good page state.
- [ ] Keyboard/focus/status semantics and all defined empty/error/manual-action states are tested.
- [ ] Canonical taxonomy/enrichment governance remains unchanged.

## Dependency and scope

- `07-18-source-catalog-runtime-correctness` and
  `07-18-versioned-crawl-scope` are complete, archived, and live; their API and
  real Automation-impact dependencies are available.
- Task Control Board/wizard implementation and backend catalog/scope logic are out of scope.
