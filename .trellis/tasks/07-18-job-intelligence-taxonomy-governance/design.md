# Job intelligence taxonomy and governance design

## Status and purpose

This document defines the cross-child architecture for the post-collection Job Intelligence program. It owns seams, shared invariants, contracts, data-flow ordering, compatibility, and release shape. Each child design owns the detailed implementation inside its Module.

The design follows the decisions in `CONTEXT.md`, ADR-0005 through ADR-0014, and the research files under this task.

## Design invariants

1. Source Taxonomy, Canonical Job Taxonomy, Company Industry Taxonomy, Employment Type, and Skill Taxonomy remain distinct authorities.
2. Raw evidence is preserved separately from governed projections.
3. Unknown or unsupported evidence remains Unknown/Unassigned or enters review; it never becomes a plausible-looking fallback.
4. AI may recommend and may perform only the explicitly approved constrained Job Taxonomy assignment. AI never creates governed taxonomy nodes or executes a Skill/Company Industry governance decision.
5. Governance decisions are local-operator actions with confirmation, idempotency, optimistic concurrency, and append-only audit.
6. Background workers cross recommendation/normalization Interfaces only; they cannot reach decision Interfaces.
7. Taxonomy revisions and historical decisions are immutable. New information appends rather than rewriting history.
8. The core Job/Company corpus and raw evidence survive cutover; derived Job Intelligence Projections are rebuildable.

## Module and seam map

| Module | External Interface | Owns | Explicitly does not own |
|---|---|---|---|
| Job Intelligence Foundation | revision publication, provenance value objects, decision context, audit append, idempotency/concurrency checks | shared invariants and persistence primitives | domain-specific mapping or decision rules |
| Source Job Attributes | normalize source classification/employment evidence; read/filter governed projections | Source Classification Paths, Source Employment Labels, Employment Types | Crawl Scope or source-catalog publication |
| Canonical Job Taxonomy | assign an existing governed path; create/read/decide review items | taxonomy revision, accepted assignment provenance, Unassigned state | source crawling or auto-created taxonomy nodes |
| Company Industry | ingest company-level evidence; map/assign/review; hierarchical filtering | HSIC revisions, crosswalks, assignments, mappings, review items | Job Industry or Source Classification |
| Skill Governance | normalize mentions; read candidates; execute operator decisions | Skill taxonomy, mentions, candidates, decisions, Job-Skill projection | treating unresolved terms as Skills |
| Job Intelligence Read Model | query governance queues and product-facing projections | pagination, filter option contracts, summaries, breadcrumbs, deep-link identifiers | domain decisions |
| Cutover/Rebuild | plan, dry-run, execute, reconcile, rollback | writer quiescence, legacy snapshot, rebuild orchestration, validation gates | runtime business decisions |

The deletion test applies: removing any domain Module would force its validation, provenance, transition, and audit rules back into multiple API routes, workers, repositories, and tests. Shared foundation remains deliberately small; domain behavior is not generalized into a shallow all-taxonomies Interface.

## Shared Interfaces

The exact Python types belong to child 1, but callers should learn no more than these concepts:

```text
RevisionRef
  domain, revision_id, release_key, content_hash

Provenance
  method, source_site?, source_revision?, mapping_id?, evidence_refs,
  model_provider?, model_name?, model_version?, captured_at

DecisionCommand
  subject_id, action, target_id?, expected_version,
  idempotency_key, confirmed=true, actor="local-operator", note?

DecisionResult
  subject, resulting_projection?, audit_event_id, version, replayed
```

All decision Interfaces return results and create their audit/outbox records in the same database transaction. A stale `expected_version` returns a conflict without partial changes. Reusing an idempotency key with the same command replays the first result; reusing it with different content fails.

## Persistence design

### Shared foundation

- `governance_revisions`: immutable release identity, domain, release key, content hash, source metadata, lifecycle timestamps, and publication status. Domain node tables retain foreign keys to one revision.
- `governance_audit_events`: append-only event with domain, subject snapshot identity, action, actor, command hash, before/after summaries, evidence references, correlation/idempotency key, and timestamp. It does not cascade away when a subject is retired.
- `governance_idempotency_records`: unique `(domain, idempotency_key)` plus command hash and serialized result reference.
- Mutable review/assignment rows carry integer `lock_version` for optimistic concurrency.
- Existing `event_outbox` is written in the same transaction for projection/embedding invalidation events.

Evidence payloads remain in domain-owned tables or immutable raw source records. A generic polymorphic evidence table would lose foreign-key integrity and locality, so the foundation shares a `Provenance` contract rather than owning all evidence.

### Source Job Attributes

- `job_source_classification_paths`: Job FK, Source, source-catalog revision when known, source order, explicit-primary state/basis, path key, capture time, and raw evidence reference.
- `job_source_classification_path_nodes`: ordered nodes with source-qualified IDs and label snapshots. Unique `(path_id, depth)` and `(path_id, source_classification_id)` prevent malformed paths.
- `employment_types`: the seven stable governed codes.
- `job_source_employment_labels`: ordered raw Source label/code evidence and optional mapping result.
- `job_employment_types`: unique Job/type projection with provenance.

Legacy scalar source classification and employment columns remain read-only compatibility evidence until cutover validation succeeds; new writes target the new Module only.

### Canonical Job Taxonomy

- Existing Domain/Category/Subcategory tables gain revision identity and stable governed codes, or are replaced by equivalent revision-bound tables during the destructive seed rebuild.
- `job_taxonomy_assignments`: at most one active accepted assignment per Job, existing governed Subcategory FK, revision, provenance, version, and timestamps.
- `job_taxonomy_review_items`: at most one active item per Job/reason, evidence/recommendations, status, version, and resolution reference.
- Unassigned is represented by no active accepted assignment plus the appropriate review state; there is no `General` or `Unknown` fallback node.
- Node deletion is restricted when referenced; retirement happens through a later revision.

### Company Industry

- `company_industry_taxonomy_nodes`: revision-bound HSIC code, parent FK, level, bilingual labels, official source metadata, validity, and content hash.
- `company_industry_crosswalk_edges`: from/to standard and release, codes, mapping cardinality, provenance, method, and confidence.
- `source_industry_mappings`: Source label/code key, normalized lookup key, target Industry node, approved actor/time, version, and active state.
- `company_industry_assignments`: Company/Industry unique pair, provenance, explicit-primary flag/basis, version, and timestamps. A partial unique index permits at most one active Primary per Company.
- `company_industry_review_items`: unresolved evidence, recommendations, status/version, and decision reference.
- Assignments target the most specific supported node; ancestors are queried through the hierarchy, not duplicated.

### Skill Governance

- Skill Category/Technology/Skill nodes become governed revision-bound seed data with stable codes and deterministic reference validation.
- `job_skill_mentions` uses constrained resolution values and retains raw/normalized evidence, optional Skill/Candidate FK, provenance, and version.
- `skill_candidates` uses constrained states and aggregates occurrence metrics without treating counts as source of truth.
- `job_skills` remains the governed projection and is derived only from resolved mentions.
- A Candidate decision updates every affected active mention, governed links, candidate state, metrics, audit, and outbox atomically.
- Taxonomy nodes referenced by history are retired, not cascade-deleted.

## Decision and recommendation separation

Recommendation Interfaces return immutable suggestions with evidence and never accept an actor or write a decision. Decision Interfaces require `DecisionCommand` and are invoked only by governance HTTP routes in trusted local-operator mode.

This is architectural isolation, not authentication. Anyone who can reach the unprotected local API could submit a decision, so deployment documentation must prohibit exposing these routes to untrusted networks. Future authentication wraps the same decision Interface without changing domain rules.

## HTTP and read contracts

All new contracts are versioned under `/api/v1/job-intelligence`.

### Governance reads

- `GET /governance/summary`
- `GET /governance/job-taxonomy/review-items`
- `GET /governance/skill-candidates`
- `GET /governance/company-industries/review-items`
- `GET /governance/audit-events`

List endpoints use cursor or stable `(created_at, id)` pagination, explicit status filters, counts, and deterministic sorting. Responses include current `version` and deep-link IDs.

### Governance writes

- `POST /governance/job-taxonomy/review-items/{id}/decision`
- `POST /governance/skill-candidates/{id}/decision`
- `POST /governance/company-industries/review-items/{id}/decision`
- `POST /governance/company-industries/mappings`

Every body includes `action`, `expected_version`, `idempotency_key`, `confirmed: true`, optional target/note, and returns the complete updated resource plus `audit_event_id`. Invalid transitions return 422, stale versions 409, idempotency conflicts 409, and missing subjects 404.

### Product projections

Job responses expose:

- `source_classification_paths[]` with ordered nodes and explicit-primary metadata;
- `employment_types[]` and, on detail/evidence views, raw Source Employment Labels;
- `canonical_taxonomy_assignment` or explicit `canonical_taxonomy_state=unassigned`;
- governed `skills[]` plus secondary `unreviewed_skill_mentions[]`;
- Company Industries with Primary metadata and breadcrumbs.

Filters use stable IDs/codes. Values within one field are OR; different fields are AND. Company Industry ancestor filters include descendants. Raw labels never become ordinary filter options.

## Runtime data flow

### Ingest and enrichment

1. Source adapter emits preserved raw evidence.
2. Source Job Attributes normalizes paths and employment labels transactionally.
3. Canonical Job Taxonomy evaluates reviewed deterministic mapping or constrained AI output.
4. Valid existing-node assignments are persisted with provenance; all other outcomes create/update a review item.
5. Skill Governance resolves deterministic matches/generic rules or creates/updates Skill Candidates.
6. Company Industry consumes company-owned evidence; reviewed mappings may assign, otherwise a review item is produced.
7. Outbox events invalidate affected read models and embeddings.

### Human decision

1. UI reads review item and version.
2. Operator selects action/target and confirms.
3. HTTP adapter builds `DecisionCommand(actor="local-operator")`.
4. Domain Module checks transition, target governance, expected version, and idempotency.
5. One transaction writes decision effects, audit, and outbox.
6. UI refreshes from returned resource; stale decisions surface a conflict and reload evidence.

## UI information architecture

`Job Intelligence Governance` has three peer areas:

1. Job Taxonomy Review
2. Skill Candidates
3. Company Industries

Each area provides backlog summary, filters, stable queue, evidence detail, advisory recommendations, explicit decision confirmation, audit history, loading/empty/error/conflict states, keyboard-accessible controls, and deep links.

Job Browser, Job Detail, Add Job, Companies, AI Enrichment, and Dashboard use the ubiquitous language from `CONTEXT.md`. Read-only product surfaces may link into governance but cannot embed decision controls.

## Compatibility and cutover

The rollout is expand → backfill/dry-run → quiesced cutover → contract switch → cleanup:

1. Add new schema and Modules while legacy fields remain readable.
2. Seed governed revisions and validate all references/content hashes.
3. Run rebuilds in dry-run/report mode against raw evidence.
4. Quiesce ingest/enrichment/embedding/API writes; take backup and immutable legacy snapshot.
5. Rebuild projections in dependency order and reconcile counts/evidence coverage.
6. Switch reads/filters to new contracts and rebuild embeddings.
7. Validate UI/API/search/recommendation flows, then reopen writers.
8. Retire/drop legacy columns only in a later cleanup migration after the rollback window.

No dual-write period spans the cutover: pre-cutover writes use legacy paths; after contract switch, new Modules are authoritative. This avoids divergent sources of truth.

## Operational and rollback design

- Cutover commands default to dry-run and require an explicit execute flag plus recorded backup identifier.
- Every phase writes a checkpoint and is idempotent or safely restartable.
- Writer health/readiness prevents reopening while required projection or embedding gates fail.
- Rollback before legacy cleanup restores the database backup and previous application image; archived legacy evidence is never the sole rollback mechanism.
- Counts are not enough: reconciliation checks referential integrity, provenance coverage, unresolved reasons, taxonomy content hashes, duplicate/primary constraints, API serialization, and representative UI/search flows.

## Testing strategy

- Test through each deep Module's external Interface with PostgreSQL-backed integration fixtures; internal normalizers may have focused pure tests.
- Replace shallow route/repository behavior tests with Interface contract tests where they duplicate the same rules.
- Source adapters have fixture-based tests for all three Sources, including multiple paths and employment labels.
- Decision contract suites run against Job Taxonomy, Skill, and Company Industry adapters: valid transition, invalid target, stale version, idempotent replay, conflicting replay, audit/outbox atomicity, and worker-interface isolation.
- Backend response-model fixtures feed frontend contract tests; hand-built incomplete payloads do not define the contract.
- Cutover tests restore a representative legacy snapshot and prove dry-run, execute, restart, reconciliation, and rollback.

## Important trade-offs and rejected alternatives

- Rejected one generic taxonomy Module: shared shape would leak domain-specific rules into callers and produce a shallow Interface.
- Rejected legacy scalar compatibility as permanent state: it preserves ambiguity and prevents correct cardinality.
- Rejected AI-created nodes and fallback buckets: they hide uncertainty as governed knowledge.
- Rejected full authentication/RBAC in this program: single-user local mode is sufficient, explicitly not secure for untrusted exposure.
- Rejected in-place mutation of taxonomy releases: immutable revisions preserve reproducibility and audit.
- Rejected GICS as Company Industry authority: proprietary market-sector scope is the wrong seam and licensing model.

## Cross-task dependencies

- `source-job-attributes` may consume the published Source Catalog identity/revision contract from the separate Task Control Board program, but it must remain operable for historical evidence whose catalog revision is unknown.
- Children 2–5 depend on foundation contracts.
- Product surfaces depend on reviewed child 2–5 read/write contracts.
- Cutover depends on child 2–5 schemas/rebuild commands; parent integration requires both product surfaces and cutover validation.

