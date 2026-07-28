# Add Job AI Enrichment and Flexible Companies — Design

## Scope and product boundaries

Manual intake and AI processing remain separate workflows:

1. Add Job atomically persists one Manual Job and either references an existing Company or creates one new Company.
2. Add Job never starts Job enrichment or Company-description generation.
3. The existing Job AI Enrichment page batch-processes eligible Manual Jobs through `Origin → Manual Entry`.
4. The existing Companies page runs quantity-driven Generate or Regenerate batches, including eligible Companies created by manual intake.

Job enrichment and Company-description generation remain independent batches on their existing pages.

## Module seams

### `ManualJobIntake` module

The external interface is intentionally small:

```python
ManualJobIntake(db).create(command, *, idempotency_key) -> ManualJobMutationResult
ManualJobIntake(db).update(job_id, command, *, idempotency_key) -> ManualJobMutationResult
```

The implementation hides Company resolution/creation, duplicate-candidate decisions, normalized website handling, Job identity generation, governed Employment Type replacement, operator provenance, enrichment staleness, idempotency replay, and transaction ordering. APIs and tests use the same interface. The module flushes but does not partially commit; the request transaction commits the complete result once.

Create and update share one validated Job-facts shape and one Company-choice union. Update rejects non-Manual Jobs before mutation. Duplicate confirmation is bound to the normalized command and candidate identities so it cannot authorize a different submission.

### `JobEnrichmentEvidence` module

This is a real seam with two adapters:

- a Source adapter backed by `SourceJobAttributes` and Canonical Taxonomy preflight;
- a Manual adapter backed by operator-authored Manual Job evidence and no Source Taxonomy path.

The external interface returns one typed enrichment input plus a stable eligibility result:

```python
JobEnrichmentEvidence(db).inspect(job) -> JobEnrichmentInspection
```

The inspection distinguishes `supported`, `needs_job_description`, and governed Source exclusions. Preview, run creation, overview counts, and worker preflight all consume this same module. The supported input supplies Job facts, governed Employment Types, allowed Canonical Taxonomy context, evidence provenance, and an input fingerprint used for staleness. Callers do not inspect projection-table presence themselves.

The Source adapter preserves the current fail-closed mapping/exclusion contracts. The Manual adapter requires a non-blank description, has no source paths or Source-to-Canonical mapping, and receives the full active assignable Canonical Job Taxonomy.

### Read projection seam

`compose_current_job_detail` remains the single Job Detail serialization seam. Manual origin, structured salary, editable/operator provenance, and intelligence freshness are composed there rather than appended privately by Add Job or Job Detail callers.

Frontend form state and payload normalization should likewise live in one reusable Manual Job form module used by Add Job and Manual Job editing, not duplicated across pages.

## Cross-layer data flow

```text
Add/Edit form
  → validated manual mutation command
  → ManualJobIntake transaction
  → Job + optional Company + Manual evidence + governed Employment Types
  → composed Job Detail response

Persisted Manual evidence
  → JobEnrichmentEvidence inspection
  → overview/filter/preview/run reservation
  → worker repeats the same inspection
  → AI enrichment transaction replaces derived intelligence
  → composed current Job Detail/search projections
```

Validation belongs at the command boundary. Persistence invariants and transaction ordering belong inside `ManualJobIntake`. Eligibility and evidence normalization belong inside `JobEnrichmentEvidence`. Rendering layers consume typed projections and do not reinterpret raw database fields.

## Manual intake command boundary

Replace the frontend's sequential `POST /companies` then `POST /jobs/manual` workflow with one manual-intake command. Its Company input is a discriminated choice:

- existing Company: stable Company UUID
- new Company draft: name plus optional website, location, and Company Industry evidence

The command owns Company/Job creation, governed Employment Type assignments, duplicate-decision evidence, and idempotency in one transaction. A successful response contains the created Job and associated Company but no enrichment result.

An idempotency key identifies one submission. Replaying the same key and command returns the original result; reusing the key for a different command is a conflict. Existing governance idempotency storage demonstrates the key/hash/result pattern, but manual intake should own a domain-appropriate record rather than coupling ordinary creation to governance audit events.

Likely duplicate Companies and Jobs are advisory identity decisions, not uniqueness constraints. The server returns candidate identities and requires an explicit decision token or confirmation on resubmission. Confirmation never silently merges records.

## Evidence and enrichment boundary

`JobSourceAttributeProjection` and its child records remain external-Source-owned. Their database checks, source-qualified classification identities, and taxonomy mappings must not be expanded with a fake `manual` Source.

Introduce an additive Manual Job evidence seam consumed by shared AI enrichment. It represents operator-authored title, description, and optional Job facts without source classification paths. The shared AI context builder must support:

- Source-collected evidence with Source Taxonomy paths;
- Manual Job evidence with no Source Taxonomy paths and the full Canonical Job Taxonomy available for assignment.

Unified pending selection becomes origin-aware. Manual Jobs require a non-blank description; missing-description records are counted as `Needs job description` rather than pending. External Source eligibility retains its Source Attribute Projection requirement.

The origin display/filter contract is additive at the product layer. Existing Source Classification cascade filters apply only to selected external Source origins. Selecting Manual Entry exposes no Source Classification or Subclassification options and must never broaden an explicitly empty Manual selection into all pending Jobs.

For compatibility, existing `source_site="manual"` plus opaque manual Job/Company IDs may remain the storage discriminator used by legacy identity columns. It does not create a Source, a Source Taxonomy, or a Source Attribute Projection. Product Job Origin is derived through the evidence seam: a Source projection yields its external Source origin; a Manual evidence projection yields Manual Entry. New Manual Companies must set the manual compatibility identity explicitly instead of inheriting the JobsDB default.

Operator-authored values are authoritative. Enrichment writes AI summary, governed taxonomy assignment, and governed Skill data. AI experience extraction may fill omitted values but must not overwrite manual experience values; conflicting extraction remains evidence.

## Relevant schema audit

### Company storage and contracts

| Field | Classification | Current use and design decision |
|---|---|---|
| `id` | authoritative identity | Internal UUID and Job foreign key; retain. |
| `company_id` | compatibility identity | Globally unique compatibility key; retain while existing APIs/source backfills depend on it. Manual intake generates it server-side. |
| `source_site`, `source_company_id` | source identity | Authoritative for collected Companies. Manual Company creation currently inherits a misleading JobsDB default; manual intake must establish explicit origin semantics without treating Manual Entry as an external Source. |
| `name` | authoritative fact | Required. Duplicate-name matches are candidates, not identity equality. |
| `website` | missing, needed | Add nullable normalized Company identity evidence. Use in duplicate review and Company-description context; do not require it. |
| `industry` | compatibility/evidence | Free text consumed by legacy displays and Company-description prompting. Retain as evidence; never treat it as a governed Company Industry Assignment. |
| `location` | authoritative/evidence | Retain and include in identity/enrichment context. |
| `ai_description` | derived intelligence | Retain as Company enrichment output. Generate targets blanks; confirmed Regenerate replaces existing content only on success. |
| `ai_description_updated_at` | missing, needed scheduling state | Add nullable timestamp. Successful Generate/Regenerate updates it atomically with the description; Regenerate orders oldest/null first. It is not model/provider provenance. |
| `extra_data` (`metadata`) | audited unused | Remove the column and all repository/source-backfill writes. Do not use it for first-class website data. |
| `is_deleted` | authoritative lifecycle | Retain; repositories, APIs, and enrichment use soft-deletion eligibility. |
| `created_at`, `updated_at` | authoritative audit/sort | Retain. |

Split Company create input from Company response. `ai_description` is output/derived state and is not accepted by ordinary Company creation or the Add Job new-Company draft. The response continues to expose it.

Description-generation model/provider, prompt hashes, Web Search sources, and other evidence remain out of scope. The only added metadata is `ai_description_updated_at`, required for deterministic Regenerate scheduling.

### Job storage and contracts

| Field group | Classification | Current use and design decision |
|---|---|---|
| `id` | authoritative identity | Internal UUID; retain. |
| `job_id` | compatibility identity | Existing global compatibility key; retain. Server generates Manual Job identity. |
| `source_site`, `source_job_id` | collected-source identity | Authoritative for collected Jobs but currently overloaded by Manual Jobs. Add origin semantics rather than admitting Manual Entry into Source Taxonomy contracts. |
| `company_id`, `title`, `description`, `location`, `posted_date` | operator/source facts | Retain. Manual title and Company are required; description remains optional to save but required for Manual Job enrichment. |
| `salary_min`, `salary_max`, `salary_currency` | structured fact | Used by filtering/export/ingestion; retain and add range/currency validation. Response schemas currently omit them and must be aligned. |
| `salary_range` | compatibility/display | Retain while source ingestion and displays use it; exclude it from Manual Job input so it cannot contradict structured salary. |
| governed Employment Type assignments | authoritative governed data | Use `employment_type_codes` for Manual Jobs and preserve operator provenance. |
| legacy `employment_type` | compatibility/source evidence | Do not accept it from the new manual-intake contract; retain storage/read compatibility for collected legacy data. |
| `experience_min_years`, `experience_max_years` | mixed provenance today | Retain values but add explicit operator/AI provenance rules and range validation. Enrichment cannot overwrite operator-authored values. |
| `experience_level`, `experience_summary`, `experience_evidence` | derived intelligence/evidence | Retain. Ensure evidence distinguishes suggestions from accepted operator facts. |
| `ai_summary`, `ai_enriched_at` | derived intelligence/status | Retain; batch state and search depend on them. Response schemas must expose the intended projection consistently. |
| source classification scalar columns | compatibility projection | Retain until legacy/source consumers are migrated; governed taxonomy lives in assignment projections. |
| `raw_data` | source compatibility/evidence | Retain for collected-source evidence. Manual intake should use an explicit manual evidence contract, not synthesize raw source payload. |
| `search_vector` | audited unused | Remove from the current-schema bootstrap; no active consumer was found. |
| `is_deleted`, timestamps | authoritative lifecycle/audit | Retain. |

`JobCreateSchema` belongs to a retired collected-job POST and should not remain the implicit base for every response. Define read schemas around actual product projections, including structured salary and AI fields, rather than inheriting an obsolete create contract.

### Source projection schemas

`JobSourceAttributeProjection`, Source Classification Paths/Nodes, and Source Employment Labels are correctly Source-specific. Retain their three-Source checks and source-qualified identity constraints. Manual evidence must be additive and must not weaken those invariants.

### Validation gaps to close

- normalized, validated optional Company website;
- non-blank trimmed Company name and Job title;
- salary and experience minimum not greater than maximum;
- non-negative salary and experience values where appropriate;
- normalized supported currency code;
- governed Employment Type codes only for the new manual command;
- existing/new Company union exclusivity;
- duplicate-decision token bound to the submitted candidate set/command;
- idempotency key replay and hash-conflict behavior.

## UI shape

The Add Job form shows title, Company combobox/new-Company draft, and description first. Description is labelled `Optional for saving · Required for AI enrichment`. Salary, location, governed Employment Types, posted date, and experience sit under `Optional job details`.

The Company combobox supports keyboard selection, visible search errors, existing candidates, and a non-persisted `New Company` draft. Same/similar Company candidates require an explicit identity choice. The submit button is `Add Job`.

Success confirms persistence only and offers ordinary navigation such as adding another Job or viewing the created Job; it contains no enrichment controls or enrichment-success claim.

Job Detail exposes editing only for Manual Jobs. The edit form reuses the manual form contracts and validations for title, Company, description, structured salary, location, governed Employment Types, posted date, and experience. AI summary, governed taxonomy assignments, and Skills remain outside the direct edit contract. Collected Source Jobs remain read-only.

Editing an enrichment-relevant Manual Job fact marks its existing Job Intelligence stale and returns it to batch eligibility. Previous AI outputs remain visible only with a stale marker. Successful re-enrichment replaces the affected outputs and clears staleness atomically; failed enrichment preserves the old outputs and stale state.

Store an enrichment-input fingerprint/freshness state owned by the Manual evidence/enrichment seam rather than inferring staleness independently in the UI. A mutation compares the normalized enrichment-relevant input; irrelevant changes do not create unnecessary pending work.

## Batch surfaces

### Job AI Enrichment page

- Rename the displayed Source filter concept to `Origin`.
- Add `Manual Entry` alongside JobsDB, CTgoodjobs, and OfferToday.
- Include eligible Manual Jobs in pending counts and runs.
- Show `Needs job description` for Manual Jobs excluded for missing descriptions.
- Preserve existing persisted run progress and failed-item retry behavior.

### Companies page

- Keep the existing independent Company-description batch.
- Newly created Manual Companies with blank descriptions already fit ordinary eligibility.
- Keep Web Search opt-in behavior.
- Provide separate Generate and Regenerate modes. Generate targets blank descriptions; Regenerate targets non-blank descriptions and requires confirmation.
- Both modes accept a positive operator-entered Run size with no product-level fixed maximum. The server freezes `min(requested, eligible)` rows; worker concurrency stays controlled by runtime settings.
- Generate orders by `Company.created_at`, then ID. Regenerate orders null/oldest `ai_description_updated_at`, then Company ID.
- Existing descriptions are excluded from Generate. Regenerate updates description plus scheduling timestamp only after success; failures preserve both old values.
- Persist run mode and requested Run size so monitoring/retry cannot reinterpret intent. Retry of failed items preserves the original frozen Company IDs and mode.

## Database evolution

The repository has no checked-in Alembic migration chain. `bootstrap_database` creates exactly the current metadata and refuses non-empty databases. Schema changes in this task therefore require updated ORM/bootstrap contracts and a documented sandbox rebuild. Online upgrade of a non-empty database is out of scope unless the project's database lifecycle changes.

The sandbox retained-data contract must be updated for every new retained Manual evidence/idempotency field or table and for removal of `Company.extra_data` and `Job.search_vector`. Export/import/verification fixtures must prove the retained Manual Job, Company website, operator facts, and freshness state round-trip exactly through a clean rebuild.

## Rollback shape

Manual intake remains separable from enrichment. If origin-aware batch support must be rolled back, persisted Manual Jobs and Companies remain valid corpus records. The old Source projection invariants remain untouched. Website and manual evidence are additive nullable data, so disabling their consumers does not invalidate existing collected Jobs.

Before a shared sandbox rebuild, rollback is a code/artifact revert and the existing database remains untouched. The requested removal of `Company.extra_data` and `Job.search_vector` is intentionally destructive: those values are excluded from the retained artifact. After successful verification and artifact finalization there is no data rollback, consistent with the sandbox cutover contract; correction requires another complete stopped-service cutover. The operator must inspect the export manifest and removal counts before authorizing clear/finalize.
