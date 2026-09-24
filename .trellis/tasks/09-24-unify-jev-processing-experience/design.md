# Design: independent AI Skills and manual Jev operations

Status: proposed for final review. Product requirements are authoritative in prd.md; this document contains implementation choices, not additional user approvals.

## Architecture and ownership

Ordinary AI enrichment discovers Skill evidence and persists a usable baseline through existing current-taxonomy reconciliation. Governed exact/alias matches remain canonical assignments; unresolved terms remain Candidates/Mentions, not automatically created taxonomy nodes. Detach `JevOnlineSkillRunner` from `AIEnrichmentService.enrich_job`. Jev is a separately initiated correction pass with its own receipts and durable result history.

Use the existing Jev native typed-question adapter, `JevRunService`, and worker/outbox mechanisms. Remove the local monetary ledger: Jev API Console owns spending limits. Extend durable orchestration to represent an operator batch and its per-Job/per-operation items; do not create a parallel in-memory queue. Historical Skill backfill currently uses enrichment runs/outbox: adapt that path to manual dispatch and preserve its deduplication contract. Exact table and route additions are resolved in child-task design against current code.

The existing Jev spec describes inline classification, scheduled maintenance, Settings run controls, and some restart/retry behavior. The approved manual-only requirements deliberately supersede those clauses; update the affected specs in the implementing slice. Read-only startup reconciliation may continue, but must never dispatch Jev.

## Skill result composition

Retain distinct AI baseline, Jev correction, and operator correction provenance. Resolve effective Skills in this order for current source evidence:

1. Operator-owned per-Skill additions/removals or dispositions.
2. A successful Jev correction bound to the current evidence.
3. The latest successful AI baseline bound to the current evidence.

Represent explicit removals as well as additions so later reconciliation cannot silently restore rejected skills. Superseding active mentions must not erase baseline/history or operator intent. Route the resulting effective projection through the existing current-taxonomy store so search, analytics, exports, and recommendation scoring agree.

An unchanged-text AI rerun updates the baseline without replacing valid Jev corrections. Changed source evidence invalidates Jev applicability; after new AI enrichment, use its current baseline pending manual Jev reevaluation. Until then, retain historical results as stale rather than presenting them as current. Empty success is a real result; unavailable/invalid is not empty success. Manual taxonomy creation/approval remains governed separately.

Jev must be able to assess supported additions from Job evidence, not only delete first-pass mentions. Use bounded candidates from original evidence and active taxonomy, preserve explicit insufficient outcomes, and do not silently call an additional ordinary AI pass from the Jev job. Record the selected evidence, taxonomy identity, model/rubric, and source fingerprint. If current evidence drifts before commit, retain the receipt but do not publish it as current.

## Manual batch and lifecycle contract

The operator supplies either a filtered Job scope or explicit Job IDs, a maximum Job count, selected operations, and optional force reevaluation. Preview is provider-free and reports selected, eligible, skipped, unsupported, missing-prerequisite, and failed counts per operation without a local monetary estimate. Avoid paid query embeddings in preview; use lexical scope/existing stored vectors. Missing embeddings are reported explicitly, not filled through an implicit paid call.

At explicit Start, validate/freeze membership, source evidence, operation set, limits, and runtime identities. Changed preview inputs require refresh; do not silently broaden a reviewed batch. Idempotent Start prevents double-click duplication. Default eligibility is independent per operation: unprocessed, stale, or failed; successful unchanged items skip unless force is requested.

One batch references bounded underlying Jev runs and durable per-operation items. If Skills and Related Jobs are both selected, complete the Skill item before finalizing that Job's recommendation input; candidate membership remains bounded by the reviewed plan. Duplicate judging is independent. Record which Skill projection/version a recommendation used. Failed dependencies are explicit; independent items continue, rather than rolling back successful work.

Only operator Start/Resume/Retry grants dispatch authority. Disable automatic scheduled initiation, inline enrichment invocation, startup recovery dispatch, and automatic retry of terminal failures. A live manually started batch may continue normal item execution. Stop prevents new requests; already dispatched calls may complete. After process restart, interrupted work requires manual resume. Do not reissue ambiguous attempts blindly; preserve attempt history. Forced reevaluation gets a new attempt lineage without bypassing active-item exclusion.

Jev API Console is the only monetary quota authority. Remove local allowance,
reservation, token-price and cost-ceiling state and all monetary admission gates.
Keep provider-reported request ID, usage, latency and cost as optional audit data;
missing cost remains unknown and is never estimated locally. Keep bounded scope,
question limits, concurrency, timeout, retry and idempotency as operational safety.

## Related Jobs and duplicate associations

Existing retrieval supplies bounded candidate identities. Jev assesses relatedness, filters and orders those candidates, and produces short reasons through native typed answers (bounded reason choices rendered to text where appropriate). Validate all output identities against the frozen candidate set; never accept invented Jobs. Persist a successful result even when empty. Avoid title-only deduplication before judgment losing distinct suitable candidates; keep source records distinct.

Read states:

| State | Current display |
| --- | --- |
| No successful Jev evaluation | Existing algorithmic recommendations, labeled not evaluated |
| Current successful nonempty result | Stored Jev order and reasons |
| Current successful empty result | No related Jobs; no algorithmic refill |
| Failed rerun, unchanged evidence | Previous successful result, including empty |
| Supporting evidence changed | Current algorithmic fallback labeled awaiting reevaluation; old Jev result retained in history |

Bind applicability to subject/candidate evidence and any effective Skill data used for judgment. No provider calls on reads, invalidation, or search. Newly added corpus Jobs do not silently join a saved evaluation; manual force reevaluation can refresh discovery. Deleted candidates are never displayed, and affected evidence/result state is revalidated.

Possible same vacancy retains its existing pair identities, current-evidence checks, proposed/confirmed review semantics, and source-preserving guarantee. It remains a separate relation from Related Jobs; no merging, hiding, or copying Job facts. Existing review actions may remain on detail because they do not initiate provider work.

## Unified page and search fixes

Proposed navigation: one Jev operations page with Job batch authoring, operation-specific tools (taxonomy maintenance, lexical search advisory, incident triage, crawl quality), and shared history/progress/provider receipt details. Move all provider execution controls, including smoke execution, here. Old pages expose results and links prefilled with relevant scope; links never auto-start. Keep credentials/default configuration in Settings, with a direct link and readiness summary in the Jev page. This placement awaits final plan review.

Reuse current operation services and preserve advisory boundaries: incident/quality tools cannot change crawl lifecycle; lexical reranking cannot change membership, totals, filters, or facets. Lexical reranking is distinct from Related Jobs filtering.

Bind each preview/result to scope and retrieval mode plus request generation. Cancel/ignore obsolete UI requests, but do not equate browser abort with cancelling already dispatched provider work.

For Job Browser, separate draft retrieval mode from the last successful applied mode. A successful explicit submit commits scope and mode together; failure retains prior rows, facets, total and export snapshot. Pagination/export use only the applied snapshot. Capabilities loading/failure leaves lexical usable and disables unverified modes with a local retry. Preserve the existing independent result/facet lifecycles and progressive rendering.

## Experience presentation and search

Add experience bounds, availability/provenance data to search-card serialization using the same authoritative interpretation as Job Detail; avoid N+1 detail fetches. Use one shared formatter for compact labels on cards/detail. Keep full bounds and evidence inspectable in detail; distinguish pending enrichment from genuinely unspecified and inferred from employer-stated.

Retain `_experience_windows_overlap_clause` and reuse it across lexical, semantic/hybrid candidates, facets and export. Display `1+` for stored `[1,2]` does not change that interval to `[1,infinity)`. Applied filter summaries describe the query range, not the lossy Job label. Preserve existing unspecified virtual `[0,1]` matching under issue #61, without claiming it is an employer requirement.

Issue #61 owns explicit-evidence recovery, estimated windows, and historical repair. Support its agreed provenance contract rather than introducing another seniority-to-years mapping. Delivery of inferred labels is dependent on that contract/data; explicit labels and search consistency can proceed independently.

## Compatibility, rollout, and rollback

Use current-schema changes for baseline/correction history, batch links and recommendation snapshots where existing tables cannot express the contracts. Retain Job identities, source bounds, and provider receipts; remove the local monetary ledger. Do not relabel legacy Jev projections as AI baselines: import them with accurate provenance; missing AI baselines require ordinary enrichment, and historical runs remain operator-selected.

Deploy backend contracts before exposing new UI actions. Fence/mark preexisting interrupted work as requiring manual recovery before enabling the new dispatcher; never auto-run migrated tasks. Rollback may disable new manual starts and retain read/history access, but must not restore automatic Jev execution or local monetary gates. No destructive corpus rebuild is part of this task.

## Verification and practical limits

Production persistence/locking tests use isolated PostgreSQL databases ending in `_test`; provider integration uses a loopback fake. Validate zero Jev provider requests for ordinary AI enrichment, page reads, preview, schedules, restart, and settings saves; ordinary AI retains its own explicitly initiated enrichment calls. Assert authorized runs and explicit retries are bounded and billed once per actual attempt. No live paid smoke is required for plan completion.

Search performance remains unmeasured. Extend the existing read-only benchmark with representative experience scopes and inspect PostgreSQL plans before proposing indexes or candidate-query reuse. Keep warm medians and corpus/result counts; do not claim speed improvements from source inspection.
