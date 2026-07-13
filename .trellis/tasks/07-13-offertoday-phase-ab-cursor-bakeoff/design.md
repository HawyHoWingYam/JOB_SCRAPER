# OfferToday Phase A-B cursor pagination bake-off design

## Contract Boundary

`listing_contract.py` defines frozen dataclasses for cursor state, request policy, typed transport ownership, parsed page cohorts, redacted page evidence, and the v2 candidate. Exact integers reject booleans, floats, negatives, and numeric strings. Raw `sessionId` is allowed only in memory and is represented durably by a SHA-256 plus non-sensitive continuity fields.

`build_offertoday_listing_payload()` keeps the legacy defaults but accepts explicit page size and validated cursor data. It always constructs a new object from the frozen condition.

## Cursor State Machine

For one condition, page 1 has no cursor. Each successful typed response is validated, identity-analyzed, observed, and only then advances the cursor. Page `N+1` carries the exact prior cursor. A transient retry keeps page, cursor input, browser context, payload fingerprint, and logical request ID fixed while changing attempt/physical request identity.

Terminal acceptance requires the endpoint terminal signal and an empty confirmation in the same validated chain. A non-empty confirmation, unexplained rollover, page-size drift, missing cursor, cross-condition use, resume at page N, identity error, unresolved gap, or conservation mismatch rejects before staging.

## Runtime Ownership

The browser runtime owns authenticated transport and one generated context identity, never pagination state. The research service owns:

- `shared-variant-runtime`: one fresh runtime for a repeat/variant, with independent condition cursors;
- `condition-local-runtime`: one fresh runtime for a single condition chain;
- `restart-each-page`: a new runtime for every page, deliberately carrying the cursor only as the tested variable.

All paths close their runtime on success, hard stop, retry exhaustion, and exception.

## Bake-Off Model

The five variants and controls are frozen exactly as implementation-plan Task 6. Order is derived before responses from `(repeat_index, order_seed)` and randomized independently per category/repeat. Summary and comparison metrics are recomputed from page evidence rather than trusted live counters.

Candidate selection is deterministic and fail-closed. The comparison accepts exactly one response-cursor variant only if every frozen integrity, duplicate, union/cost, Jaccard, and zero-failure gate passes. Candidate freezing binds the accepted comparison and source hashes into `candidate_version=2`.

## Artifact and Replay Design

V2 experiments use new names and a separate verifier. Events carry protocol/variant/repeat/condition identities, logical and physical request identities, request/context/cursor hashes, cohort identities, marginal/duplicate evidence, terminal states, budgets, snapshots, and no-write evidence. The strict verifier independently reconstructs all summaries and rejects unknown fields/versions, leaks, ordering drift, parent drift, or mismatched hashes.

V1 dispatch and artifact semantics remain unchanged.

## Compatibility and Rollback

Production callers continue to use the v1-compatible default payload until final adoption. Phase A/B can be rolled back by removing the new research entry points and v2 types without rewriting historical artifacts. A valid-but-rejected bake-off remains durable evidence and stops the workflow.
