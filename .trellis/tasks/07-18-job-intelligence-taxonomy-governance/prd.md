# Job intelligence taxonomy and skill governance

## Goal

Establish a coherent post-collection domain model and independently verifiable remediation program for Canonical Job Taxonomy, Source Classification Paths, Employment Types, Company Industries, governed Skills, and review evidence so frontend language, backend behavior, database constraints, enrichment, search, analytics, recommendations, and governance agree.

## User value

- Users can distinguish Source-owned evidence, governed project knowledge, and unresolved review items.
- Filters and analytics operate on stable identities and documented semantics rather than raw-string coincidences.
- Taxonomy changes and human decisions are reviewable, observable, deterministic, and auditable.
- The existing Job/Company corpus can be retained while polluted derived intelligence is rebuilt safely.

## Background and confirmed facts

- This is a separate post-collection parent program. `07-18-task-control-board-ui` remains responsible for pre-dispatch Source Taxonomy, Source Catalog Revisions, Crawl Scope, crawler execution, and control-board UX.
- The cross-layer evidence audit is `research/job-taxonomy-ui-backend-schema-audit.md`; external Industry-standard research is `research/company-industry-taxonomy-standards.md`; the current database snapshot is `research/current-data-migration-inventory.md`.
- The legacy UI calls the canonical hierarchy Job Taxonomy, Classification, and AI Category; calls `employment_type` Job Type; and calls unresolved mentions Provisional Skills (`frontend/src/components/FilterPanel.jsx:127-169`, `frontend/src/components/jobs/AddJobPage.jsx:328-332`, `frontend/src/components/charts/CategoryChart.jsx:96-127`, `frontend/src/components/JobDetailModal.jsx:339-377`).
- `Job` separates one Source classification/subclassification snapshot from one canonical `subcategory_id`, but JobsDB and OfferToday raw payloads may contain multiple source paths that current parsers truncate (`backend/app/models/job.py:68-75`, `backend/app/sources/jobsdb/parsers.py:14-43`, `backend/app/sources/contracts.py:203-226`).
- Company Industry is free text and can be populated from a Job Source Classification (`backend/app/workers/run_ingest_worker.py:311-317`, `backend/app/utils/data_mapper.py:180-199,275-288`, `backend/app/api/jobs.py:337-344`).
- Canonical classifier output outside an allowed slice silently becomes a default path, and `create_new` can introduce a Subcategory (`backend/app/services/job_category_normalizer.py:452-479`).
- Governed Skill and unresolved mention paths exist in code, but the live database snapshot had no governed Skill rows/Job-Skill links, more than 22k review-candidate mentions, and more than 5k pending candidates.
- Static Skill curation references include absent/conflicting Wi-Fi, Vue 3, PCI DSS, Oracle, Jira, and Confluence targets.
- The 2026-07-18 database snapshot had 17,596 Jobs with raw data and 4,657 Companies; all live database Job taxonomy nodes were AI-created, embeddings covered only 2,931 Jobs, and writers were actively changing counts.
- Backend response-model tests do not currently protect the computed taxonomy/governed/unreviewed Skill contract; frontend tests rely on partial hand-built payloads.

## Requirements

### R1 — Scope and ubiquitous language

- Use the terms in `CONTEXT.md`: Canonical Job Taxonomy with Job Domain → Job Category → Job Subcategory; Source Classification Path; Employment Type; Company Industry; Skill, Skill Mention, Skill Candidate, Unreviewed Skill Mention, Taxonomy Operator, and Job Intelligence Projection.
- Retire AI Category, bare canonical Classification, Canonical Job Domain for the whole tree, Job Type, Job Industry, and Provisional Skill(s) from current product/API language.
- Canonical Job Taxonomy, Company Industry Taxonomy, and Skills never become Crawl Scope authorities.

### R2 — Evidence and governance foundation

- Preserve raw Source/company evidence separately from governed projections and attach typed method/source/mapping/model/operator provenance.
- Use immutable revision identity/content hashes, append-only audit, idempotent decisions, optimistic concurrency, and transactional outbox events.
- Run first-version governance in trusted single-user local-operator mode without authentication/RBAC; every decision records `actor=local-operator`.
- Separate human decision Interfaces from worker recommendation/normalization Interfaces. Require explicit confirmation, idempotency key, and expected version; document that local-operator mode is not safe for untrusted network exposure.
- Future authentication must wrap the same domain decision Interfaces without changing domain rules.

### R3 — Source Classification Paths

- A Job has zero or more ordered Source Classification Paths and preserves every Source-returned classification/subclassification and label snapshot (`docs/adr/0005-preserve-all-source-classification-paths.md`).
- A path is Primary only when the Source explicitly declares it; order/name/local inference never implies Primary.
- Historical evidence may have an unknown Source Catalog Revision but remains queryable with visible provenance limitations.
- Compact UI may show one path plus `+N`; detail and filters use all paths and source-qualified identities.

### R4 — Employment Types

- Replace the free-text scalar with zero-to-many governed values: Full-time, Part-time, Permanent, Contract, Temporary, Internship, and Freelance (`docs/adr/0008-model-employment-type-as-controlled-multi-value.md`).
- Preserve ordered Source Employment Labels/codes. Unknown/unmapped labels create no governed value and never collapse into Other.
- Work Arrangement and working-day concepts remain independent.
- Filters are stable multi-select values, never exact comparisons against comma-joined raw text.

### R5 — Canonical Job Taxonomy assignments

- Publish a validated immutable governed taxonomy revision; AI never creates Domain/Category/Subcategory nodes.
- Automatically accept only a reviewed deterministic mapping to an existing governed Subcategory or a structurally valid AI selection inside the Source-bound allowed slice (`docs/adr/0007-leave-uncertain-job-taxonomy-unassigned.md`).
- Record mapping/model/provider/version/method/evidence for every accepted assignment.
- Invalid, out-of-slice, unknown, fallback/default, and `create_new` outcomes remain Unassigned and create Job Taxonomy Review Items.
- Taxonomy Operator decisions may assign an existing Subcategory or record insufficient evidence; they cannot mutate taxonomy nodes from an item.

### R6 — Company Industry governance

- Replace free text with a project-owned Company Industry Taxonomy with stable identities (`docs/adr/0009-govern-company-industry-with-stable-taxonomy.md`).
- Seed immutable append-only revisions from C&SD's current five-level bilingual HSIC V2.0 hierarchy (`docs/adr/0011-seed-company-industry-taxonomy-from-hsic-v2.md`; `research/company-industry-taxonomy-standards.md`).
- Optional ISIC mappings require an explicit revision and published/project-validated provenance; HSIC's ISIC Rev.4 lineage never implies Rev.5 mapping.
- A Company has zero or more provenance-bearing assignments; at most one Primary exists, based only on authoritative Source declaration or Taxonomy Operator decision (`docs/adr/0010-allow-multiple-company-industries.md`).
- Assign at the most-specific evidence-supported HSIC node, derive ancestors without duplicate assignments, and use subtree semantics for ancestor filters (`docs/adr/0012-assign-company-industry-at-most-specific-supported-level.md`).
- Automatically assign only from an authoritative valid HSIC code or Taxonomy Operator-approved deterministic Source Industry mapping. Unmapped Source labels, manual text, and AI inference create Company Industry Review Items; AI recommendations never execute or create nodes/Primary (`docs/adr/0013-require-reviewed-company-industry-mappings.md`).
- Remove every Source Classification → Company Industry write and preserve legacy/source/manual/AI values as evidence only.

### R7 — Skill governance

- Publish a validated governed Skill Category → Technology → Skill revision after resolving all static reference/alias/curation conflicts.
- Treat Skill Mentions as Job-level evidence and Skill Candidates as aggregated unresolved potential Skills; only governed Skills enter ordinary search, recommendations, analytics, and embeddings.
- Reviewed deterministic aliases/generic/suppression rules may resolve before Candidate creation; fuzzy/AI output is advisory.
- Only the human Taxonomy Operator may merge a Candidate, create a valid governed Skill, classify generic, or reject (`docs/adr/0006-require-human-decisions-for-skill-candidates.md`).
- One decision transaction updates every affected active Mention, Job-Skill projection, Candidate state/metrics, audit, and outbox.

### R8 — Governance and product surfaces

- Provide one `Job Intelligence Governance` product area with peer Job Taxonomy Review, Skill Candidates, and Company Industries sections.
- Each section provides backlog/filters, stable queue, evidence, advisory recommendations, explicit confirmation, stale-conflict handling, audit, deep links, loading/empty/error/Unknown states, responsive behavior, and accessibility.
- In the product UI, governance decisions exist only in that area; Job Detail, Companies, AI Enrichment, Dashboard, and other product surfaces remain read-only and deep-link. This placement is not an authorization boundary; R2's trusted-local deployment constraint applies.
- Job Browser/Detail/Add Job/Companies/AI Enrichment/Dashboard use stable IDs, complete arrays/breadcrumbs, governed versus unresolved states, and the ubiquitous language.

### R9 — Contracts, persistence, and downstream intelligence

- Define versioned request/response contracts; OR values within one filter field and AND across fields. Company Industry ancestor filters include descendants.
- Enforce constrained statuses/resolutions, FK/delete/retirement behavior, uniqueness/Primary rules, required indexes, and revision/provenance/audit coverage in PostgreSQL.
- Backend response-model fixtures are the source for frontend contract tests; partial UI mocks do not define contracts.
- Search, stats, recommendations, and embeddings consume governed projections. Embeddings include accepted Canonical Job Taxonomy and governed Skills and exclude Candidate/generic/rejected evidence.
- Resolve the multi-source list versus JobsDB-only detail category API inconsistency without making it a Crawl Scope authority.

### R10 — Cutover and rebuild

- Preserve the core Job/Company corpus, source identities, raw payload/metadata, descriptions, URLs, dates, salaries, unrelated enrichment, and an immutable legacy audit snapshot (`docs/adr/0014-rebuild-job-intelligence-projections.md`).
- Destructively rebuild only the derived Job Intelligence Projection and governed seed state for Canonical Job Taxonomy, Source Classification Paths, Employment Types, Company Industry, Skills, and embeddings in dependency order from preserved raw evidence.
- Quiesce all writers, take/test a consistent backup, pin schema/taxonomy/model hashes, default commands to dry-run, checkpoint every phase, reconcile all projections, and fail closed on uncertainty.
- Unsupported evidence becomes Unknown/Unassigned/review rather than a compatibility guess.
- Reopen writers only after database/API/search/frontend/embedding gates pass; retain the previous image/database backup and legacy columns through the rollback window.

### R11 — Quality and planning gates

- Each child owns cross-layer tests for its Interface and real PostgreSQL behavior; final testing is not deferred to a separate task.
- Complex parent/child `prd.md`, `design.md`, and `implement.md` artifacts must converge and receive user review before any `task.py start`.
- No frontend, backend, schema, seed-data, or live migration implementation is authorized during planning.

## Child task map

1. `job-intelligence-foundation` — revision/provenance/audit, local decision isolation, seed-validation, compatibility, and common contracts.
2. `source-job-attributes` — Source Classification Paths and Employment Types. Depends on child 1.
3. `canonical-job-taxonomy-governance` — governed seed, assignments, Unassigned/review, decisions. Depends on child 1.
4. `company-industry-governance` — HSIC revisions, assignments, mappings, review, crosswalks. Depends on child 1.
5. `skill-governance` — governed Skill revision, Mentions/Candidates, human decisions. Depends on child 1.
6. `job-intelligence-product-surfaces` — governance workspace and all read-only product surfaces. Depends on reviewed children 2–5 contracts.
7. `job-intelligence-cutover-rebuild` — backup/snapshot/rebuild/reindex/reconciliation/rollback. Depends on children 2–5 schemas/rebuild logic; parent integration requires both 6 and 7.

The parent owns terminology, source requirements, final integration acceptance, and release coordination. Every child repeats its real dependencies in its own artifacts; tree position is not dependency metadata.

## Acceptance Criteria

- [ ] AC-R1: `CONTEXT.md`, UI, APIs, docs, and tests consistently distinguish Source evidence, governed knowledge, and review items; retired terms remain only in legacy/audit context.
- [ ] AC-R2: Revision/provenance/audit/idempotency/concurrency/outbox behavior is atomic, deterministic, records `local-operator`, and is unreachable through worker recommendation Interfaces.
- [ ] AC-R3: All three Sources preserve complete zero-to-many paths without inferred Primary; stable qualified filtering and historical unknown-revision behavior pass.
- [ ] AC-R4: Only the seven Employment Types appear as governed values; raw labels/order survive, Unknown never becomes Other, and Work Arrangement remains separate.
- [ ] AC-R5: Assignments target existing governed Subcategories with complete provenance; every uncertain/fallback/create-new outcome remains Unassigned/review, and AI cannot create nodes.
- [ ] AC-R6: Complete immutable HSIC hierarchy, assignment cardinality/Primary/most-specific/subtree rules, reviewed mappings, review items, and pollution repair pass deterministic tests.
- [ ] AC-R7: Skill seed/curations are reference-clean; Candidate decisions are human-only, atomic across Mentions/Job-Skills, and only governed Skills reach downstream intelligence.
- [ ] AC-R8: Three accessible governance sections and all read-only surfaces render real backend contracts, correct labels/states/deep links, and safe conflict/confirmation behavior.
- [ ] AC-R9: PostgreSQL constraints/indexes, versioned APIs, backend→frontend fixtures, filters, search/stats/recommendations, and embedding documents agree end to end.
- [ ] AC-R10: Dry-run/backup/quiescence/checkpoint/rebuild/reconciliation/rollback rehearsal preserves corpus evidence and passes every gate before writers reopen.
- [ ] AC-R11: All parent/child artifacts validate and are reviewed; no task is started without explicit approval.

## Out of scope

- Source Catalog discovery/publication, Crawl Scope authoring, crawler query semantics, and Task Control Board implementation.
- Automatic name-based cross-source classification as a Crawl Scope authority.
- Authentication, accounts, sessions, and multi-role RBAC; v1 is trusted local-operator mode.
- Deleting the Job/Company corpus or resetting unrelated enrichment.
- Dropping legacy columns before the post-cutover rollback window.
- Any implementation or live migration before the planning review gate.
