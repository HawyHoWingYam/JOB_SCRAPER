# Company Industry Governance

## Scenario: Govern Company Industry with immutable HSIC V2.0 revisions

### 1. Scope / Trigger

Use this contract when changing the committed HSIC seed, Company Industry
publication or activation, company-owned Industry evidence, Source Industry
mappings, Company assignments/reviews, governance decisions, Company Industry
reads/filters, the compatibility projection, the rebuild inspector, or the
Company Industry Alembic migration.

Company Industry is downstream governed knowledge. Job Source Classification
is crawl/job evidence and must never be copied into `Company.industry`, an
Industry assignment, or a reusable Industry mapping. The legacy nullable
`companies.industry` scalar remains comparison/manual evidence through the
cutover rollback window; it is not governed read or filter authority.

This contract permits explicit materialization and activation in tests or
operator code. Migration, application startup, ingest, and the read-only
inspector must not publish, activate, backfill, or mutate the live corpus.

### 2. Signatures

The publication and domain seams are:

```python
CompanyIndustryPublisher.validate(seed) -> ValidationReport
CompanyIndustryPublisher(db).materialize(seed) -> RevisionRef
CompanyIndustryPublisher(db).activate(
    revision,
    expected_lock_version: int,
) -> CompanyIndustryActivationRef

CompanyIndustryEvidenceAdapter.extract(canonical_job) -> CompanyIndustryEvidence | None
project_company_industry(db, company_id, canonical_job) -> CompanyIndustryOutcome | None

CompanyIndustry(db).ingest_evidence(
    company_id,
    evidence,
) -> CompanyIndustryOutcome
CompanyIndustry(db).get_active_revision() -> CompanyIndustryRevisionView
CompanyIndustry(db).get_tree(parent_id=None) -> CompanyIndustryTreeView
CompanyIndustry(db).get_breadcrumb(node_id) -> tuple[CompanyIndustryNodeView, ...]
CompanyIndustry(db).get_company_state(company_id) -> CompanyIndustryCompanyStateView
CompanyIndustry(db).list_review_items(query) -> CompanyIndustryReviewPage
CompanyIndustry(db).list_mappings(...) -> tuple[SourceIndustryMappingView, ...]
CompanyIndustry(db).build_company_filter(node_ids) -> SQL predicate
CompanyIndustryDecisionAdapter(db).decide(command) -> DecisionResult
CompanyIndustryRebuildInspector(db).inspect(company_ids=None) -> CompanyIndustryRebuildReport
CompanyIndustryCompatibilityAdapter(db).project(company_id) -> projection
```

Versioned HTTP routes are:

```text
GET  /api/v1/job-intelligence/company-industries/revision
GET  /api/v1/job-intelligence/company-industries/tree?parent_id=...
GET  /api/v1/job-intelligence/companies/{company_id}/industries
GET  /api/v1/job-intelligence/governance/company-industries/review-items
GET  /api/v1/job-intelligence/governance/company-industries/review-items/{id}
POST /api/v1/job-intelligence/governance/company-industries/review-items/{id}/decision
GET  /api/v1/job-intelligence/governance/company-industries/mappings
GET  /api/v1/job-intelligence/governance/company-industries/audit-events
```

The read-only operator command is:

```text
python backend/scripts/inspect_company_industries.py \
  [--format json|human] [--company-id <uuid>]...
```

PostgreSQL migration/constraint tests require an explicit disposable database:

```text
JOB_INTELLIGENCE_TEST_DATABASE_URL=postgresql://.../<dedicated_test>
```

The database name must end in `_test`. Never point this key, downgrade tests,
seed materialization tests, or raw guard checks at the live corpus.

### 3. Contracts

#### HSIC seed and release lifecycle

- `backend/app/data/hsic_v2.json` is a derived, attributed HSIC V2.0 seed with
  five levels and exactly 21 Sections, 88 Divisions, 221 Groups, 483 Classes,
  and 1,001 Sub-classes (1,814 nodes total).
- Codes, parent codes, bilingual `en`/`zh_hant`/`zh_hans` labels, global source
  order, official URLs, C&SD/HKSAR rights attribution, retrieval metadata, raw
  SHA-256, and documented transformations are part of deterministic identity.
- Validation accumulates code/level/parent/cycle/label/count/hash/crosswalk
  issues. It never publishes a partial or invalid seed.
- `RevisionStore.publish` intentionally commits the immutable Foundation
  identity before domain rows. A later materialization failure may leave only
  the `GovernanceRevision`; this is a retry token, not an active release. Exact
  retry reuses that identity and transactionally creates release, nodes, and
  crosswalks. A partial/mismatched domain release fails closed.
- A domain release remains `materializing` while content is inserted. The ready
  transition recomputes actual node counts. Ready nodes/crosswalks and release
  rows cannot be updated or deleted through ORM or PostgreSQL triggers.
- Activation is explicit and compare-and-swap. The pointer must reference a
  matching ready release and Foundation domain/content hash; insert starts at
  lock version 1 and each update increments exactly once. Pointer deletion is
  forbidden.

#### Crosswalks, mappings, and evidence authority

- Crosswalk edges pin HSIC revision/node and target standard/release/code,
  cardinality, method, provenance, confidence, and source order. Only explicit
  `official` or `project_validated` edges are accepted. Never infer an ISIC
  Rev.5 edge from HSIC's ISIC Rev.4 lineage.
- `SourceIndustryMapping` is created only by a confirmed local-operator review
  decision. One active `(source_site, key_kind, normalized_key)` exists at a
  time. Historical states require `superseded_at`; active rows forbid it.
- A mapping's `decision_audit_id` identifies the decision that created that
  reusable authority. Reusing the mapping for another review must not overwrite
  the originating audit reference.
- Automatic assignment accepts only (a) valid HSIC code/path evidence in the
  active revision or (b) an active operator-approved deterministic mapping.
- The automatic Source adapter accepts company-owned OfferToday
  `raw_data.company_industry` or OfferToday `raw_data.industry.name`. It rejects
  every JobsDB/CTgoodjobs payload, even when a job taxonomy field is named
  `industry` or resembles an Industry label.
- Manual text, AI recommendations, invalid codes, unmapped labels, and
  conflicting evidence create Review Items and no assignment. AI never creates
  a node, mapping, assignment, or Primary.

#### Assignment, review, and transaction semantics

- A Company has zero-to-many active assignments at the most specific supported
  node. Ancestors are derived from the pinned hierarchy and are never duplicated
  as assignment rows.
- There is at most one active assignment per `(company_id, node_id)` and at
  most one active explicit Primary per Company. Primary basis is only
  `authoritative_source` or `operator`; row order and AI confidence never infer
  Primary.
- Exact assignment identity replay (revision/node/evidence hash/method/mapping)
  is a no-op and emits no duplicate outbox event. Changed evidence for the same
  node marks the old row `superseded` with `superseded_at`, creates the next
  version, and preserves an existing explicit Primary unless a confirmed action
  changes it.
- Assignment and Review evidence hashes are lowercase 64-character SHA-256
  values in both ORM metadata and the migration. Active/superseded timestamp
  checks are database-enforced.
- `ingest_evidence` and `project_company_industry` flush but never commit. Each
  authoritative writer performs Company upsert, Industry projection, remaining
  Job projections, and one outer commit on the same `Session`; projection
  failure rolls back Company/Job/Industry/outbox effects together.
- Manual `POST /companies` retains the legacy scalar for rollback comparison
  and creates `manual_evidence` review in the same transaction. It never turns
  free text directly into an assignment.
- Human actions are `assign_existing_industry`,
  `assign_existing_primary_industry`, `approve_mapping_and_assign`,
  `approve_mapping_and_assign_primary`, `mark_insufficient_evidence`, and
  `mark_not_company_industry`. They use Foundation confirmation, fixed
  `local-operator`, expected version, idempotency, append-only audit, and the
  existing outbox in one transaction.
- Workers/adapters may call evidence projection only. They must not import or
  receive `DecisionCommand`, `GovernanceUnitOfWork`, or the Company Industry
  decision adapter.

#### Reads, filters, compatibility, and rebuild

- Tree reads are lazy by `parent_id`; node payloads include stable UUID, code,
  level, bilingual labels, source order, revision, and breadcrumbs where
  applicable.
- Company state returns complete assignment and review-reference arrays.
  Ancestor filters expand descendants inside the active revision and match any
  active assignment; display labels and `companies.industry` are excluded.
- The legacy Job Browser `industry` request field is retired. Any non-empty
  value fails validation with `industry is retired; use
  company_industry_node_ids`; the compatibility `industries` option array is
  returned empty. Never translate display text or restore direct
  `Company.industry` equality as a fallback predicate.
- Review pagination is newest-first by `(created_at, id)` with a stable cursor.
  Mapping and audit reads expose operator provenance and immutable audit IDs.
- Compatibility projection returns the explicit governed Primary, a single
  governed assignment when unambiguous, `ambiguous_governed` for multiple
  non-Primary assignments, or legacy scalar evidence when no governed rows
  exist. It never picks the first assignment as Primary.
- The rebuild inspector is deterministic and read-only. It reports polluted,
  recoverable, legacy-review, conflicting, and no-evidence Companies plus
  mapping/Primary summaries. The CLI rejects `--apply`, `--execute`, and
  `--activate` before opening a database session.

### 4. Validation & Error Matrix

| Condition | Required result |
|---|---|
| Seed hierarchy/count/labels/hash/provenance invalid | Deterministic validation report; no Foundation/domain write |
| Domain materialization fails after Foundation identity publication | Roll back domain rows; exact retry reuses identity and can become ready |
| Ready counts differ from actual nodes | PostgreSQL rejects ready transition |
| INSERT after ready or UPDATE/DELETE node/crosswalk | PostgreSQL immutability error |
| Active pointer is stale, not-ready, wrong-domain, or hash-mismatched | Reject without pointer mutation |
| Taxonomy not active | `404 / COMPANY_INDUSTRY_TAXONOMY_NOT_ACTIVE` |
| Active revision internally inconsistent | `409 / COMPANY_INDUSTRY_ACTIVE_REVISION_INVALID` |
| Parent/node/Company/Review Item missing | Stable `*_NOT_FOUND` code with HTTP 404 |
| Review cursor/filter/status/limit invalid | Stable `COMPANY_INDUSTRY_REVIEW_*_INVALID`, HTTP 422 |
| Audit cursor invalid | `422 / COMPANY_INDUSTRY_AUDIT_CURSOR_INVALID` |
| Unknown descendant filter node | `COMPANY_INDUSTRY_FILTER_NODE_INVALID`; no fallback match |
| Legacy Job search `industry` is non-empty | HTTP/Pydantic 422 directing the caller to `company_industry_node_ids`; no scalar predicate |
| Manual, AI, unmapped, invalid, or conflicting evidence | Active review; zero assignment |
| Exact evidence/outcome replay | `changed=false`; no duplicate assignment/review/outbox |
| Changed same-node evidence | Supersede old row with timestamp; create next active version |
| Mapping reused by another decision | Preserve original mapping `decision_audit_id` |
| Unconfirmed/stale/missing/conflicting-idempotency decision | Stable governance error; no partial writes |
| Rebuild CLI receives apply/execute/activate | Argument error, exit 2, database session never opened |

### 5. Good / Base / Bad Cases

- **Good:** OfferToday supplies a company-owned HSIC path ending in a Sub-class;
  one assignment targets that leaf, ancestors are derived, and an explicit
  Source Primary remains Primary.
- **Good:** a pre-existing unmapped OfferToday review is resolved by an
  operator-approved mapping; mapping, assignment, review, audit, idempotency,
  and outbox commit once. A second Company reuses the mapping without changing
  its originating audit ID.
- **Base:** a Company has no governed assignment. Product reads return empty
  arrays; compatibility may expose the legacy scalar as evidence, not authority.
- **Base:** Foundation identity exists after a failed domain flush. Activation
  rejects it; exact materialization retry completes it safely.
- **Bad:** copying `source_classification_name`, the first Job category, or a
  JobsDB/CTgoodjobs `industry`-shaped field into Company Industry.
- **Bad:** mutating a ready seed row, inferring Primary by assignment order,
  accepting an AI recommendation, or committing inside Industry projection.

### 6. Tests Required

- `test_company_industry_governance.py` covers official 21/88/221/483/1001
  counts and attribution, validation aggregation, exact release replay,
  failed-materialization identity retry, CAS activation, full 1,814-node
  materialization, bilingual breadcrumbs, most-specific assignment, evidence
  replacement/replay, Primary semantics, mapping creation/reuse audit,
  manual/AI/unmapped reviews, stable API errors, ancestor filters, real response
  fixture roundtrip, compatibility behavior, read-only rebuild, and forbidden
  CLI flags.
- The same file must inventory all authoritative writers and prove
  `upsert_company -> project_company_industry -> outer commit`. At least one
  runtime projection test must prove exact replay and outer rollback; adjacent
  crawl tests must keep their Industry projection test doubles current.
- `test_company_industry_architecture.py` proves workers cannot reference human
  decision interfaces and only the Module constructs assignment rows.
- `test_job_intelligence_response_contracts.py` rejects legacy scalar Industry
  at both the schema and `GET /jobs/search` HTTP boundaries, proves the GET
  replacement accepts stable node IDs, and retains ancestor/descendant
  semantics; `test_source_job_attributes.py` proves filter options publish no
  raw legacy Industry strings.
- `test_company_industry_migration.py` covers additive/no-data migration,
  application-level 1,814-node plus crosswalk materialization against the
  migrated schema, ready/content/CAS guards, Primary uniqueness, hash/timestamp
  constraints, crosswalk UPDATE/DELETE rejection, and downgrade cleanup.
- Run PostgreSQL tests only against a dedicated `*_test` database. Because
  combined collection has a known interaction, sequential per-file execution
  is the accepted full-suite fallback; do not report a hanging combined run as
  a pass.

### 7. Wrong vs Correct

#### Wrong: treat a Job classification as Company Industry

```python
company_data["industry"] = canonical_job["source_classification_name"]
company_repository.upsert_company(db, company_data)
```

This destroys the Source/Company boundary, invents governed authority from a
job role, and commits before review/audit/outbox policy can run.

#### Correct: project company-owned evidence in the outer writer transaction

```python
company, _ = company_repository.upsert_company(
    db,
    company_data_without_industry,
    auto_commit=False,
)
project_company_industry(db, company.id, canonical_job)
job, _ = job_repository.upsert_source_job(
    db,
    job_data,
    auto_commit=False,
)
db.commit()
```

The Source adapter rejects job-taxonomy evidence, the Module creates only an
authoritative assignment or unresolved review, and one outer transaction owns
all effects.
