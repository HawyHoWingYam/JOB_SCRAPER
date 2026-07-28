# Technical design

## Design principle

The target system has one current state. It does not publish, activate, select,
compare, or roll back application data versions. Complexity is concentrated in
four deep modules with small interfaces:

1. `SourceClassificationRegistry`
2. `CurrentTaxonomyStore`
3. `ClassificationBatchRuntime`
4. `SandboxCutover`

Source-specific adapters remain real seams because JobsDB, OfferToday, and
CTgoodjobs discover classifications and compile queries differently.

## Target data flow

```text
Source adapter refresh ──> SourceClassificationRegistry ──> top-level crawl choices
         │                            │
         └── Job ingest ──────────────┴──> preserved Job path evidence

top-level crawl scope ──> Source adapter compile/fallback ──> dispatch/run

Job/Company/evidence ──> ClassificationBatchRuntime ──> CurrentTaxonomyStore
                                   │
                                   └──> progress / failed retry / direct correction
```

No edge carries an application revision, release, active pointer, schema
version, expected version, or embedding version.

## Module 1: SourceClassificationRegistry

### Interface

```python
synchronize(source_site, observed_classifications) -> SyncResult
observe_path(job_id, source_site, captured_path) -> ProjectionResult
list_top_level(source_site, *, active_only=True) -> tuple[SourceClassification, ...]
resolve_scope(authored_scope, source_adapter) -> ResolvedRunScope
```

Callers know Source-qualified IDs, labels, top-level/child relationships, active
status, and whether scope resolution succeeded. They do not know discovery
candidates, catalog revisions, fingerprints, publication state, or repair state.

### Ordinary schema

`source_classifications` owns the current registry:

- stable UUID primary key
- `source_site`
- Source-native `classification_id`
- current label
- nullable parent registry ID
- depth / top-level marker
- active flag
- first/last observed timestamps
- uniqueness on `(source_site, classification_id)`

Existing Job Source Classification Path and Path Node tables remain evidence
snapshots but drop catalog revision relationships and projection version fields.

### Synchronization

- A successful complete adapter synchronization upserts observed identities,
  labels, and hierarchy and marks previously active missing top-level identities
  inactive.
- Failed or partial discovery never marks identities inactive.
- Job ingestion uses `observe_path` as an idempotent fallback and never infers
  identity from label.
- The registry never physically deletes a top-level classification.

### Query compilation seam

Each Source adapter accepts the top-level scope and returns one or more current
query targets. An adapter may use a direct category query or a documented broader
query plus post-collection filtering. Unsafe or malformed targets fail before
dispatch. No generic full-site fallback is invented by the registry.

## Module 2: CurrentTaxonomyStore

### Interface

The external interface is current-state only:

```python
job_taxonomy() -> JobTaxonomyTree
assign_job(command) -> JobAssignment
company_industries() -> CompanyIndustryTree
assign_company(command) -> CompanyIndustryAssignment
skills() -> SkillTree
resolve_or_create_skill(command) -> SkillResolution
optional_job_slice(source_path) -> tuple[JobSubcategoryId, ...] | None
```

### Canonical Job Taxonomy

- Keep the current 25/63/198 hierarchy and stable node IDs/codes.
- Remove release and active-pointer tables and all `revision_id` columns.
- Parent/child FKs become ordinary stable-ID FKs.
- Current and historical accepted Job assignments reference stable Subcategory
  IDs directly. Preserve method, evidence, breadcrumb, current/superseded state,
  audit IDs, and timestamps without taxonomy/mapping versions.
- Delete per-item review/recommendation rows. Unassigned Jobs are selected by
  current assignment absence plus processing status, not a review queue.

### Optional Source mappings

- Drop mapping releases, active mapping pointers, coverage, identity hashes, and
  complete-coverage validation.
- Keep useful current mapping rows keyed by `(source_site,
  source_classification_id)` and target rows keyed by stable Job Subcategory ID.
- A mapping may constrain AI. No mapping returns `None`, which means the full
  current Job Taxonomy is available.

### Company Industry

- Flatten only the current HSIC hierarchy/crosswalk/mappings to stable ordinary
  rows and direct FKs.
- Accepted Company assignments reference stable Industry node IDs.
- Delete per-item review/recommendation rows; select work from missing/current
  assignment state.

### Skills

- Flatten current Skill categories, technologies, skills, and aliases to stable
  ordinary IDs.
- Preserve governed Job Skill mentions/projections and unresolved normalized
  Candidate evidence without taxonomy revision columns.
- Candidate metrics remain derived from mentions.
- `resolve_or_create_skill` reuses aliases/duplicates first. At the Settings
  threshold (default five distinct Jobs), automated validation chooses an
  existing Category/Technology and creates the Skill. Generic or uncertain
  evidence remains failed/unresolved.

### Data integrity without versions

Keep stable-ID uniqueness, hierarchy/check constraints, current-assignment
uniqueness, status transitions, evidence hashes, audit, idempotency, and
transactional outbox where still needed. Remove only version identities and
stale-version comparison. Direct edits are last-write-wins.

## Module 3: ClassificationBatchRuntime

### Interface

```python
preview(domain, filters, limit) -> BatchPreview
start(domain, filters, limit) -> BatchRun
status(run_id) -> BatchRun
retry_failed(run_id) -> BatchRun
request_stop(run_id) -> BatchRun
```

Domain adapters implement candidate selection and one-item processing for
`job-taxonomy`, `company-industry`, and `skills`. Shared orchestration owns
oldest-first bounded selection, run/item status, progress, stop, retry, and
error projection.

The frontend exposes three ordinary batch surfaces with the AI Enrichment
interaction model. There is no Governance queue, release selector, or per-item
decision requirement. A direct correction link may open the Job/Company detail
editor.

Batch run tables are current operational infrastructure. The cutover starts them
empty; future runs may create new history normally.

## Unversioned protocols

### API

- Mount current endpoints at root application paths instead of `/api/v1`.
- Remove route version selectors such as Task Control Board V1/V2 and retain one
  current response shape.
- Frontend `apiPath` targets the root API base.

### Events and projections

- Remove event/payload `schema_version` and application projection `version`
  fields.
- Producers and consumers deploy as one atomic code set.
- Event ID, type, aggregate identity, occurrence time, payload, idempotency, and
  outbox delivery state remain.

### Automations and edits

- Keep only the current Automation row/configuration/lifecycle.
- Drop immutable Automation revision snapshots, expected revision, ETags,
  revision-bound delete reviews, and stale-revision errors.
- Use complete transactional writes; later writes win.
- Newly created dispatch plans freeze their own current resolved scope and
  limits, but do not point to an Automation or Catalog revision.

### Embeddings

- Keep Job ID, vector dimensions, document text/hash, vector, and update time.
- Drop persisted embedding model/version identity and freshness comparison by
  model/version.
- Current vectors are imported without compatibility checks. A future model
  switch invokes an explicit full-index reset/rebuild operation.

## Module 4: SandboxCutover

### Interface

```python
export_retained(output_dir) -> RetentionManifest
create_target_schema() -> None
import_retained(input_dir, manifest) -> ImportReport
verify_retention(before, after) -> VerificationReport
clear_runtime_state() -> None
```

This is an operator-only one-time module, not a migration framework.

### Retained artifact

The export contains only data named in PRD R9. It includes stable source IDs,
content hashes/counts for verification, and old-to-new identity maps needed to
flatten revision-pinned nodes. It excludes all task/run/release/version state.

The artifact is deleted after successful verification. It is not a backup.

### Target schema creation

Replace Alembic with one current empty-database bootstrap owned by the backend.
It creates extensions, tables, constraints, indexes, and any required triggers
directly and refuses to mutate a non-empty/incompatible database.

### Cutover sequence

1. Refuse unless all API/frontend/workers/scheduler/helpers are stopped.
2. Export retained data and compute the before manifest.
3. Clear Redis Streams, groups, pending entries, dead letters, and durable outbox.
4. Destroy the database; create the target schema from the current bootstrap.
5. Import ordinary Source/taxonomy data, then Jobs/Companies/evidence, then
   accepted assignments/projections/audits, then embeddings.
6. Verify counts, stable identities, hashes, FKs, absence of task/version data,
   and empty queues.
7. Delete the transient artifact; start the complete application atomically.

There is no rollback after artifact deletion. Before deletion, failure recovery
is to fix the target code and rerun create/import/verify from the same artifact.

## Compatibility and operational policy

- No rolling or mixed-code deployment.
- No in-place schema upgrade after cutover. Future schema changes destructively
  rebuild the sandbox unless a new preservation exception is approved.
- Third-party dependency/runtime/model release pins remain.
- Old URLs, payloads, release IDs, task IDs, and task history receive no
  compatibility layer.

## Verification strategy

- Architecture searches assert forbidden production version/release symbols,
  columns, routes, and pages are absent; allowlist external dependency strings.
- Cross-source contract tests cover Source sync, inactivity, label update,
  top-level authoring, child evidence, and adapter query/fallback behavior.
- Taxonomy migration fixtures prove stable node/assignment/evidence remapping.
- Batch tests cover preview/start/progress/stop/retry for all three domains.
- Skill tests cover Settings threshold and every validation branch.
- Cutover integration uses a disposable populated PostgreSQL/Redis fixture and
  compares before/after manifests while asserting zero old task/version state.
- Frontend lint/tests/build and full backend tests run only after the atomic
  target code set is complete.
