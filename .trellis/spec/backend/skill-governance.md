# Skill Governance

## Scenario: Govern Skills while keeping unresolved evidence secondary

### 1. Scope / Trigger

Use this contract when changing the governed Skill seed/rules/backfill manifests,
Skill publication or activation, deterministic extraction, Skill Mentions or
Candidates, human Candidate decisions, Job-Skill projections, Skill reads and
filters, recommendations, embeddings, rebuild inspection, Job Detail Skill
payloads, or the Skill Governance Alembic migration.

The governed Module owns Skill Category -> Technology -> Skill identity,
reviewed aliases/rules, Candidate state, governed Mentions, and the projected
Skills used by product consumers. Legacy `skills`, `skill_review_candidates`,
`job_skill_mentions`, static normalizer writers, and provisional values remain
rollback/comparison evidence only. They are never governed write, filter,
recommendation, analytics, or embedding authority.

This contract permits explicit materialization and activation in tests or
operator code. Migration, startup, normal ingest, AI workers, and read-only
inspectors must not publish, activate, backfill, cut over, or mutate the live
corpus. Live rebuild/cutover and the full governance UI belong to later tasks.

### 2. Signatures

The publication and worker-safe write seams are:

```python
SkillTaxonomyPublisher.validate(bundle) -> ValidationReport
SkillTaxonomyPublisher(db).materialize(bundle) -> RevisionRef
SkillTaxonomyPublisher(db).activate(
    revision,
    expected_lock_version: int,
) -> SkillTaxonomyActiveRevision

SkillGovernance(db).extract(
    job_id: UUID,
    extracted_terms: Sequence[object],
    context: SkillExtractionContext | None = None,
) -> SkillExtractionResult
```

`SkillExtractionContext` contains `source` (default `ai-extraction`), optional
`confidence` in `[0, 1]`, and bounded provenance. Extraction returns the pinned
taxonomy revision, ordered Mention projections, and `changed`.

The read, advisory, decision, and inspection seams are:

```python
SkillGovernanceReader(db).get_active_revision() -> SkillRevisionView
SkillGovernanceReader(db).get_tree() -> SkillTreeView
SkillGovernanceReader(db).search_skills(
    query=None, *, category_code=None, technology_code=None, limit=100
) -> tuple[GovernedSkillView, ...]
SkillGovernanceReader(db).get_job_state(job_id) -> JobSkillStateView
SkillGovernanceReader(db).list_candidates(query) -> SkillCandidatePage
SkillGovernanceReader(db).get_candidate(candidate_id) -> SkillCandidateView
SkillGovernanceReader(db).recommend(candidate_id, *, limit=10) \
    -> tuple[SkillRecommendationView, ...]
SkillCandidateDecisionAdapter(db).decide(command) -> DecisionResult
SkillGovernanceRebuildInspector(db).inspect(job_ids=None) \
    -> SkillGovernanceRebuildReport
```

Versioned HTTP routes are:

```text
GET  /api/v1/job-intelligence/skills/revision
GET  /api/v1/job-intelligence/skills/tree
GET  /api/v1/job-intelligence/skills/search
GET  /api/v1/job-intelligence/jobs/{job_id}/skills
GET  /api/v1/job-intelligence/governance/skills/candidates
GET  /api/v1/job-intelligence/governance/skills/candidates/{candidate_id}
GET  /api/v1/job-intelligence/governance/skills/candidates/{candidate_id}/recommendations
POST /api/v1/job-intelligence/governance/skills/candidates/{candidate_id}/decision
GET  /api/v1/job-intelligence/governance/skills/audit-events
```

The read-only rebuild command is:

```text
python backend/scripts/inspect_skill_governance.py \
  [--format json|human] [--job-id <uuid>]...
```

Persistence is owned by `skill_taxonomy_releases`,
`skill_taxonomy_active_revisions`, `governed_skill_categories`,
`governed_skill_technologies`, `governed_skills`,
`governed_skill_aliases`, `skill_candidates`,
`governed_job_skill_mentions`, and `governed_job_skills`.

The task design's logical names `job_skill_mentions` and `job_skills` map to
the implemented `governed_job_skill_mentions` and `governed_job_skills` tables.
The `governed_` prefix is required because the unprefixed legacy Mention store
already exists and must remain rollback evidence, not authority.

PostgreSQL integration and migration tests require an explicit disposable URL
whose database name ends in `_test`:

```text
JOB_INTELLIGENCE_TEST_DATABASE_URL=postgresql://.../<dedicated_test>
```

Never point this key, activation/concurrency tests, or Alembic downgrade
rehearsals at the live development corpus.

### 3. Contracts

#### Seed, normalization, and immutable release lifecycle

- The committed `skills-2026-07-19-v1` bundle pins
  `skill_taxonomy.json`, `skill_curation_rules.json`, and
  `skill_backfill_curations.json` at schema version 1. It contains exactly 8
  Categories, 33 Technologies, and 91 Skills with explicit stable lowercase
  codes, source order, active/retired state, aliases, provenance, and component
  hashes.
- Validation accumulates and deterministically sorts schema/release mismatch,
  invalid code/order/state/count, orphan path/target, duplicate normalized key,
  alias collision, generic/review/suppression overlap, invalid backfill action,
  and missing merge-target issues. `Other`/`General` fallback nodes are
  forbidden; validation never auto-creates a missing target.
- Text normalization is NFKC, trims and collapses whitespace, maps Unicode
  dashes to `-`, and case-folds. Exact keys preserve `+`, `#`, `.`, `/`, and
  `-`; broad lookup keys discard punctuation. Do not use the broad key where
  `C`, `C++`, `C#`, `.NET`, or similarly symbol-sensitive Skills must remain
  distinct.
- `RevisionStore.publish` intentionally may commit immutable Foundation
  identity before domain materialization. A failed materialization can leave
  only that retry identity; it is not a usable release. Exact retry reuses it.
- Domain content is inserted only while a release is `materializing`. Becoming
  `ready` recomputes actual Category, Technology, seed Skill, and alias counts;
  PostgreSQL rejects mismatches. Ready release/content rows are immutable.
- Activation is explicit and compare-and-swap. It takes a PostgreSQL advisory
  transaction lock, locks the singleton active row, requires a matching ready
  release/content hash, replays the same revision idempotently, and otherwise
  requires `expected_lock_version`. The database requires version 1 on insert,
  exactly `old + 1` on update, and forbids pointer deletion.

#### Mentions, Candidates, and deterministic extraction

- A Skill Candidate is unique by `(taxonomy_revision_id, normalized_key)`.
  Status is one of `pending`, `resolved_merged`, `resolved_created`,
  `resolved_generic`, `rejected`, or `superseded`; the database constrains the
  required Skill/generic/reason/timestamp shape for each status.
- Mention resolution is one of `match_existing`, `review_candidate`,
  `generic_tag`, or `rejected`. Exactly the matching Skill, Candidate, generic
  tag, or rejection reason must be populated. One active normalized Mention
  exists per Job/revision, and superseded evidence keeps history.
- Extraction precedence is exact governed Skill/alias, an already-decided
  Candidate, reviewed generic rule, reviewed suppression rule, then technical
  evidence to one pending Candidate. Other nontechnical evidence is generic.
  Reusing a decided Candidate applies the prior human disposition consistently;
  it is not a new automated decision. Fuzzy/semantic logic never changes this
  outcome.
- Concurrent registration of the same unknown normalized key converges on one
  Candidate. Candidate occurrence and distinct-Job counts are recomputable
  metrics; Mentions are the evidence source of truth.
- Only active `match_existing` Mentions with non-null active Skills produce
  `governed_job_skills`. Projection rebuilds take a per-Job PostgreSQL advisory
  transaction lock, aggregate provenance/maximum confidence/mention count, and
  remove stale rows. Retiring or deleting a Skill cannot silently leave a
  `match_existing` Mention with no target: composite FKs use `RESTRICT`, and a
  successor revision resolves unavailable evidence back to review.
- `extract` flushes but does not commit. Changed Mention/projection state emits
  one `job.skill_projection_changed` event to
  `job-intelligence-projections` with `auto_commit=False`; the authoritative
  outer enrichment writer owns the single commit.

#### Human decisions, audit, and outbox

- Candidate actions are exactly `merge_existing`, `create_skill`,
  `classify_generic`, and `reject`. A create target requires existing active
  Category/Technology codes, an explicit stable code, non-empty name, and
  collision-free aliases.
- Decisions are trusted-local human actions only. Foundation requires
  `confirmed=true`, actor `local-operator`, expected Candidate version, and a
  domain-scoped idempotency key. AI, fuzzy recommendations, workers, and batch
  selectors may inspect/recommend but cannot receive or invoke the decision
  adapter or `GovernanceUnitOfWork`.
- One transaction locks the pending Candidate and every active linked Mention,
  applies the selected disposition to all Mentions, clears Candidate metrics,
  rebuilds every affected Job projection, increments the Candidate version,
  appends immutable audit/idempotency state, and emits one Candidate event plus
  one `job.skill_projection_changed` invalidation per affected Job. Any error,
  including audit/outbox serialization, rolls back all effects.
- Exact idempotency replay returns the original result with `replayed=true` and
  creates no second audit/outbox event. Reusing a key for different content or
  deciding a stale/non-pending Candidate fails with no partial writes.
- Operator-created Skills and aliases are permitted only in the active revision
  and are immutable after creation. Deferred PostgreSQL triggers require their
  one-time `created_by_audit_id` binding to reference the exact
  `skill-governance` / `skill-candidate` audit whose Candidate resolves to that
  Skill. An unrelated valid audit is not sufficient.

#### Reads, recommendations, consumers, and Job Detail

- `JobSkillStateView.skills` contains active governed projections only.
  `unreviewed_skill_mentions` contains only active `review_candidate` Mentions
  attached to pending Candidates, labeled exactly `Unreviewed Skill Mention`,
  with Candidate version/deep link and evidence provenance. Generic and
  rejected evidence is not product-visible.
- Candidate pages default to pending, order stably by recency/ID, and batch
  recommendation/alias loading. Audit pages are newest-first by stable
  `(created_at, id)` cursors. Do not introduce per-item recommendation or alias
  queries.
- Recommendations are advisory-only normalized string similarity. The best
  alias score is retained per Skill and ties order by descending score, Skill
  code, Skill name, then Skill UUID. They never execute a Candidate action.
- Ordinary Job serialization, search/filter clauses, stats, recommendations,
  and embedding documents read active `governed_job_skills` plus the active
  revision. Legacy scalar/JSON/provisional Skill values and pending/generic/
  rejected evidence cannot affect those consumers.
- Job Detail exposes governed `skills: list[str]` separately from structured
  `unreviewed_skill_mentions`. The UI heading is `Unreviewed Skill Mentions`
  with the note `Secondary evidence awaiting human taxonomy review.` When the
  structured array exists it is authoritative, even when empty; only an absent
  array may fall back to legacy `provisional_skills` during compatibility.
- Before the cutover child, the embedding worker handles Skill invalidations in
  addition to existing ingest/enrichment events, but does not subscribe to
  unrelated canonical/source-governance invalidations. It embeds governed Skill
  names only and skips writes when the document hash is unchanged.
- The database integrity report includes active Skill revision/counts,
  Candidate/Mention/projection state. Legacy Candidate audit CLIs remain
  read-only; retired mutation commands reject apply/execute before opening a
  database session. There is no DB-bound Skill normalizer singleton or legacy
  Candidate writer.

#### Rebuild and rollback boundary

- The inspector is deterministic and read-only. Preserved evidence precedence
  is `ai_extraction.skills`, then `ai_enrichment.skills`, then `skills`; it
  reports pinned revision/rule/backfill hashes, outcomes, normalized collisions,
  affected/no-evidence Jobs, and differences from legacy evidence.
- Inspection/legacy commands reject `--apply`, `--execute`, and `--activate`
  (or their equivalent mutation subcommand) before creating a Session.
- The migration is additive and contains no seed publication or data mutation.
  Downgrade drops all nine governed Skill tables and is destructive rollback;
  preserving/rebuilding corpus data belongs to the cutover plan, not Alembic.

### 4. Validation & Error Matrix

| Condition | Required result |
|---|---|
| Seed/rules/backfill schema, path, count, alias, overlap, or target invalid | Deterministically sorted validation issues; no domain materialization |
| No active revision | `404 / SKILL_TAXONOMY_NOT_ACTIVE` |
| Active pointer/release/hash/count inconsistent | `409 / SKILL_TAXONOMY_ACTIVE_REVISION_INVALID` |
| Job or Candidate absent in active revision | `404 / SKILL_JOB_NOT_FOUND` or `SKILL_CANDIDATE_NOT_FOUND` |
| Candidate status, cursor, search/recommendation limit, or audit cursor invalid | `422 / SKILL_*_INVALID`; no writes |
| Resolved Candidate points to unavailable Skill | `409 / SKILL_CANDIDATE_RESOLUTION_INVALID` |
| Exact extraction replay | `changed=false`; no duplicate Mention/projection/outbox |
| Concurrent unknown evidence | One Candidate for the revision/key; complete metrics and Mentions |
| Decision unconfirmed, actor invalid, target/reason missing, or action invalid | Stable governance/Skill decision error, HTTP 422; no writes |
| Decision stale, Candidate non-pending/inactive revision, create/alias collision, or idempotency conflict | HTTP 409 with stable code; no partial writes |
| Exact decision idempotency replay | Original result with `replayed=true`; no new audit/outbox |
| Audit/outbox/projection failure during decision | Roll back Candidate, every Mention/projection, audit, idempotency, and outbox |
| Operator Skill/alias has missing or unrelated Candidate audit | Deferred PostgreSQL constraint error; whole transaction rolls back |
| Ready content mutation, invalid late insert, stale active pointer, or pointer delete | PostgreSQL trigger rejection |
| Rebuild/legacy CLI receives mutation flag | Argument error before Session; zero writes |

### 5. Good / Base / Bad Cases

- **Good:** two Jobs emit the same unknown technical term concurrently. One
  pending Candidate owns two active Unreviewed Mentions; no governed projection
  exists until a local operator decides it.
- **Good:** an operator merges that Candidate at the expected version. Every
  linked Mention becomes `match_existing`, both Job projections rebuild, audit,
  idempotency, Candidate event, and per-Job invalidations commit once.
- **Good:** an operator creates a Skill with a stable code and aliases. The new
  rows are bound to that Candidate's exact audit, then become immutable.
- **Base:** a Job has governed Python plus pending Rust evidence. Ordinary
  consumers see only Python; Job Detail renders Rust under the secondary
  Unreviewed heading.
- **Base:** generic/rejected evidence remains auditable but appears in neither
  governed Skills nor Unreviewed Skill Mentions.
- **Bad:** accepting a fuzzy/AI recommendation, auto-creating `Other/General`,
  selecting the first database row on a tie, or writing a governed Skill from a
  worker.
- **Bad:** committing inside extraction/projection, updating only some linked
  Mentions, using legacy provisional Skills in search/embeddings, or binding an
  operator Skill to an unrelated audit.

### 6. Tests Required

- `test_skill_governance.py`: exact 8/33/91 seed and known reconciliation
  cases; aggregated deterministic validation/hash/replay; inactive
  materialization and activation CAS; concurrent first activation; resolution
  and FK constraints; retirement; exact alias/generic/suppression behavior;
  concurrent Candidate and per-Job projection registration; all four decisions;
  full fan-out, idempotency, and outbox rollback; batched Candidate/job reads;
  stable API errors and real response fixture roundtrip; governed-only search,
  stats, filters, recommendation, embedding, and integrity report; deterministic
  zero-write rebuild and fail-closed legacy commands.
- `test_skill_governance_architecture.py`: workers cannot import human decision
  interfaces; only the Skill Governance Module constructs authoritative rows;
  every consumer excludes legacy Skill authority; AI enrichment extracts before
  its single outer commit; retired singleton/writers and mutation CLIs stay
  fail-closed.
- `test_skill_governance_migration.py`: additive/no-data upgrade; exact tables,
  constraints, indexes, and trigger SQL; real disposable-PostgreSQL
  upgrade/materialize/activate/guard/downgrade rehearsal; ready/content/pointer
  immutability; operator Skill/alias exact-audit binding; unrelated audit
  rejection; downgrade cleanup.
- `test_canonical_job_taxonomy_governance.py` and
  `test_source_job_attributes.py`: adjacent fixtures/writers keep explicit
  governed Skill relationships and transaction boundaries current.
- `JobDetailModal.test.jsx` plus
  `tests/fixtures/skill_governance_responses.json`: mixed governed/unreviewed/
  generic/rejected payloads, structured-array authority, legacy fallback, exact
  secondary label/copy, and backend Pydantic fixture roundtrip.
- Run PostgreSQL tests only with
  `JOB_INTELLIGENCE_TEST_DATABASE_URL` targeting a dedicated `*_test` database.
  Sequential per-file execution with schema reset is the accepted full-suite
  fallback when adjacent integration fixtures leave incompatible schemas.

Targeted gate:

```bash
pytest -q tests/test_skill_governance.py \
  tests/test_skill_governance_architecture.py \
  tests/test_skill_governance_migration.py
ruff check app/job_intelligence/skill_governance \
  app/models/skill_governance.py app/schemas/skill_governance.py \
  app/api/skill_governance.py tests/test_skill_governance*.py
mypy --follow-imports=skip app/job_intelligence/skill_governance \
  app/models/skill_governance.py app/schemas/skill_governance.py \
  app/api/skill_governance.py
```

### 7. Wrong vs Correct

#### Wrong: let AI or a legacy writer create governed authority

```python
recommendation = reader.recommend(candidate.id)[0]
candidate.status = "resolved_merged"
candidate.resolved_skill_id = recommendation.skill_id
db.commit()
```

This bypasses human confirmation, expected-version/idempotency checks, full
Mention fan-out, audit provenance, projection invalidation, and rollback.

#### Correct: keep recommendations advisory and decide through the UoW

```python
recommendations = reader.recommend(candidate.id)  # display only
result = SkillCandidateDecisionAdapter(db).decide(
    DecisionCommand(
        subject_id=str(candidate.id),
        action="merge_existing",
        target_id=str(operator_selected_skill_id),
        expected_version=candidate.lock_version,
        idempotency_key=request_id,
        confirmed=True,
    )
)
```

The fixed local operator selects the target; Foundation locks and versions the
Candidate, the transition updates every Mention/projection, and audit,
idempotency, and outbox effects commit atomically.
