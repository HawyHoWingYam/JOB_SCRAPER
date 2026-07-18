# Job intelligence taxonomy and skill governance

## Goal

Establish a coherent post-collection domain model and an independently verifiable remediation plan for Canonical Job Taxonomy, Employment Type, Company Industry, Source Classifications/Subclassifications, governed Skills, and provisional skill candidates so that frontend language, backend behavior, database constraints, enrichment, search, and governance agree.

## User value

- Operators and users can tell which labels came from a Source, which concepts are governed by this project, and which values are still provisional.
- Filters and summaries represent stable, documented semantics instead of accidentally grouping unlike values.
- Taxonomy and skill governance changes are reviewable, observable, and protected by cross-layer contracts.
- Company and job data can be trusted for search, analytics, enrichment, and recommendations.

## Background and confirmed facts

- This task is a separate parent program. The existing `07-18-task-control-board-ui` parent remains responsible for pre-dispatch Source Taxonomy, Source Catalog Revisions, Crawl Scope, crawler execution, and control-board UX.
- The full preliminary evidence audit is `research/job-taxonomy-ui-backend-schema-audit.md`.
- The product currently exposes at least five distinct models behind the seven labels under review:
  - source-owned Classification/Subclassification snapshots;
  - a project-owned canonical Domain → Category → Subcategory tree shown as Job Taxonomy;
  - source-derived `employment_type` shown as Job Type;
  - free-text Company Industry;
  - governed Skills plus unresolved review candidates shown as Provisional Skills.
- `Job` correctly stores source classification snapshots separately from canonical `subcategory_id`, and exposes the full canonical path through `job_taxonomy` (`backend/app/models/job.py:68-75`, `backend/app/models/job.py:185-201`).
- Job Browser calls the canonical path `Job Taxonomy`, Add Job calls the same path `Classification`, and Dashboard calls canonical results `AI Category` (`frontend/src/components/FilterPanel.jsx:142-154`, `frontend/src/components/jobs/AddJobPage.jsx:328-332`, `frontend/src/components/charts/CategoryChart.jsx:96-127`).
- AI Enrichment's `Classifications` and `Subclassifications` are source-native fields, but the labels omit the Source qualifier and options collapse by display name (`frontend/src/components/ai/AIEnrichmentPage.jsx:390-402`, `frontend/src/components/ai/AIEnrichmentPage.jsx:893-911`).
- The `Industry` filter operates on `Company.industry`, while ingest can populate that field from a job's `source_classification_name` (`backend/app/api/jobs.py:337-344`, `backend/app/workers/run_ingest_worker.py:311-317`, `backend/app/utils/data_mapper.py:279-288`).
- `Job Type` is currently a UI label for exact matching against the nullable free-text `Job.employment_type`; there is no separate Job Type taxonomy (`frontend/src/components/FilterPanel.jsx:127-139`, `backend/app/models/job.py:87-95`, `backend/app/api/jobs.py:337-343`).
- Governed Skills are visible `match_existing` mentions. Provisional Skills are unresolved `review_candidate` mentions and are not canonical Skill rows (`backend/app/models/job.py:110-170`, `backend/app/models/job_skill_mention.py:21-39`).
- Skill candidate governance exists as an offline audit/apply script that can merge a candidate into a canonical Skill or reclassify it as a generic tag; Job Detail provides no status, provenance, recommendation, or governance action (`backend/scripts/govern_skill_review_candidates.py:31-138`, `frontend/src/components/JobDetailModal.jsx:339-359`).
- OfferToday persistence reads only the first source job function and first child, while the Job schema can store only one classification and one subclassification snapshot (`backend/app/sources/contracts.py:203-226`, `backend/app/models/job.py:72-75`).
- The multi-source classification list API and JobsDB-only integer detail API have incompatible identity/depth contracts (`backend/app/api/category_routes.py:21-61`).
- Canonical classifier decisions outside the source-bound slice silently become a default path; `create_new` can introduce a new subcategory (`backend/app/services/job_category_normalizer.py:452-479`).
- Embedding documents include source taxonomy and governed Skills but omit the canonical Job Taxonomy path and provisional/generic terms (`backend/app/services/embedding_document_builder.py:22-73`).
- Skill curation rules and backfill targets contain references that do not resolve against the checked static skill taxonomy, including Wi-Fi/Vue 3/PCI DSS aliases and Oracle/Jira/Confluence targets (`backend/app/data/skill_curation_rules.json:3-39`, `backend/app/data/skill_backfill_curations.json:275-281`, `backend/app/data/skill_backfill_curations.json:439-454`).
- Backend tests do not cover computed governed/provisional skill lists, canonical taxonomy serialization, or the Job Detail response contract; frontend tests rely on hand-built partial payloads.

## Confirmed decisions

- Keep this post-collection job-intelligence and skill-governance program separate from the pre-dispatch `task-control-board-ui` program.
- Cross-link shared terminology and contracts, but do not make Canonical Job Taxonomy or Skills an execution authority for Crawl Scope.
- Name the full project-owned hierarchy `Canonical Job Taxonomy`; its levels are `Job Domain → Job Category → Job Subcategory`.
- Do not use `AI Category`, bare `Classification`, or `Canonical Job Domain` to name the full hierarchy. `Job Domain` refers only to its first level.
- Retire `Job Type` as an independent product/domain concept. Rename the current field and UI to `Employment Type`, meaning only the normalized employment relationship such as full-time, part-time, contract, temporary, or internship.
- Do not create a separate Job Type taxonomy; job function remains the responsibility of Canonical Job Taxonomy.
- `Industry` means `Company Industry` only. Do not create a separate Job Industry concept.
- Company Industry may come only from company-owned source data or company-level enrichment. Source Classification must never populate it; absent authoritative data remains Unknown.
- A collected Job has zero or more Source Classification Paths and preserves every classification/subclassification returned by its Source (`docs/adr/0005-preserve-all-source-classification-paths.md`).
- A Source Classification Path is Primary only when the Source explicitly declares it; array order, name matching, or local heuristics must never infer primacy. Compact UI may show one path plus `+N`, while detail and filtering operate over the complete set.
- Use `Skill`, `Skill Mention`, and `Skill Candidate` as distinct domain concepts. A Skill is governed; a Skill Mention is job-level extracted evidence; a Skill Candidate aggregates unresolved mentions awaiting governance.
- Retire `Provisional Skill(s)` from domain and product language. Job Detail may show `Unreviewed Skill Mentions` as secondary evidence, not as governed Skill tags.
- Ordinary skill search, recommendations, and analytics consume only governed Skills; unresolved mentions and Skill Candidates remain outside those result sets until resolved.
- Only a human Taxonomy Operator may make the final decision on a Skill Candidate: create a Skill, merge into an existing Skill, classify as generic, or reject (`docs/adr/0006-require-human-decisions-for-skill-candidates.md`).
- AI recommendations for Skill Candidates are advisory only and never self-executing. Deterministic governed aliases/rules may still resolve a Skill Mention before it becomes a Candidate.
- Add a dedicated `Job Intelligence Governance` product area for post-collection Canonical Job Taxonomy review and Skill Candidate governance.
- Keep `Job Intelligence Governance` separate from pre-dispatch `Source Catalogs` and execution-oriented `AI Enrichment`. Job Detail presents read-only evidence and deep-links to the corresponding governance item.
- Organize `Job Intelligence Governance` into three peer areas: `Job Taxonomy Review`, `Skill Candidates`, and `Company Industries`.
- `Company Industries` owns HSIC revisions, Source Industry Label mappings, Company Industry Review Items, and assignment audit. Company-facing pages remain read-only and deep-link to governance records.
- A Canonical Taxonomy Assignment may be accepted automatically only from a reviewed deterministic mapping to an existing governed Job Subcategory, or a structurally valid AI selection of an existing governed Job Subcategory within its Source-bound allowed slice (`docs/adr/0007-leave-uncertain-job-taxonomy-unassigned.md`).
- Every accepted AI assignment records model, version, method, and evidence. Invalid, out-of-slice, unknown, fallback/default, and `create_new` outcomes leave Canonical Job Taxonomy Unassigned and create a Job Taxonomy Review Item.
- AI never creates Canonical Job Taxonomy nodes. A Taxonomy Operator owns decisions arising from Job Taxonomy Review Items.
- A Job has zero or more controlled Employment Types: Full-time, Part-time, Permanent, Contract, Temporary, Internship, and Freelance (`docs/adr/0008-model-employment-type-as-controlled-multi-value.md`).
- Preserve Source Employment Labels/codes in original order as normalization evidence. Unknown/unmapped labels produce no canonical Employment Type and display Unknown; do not collapse them into `Other`.
- Work Arrangement such as on-site/remote/hybrid and working-day concepts remain independent from Employment Type. Employment Type filters are multi-select over governed values, never exact matching against comma-joined raw text.
- Replace free-text Company Industry with a project-owned Company Industry Taxonomy whose nodes have stable identities (`docs/adr/0009-govern-company-industry-with-stable-taxonomy.md`).
- Preserve company-owned source labels/codes, manual input, and company-level AI output as provenance-bearing evidence. Only mapped governed Industry nodes appear in filters/analytics; unmapped evidence leaves Company Industry Unknown.
- A Company has zero or more provenance-bearing Company Industry Assignments (`docs/adr/0010-allow-multiple-company-industries.md`).
- An assignment is Primary only when an authoritative company source explicitly declares it or a Taxonomy Operator confirms it. Source order, AI output, and display order never imply Primary; filters match any governed assignment.
- Seed the Company Industry Taxonomy from C&SD's current HSIC V2.0, preserving all five levels, bilingual labels, official codes, release identity, and source provenance (`docs/adr/0011-seed-company-industry-taxonomy-from-hsic-v2.md`).
- Company Industry Taxonomy Revisions are immutable and append-only. Optional ISIC mappings require an explicit revision and published/project-validated crosswalk; HSIC V2.0's ISIC Rev.4 lineage never implies an ISIC Rev.5 mapping.
- A Company Industry Assignment may target any HSIC level but must use the most specific node supported by evidence (`docs/adr/0012-assign-company-industry-at-most-specific-supported-level.md`).
- Do not persist ancestor nodes as duplicate assignments. Ancestor filters use subtree semantics, and displays show the assigned node with its full HSIC breadcrumb.
- Automatically create a Company Industry Assignment only from an authoritative valid HSIC code or a Source Industry Label that matches a Taxonomy Operator-approved deterministic mapping (`docs/adr/0013-require-reviewed-company-industry-mappings.md`).
- Unmapped source labels, manual free text, and AI inference create Company Industry Review Items. AI recommendations are advisory and cannot create assignments/nodes or mark an Industry Primary.
- Preserve the core Published Job Corpus and Company corpus, but destructively rebuild the affected Job Intelligence Projections (`docs/adr/0014-rebuild-job-intelligence-projections.md`).
- Preserve identities, source identities, raw payloads/metadata, descriptions, URLs, dates, salaries, unrelated enrichment, and an immutable audit snapshot of replaced legacy values.
- Rebuild Canonical Job Taxonomy state, Employment Types, Source Classification Paths, Company Industry state, Skill state, and embeddings. Quiesce writers and take a consistent backup first; unsupported values become Unknown/review items instead of compatibility guesses.
- Execute the program through seven independently verifiable child tasks: shared foundation; source job attributes; Canonical Job Taxonomy governance; Company Industry governance; Skill governance; product surfaces; and cutover/rebuild. Dependencies are explicit in each child artifact rather than inferred from tree position.
- First-version governance writes use one environment-configured Bearer credential bound to a stable `operator_id`; the backend enforces it and every decision/audit event records that actor.
- Background workers never receive the Operator credential. Full user accounts, login, and multi-role RBAC are deferred; the credential check remains a replaceable authentication adapter.
- Remain in planning. No frontend, backend, schema, seed-data, or migration implementation is authorized until artifacts are complete and reviewed.

## Requirements

- Use the resolved Canonical Job Taxonomy language consistently and define one precise term for every remaining concept; update `CONTEXT.md` as terms are resolved.
- Preserve the existing boundary between source-owned classification identities and project-owned canonical taxonomy concepts.
- Define the authority, cardinality, provenance, lifecycle, display, filtering, and persistence contract for every reviewed concept.
- Replace the free-text Employment Type string with a zero-to-many governed-value contract, preserve ordered raw Source Employment Labels/codes, keep Work Arrangement independent, and define normalization, unknown handling, compatibility, and multi-select filtering.
- Introduce an immutable, HSIC V2.0-seeded Company Industry Taxonomy with zero-to-many assignments, most-specific-evidence placement, subtree filtering, explicit Primary semantics, reviewed deterministic mappings, Company Industry Review Items, advisory-only AI, optional revisioned ISIC crosswalks, and data-repair planning.
- Replace the lossy single source-classification snapshot contract with a zero-to-many Source Classification Path contract, preserving source identity, hierarchy, source-provided order, and explicit-primary provenance without inventing a primary path.
- Replace silent fallback/auto-create behavior with explicit Canonical Taxonomy Assignment provenance and Unassigned/Job Taxonomy Review Item states; define accepted mapping/AI methods, evidence, model version, operator resolution, and affected-job behavior.
- Implement the resolved Skill / Skill Mention / Skill Candidate language and define governance states, Taxonomy Operator actions, transitions, authorization, audit trail, AI recommendation boundaries, and deterministic effects on every affected mention.
- Define the three-area `Job Intelligence Governance` information architecture, queues, filters, evidence, recommendations, decision confirmations, optimistic/concurrent-update behavior, audit history, deep links, empty/error states, and accessibility.
- Make frontend labels, filters, option identities, detail displays, empty/error states, and governance affordances follow the resolved language and contracts.
- Define API response/request contracts that preserve source-qualified identities and do not rely on cross-source display-name equality.
- Define database constraints, indexes, delete behavior, migration/repair policy, and rollback boundaries needed to enforce the resolved model.
- Define the quiesced cutover runbook, immutable legacy snapshot, backup/restore validation, ordered projection rebuild, unresolved-queue reconciliation, acceptance thresholds, and writer reopening/rollback gates.
- Add a server-enforced Operator authentication seam for governance writes, secure credential configuration/comparison, stable actor identity, redaction, negative authorization tests, and an adapter shape that can later be replaced by real RBAC without changing domain decision interfaces.
- Resolve static taxonomy/curation source-of-truth conflicts and define validation that prevents invalid references from shipping.
- Align embedding, search, analytics, and recommendation representations with the resolved taxonomy and skill contracts, or explicitly document deliberate differences.
- Add cross-layer tests that serialize real backend response models and exercise the corresponding frontend behavior.

## Child task map

1. `job-intelligence-foundation` — shared revision/provenance/audit primitives, Taxonomy Operator authorization boundary, governed seed validation, compatibility scaffolding, and common API contracts.
2. `source-job-attributes` — zero-to-many Source Classification Paths and governed multi-value Employment Types, including source adapters, filtering, and migration evidence. Depends on child 1.
3. `canonical-job-taxonomy-governance` — governed Canonical Job Taxonomy seed, accepted assignment provenance, Unassigned state, Job Taxonomy Review Items, backend decisions, and tests. Depends on child 1.
4. `company-industry-governance` — immutable HSIC V2.0 revisions, Company Industry Assignments, reviewed mappings, review items, optional crosswalk model, and tests. Depends on child 1.
5. `skill-governance` — governed Skill taxonomy, Skill Mentions/Candidates, human-only resolution workflow, affected-mention transitions, and tests. Depends on child 1.
6. `job-intelligence-product-surfaces` — the three-area Job Intelligence Governance UI plus consistent Job Browser, Job Detail, Company, dashboard, filter, empty/error, deep-link, and accessibility behavior. Depends on children 2–5's reviewed API contracts.
7. `job-intelligence-cutover-rebuild` — quiesced backup/audit snapshot, destructive projection rebuild, data reconciliation, embedding reindex, rollback, and writer reopening. Depends on children 2–5's schemas and rebuild logic; it does not infer a dependency on child 6, but the parent integration gate requires both 6 and 7.

The parent owns cross-child terminology, the source requirement set, final integration acceptance, and release coordination. Cross-layer tests belong to the child that owns each contract rather than a separate late testing task. Every dependency above must be copied into the corresponding child `prd.md` and `implement.md`; tree position alone is not a dependency.

## Acceptance Criteria

- [ ] `CONTEXT.md` defines every accepted domain term without implementation details, names the canonical hierarchy and its three levels, and explicitly distinguishes Source Classification from Canonical Job Taxonomy.
- [ ] Every reviewed UI surface uses the accepted terminology and identifies provisional or source-owned data where ambiguity is possible.
- [ ] Employment Type and Company Industry each have one documented authority, persistence contract, filter contract, and null/unknown behavior; no UI or API presents the current employment field as Job Type or presents Source Classification as Company Industry.
- [ ] Employment Type accepts only the seven approved values, preserves ordered raw Source Employment Labels/codes, supports legitimate combinations, never coerces unknown labels to `Other`, and does not absorb Work Arrangement or working-day data.
- [ ] Company Industry filters and analytics use stable governed IDs from the Company Industry Taxonomy; free-text evidence is retained with provenance but cannot become a filter value or silently create an Industry node.
- [ ] A Company supports zero or more Company Industry Assignments; Primary is set only by an authoritative source declaration or Taxonomy Operator, compact/detail displays are defined, and filtering matches any governed assignment.
- [ ] Company Industry Taxonomy Revisions preserve the complete five-level HSIC V2.0 hierarchy, bilingual labels, official codes, release/source provenance, and append-only history; any ISIC mapping is explicitly revisioned and provenance-bearing.
- [ ] Company Industry Assignments target the most specific evidence-supported HSIC node without duplicate ancestor assignments; ancestor filters include descendants and UI/API expose the full breadcrumb.
- [ ] Only a valid authoritative HSIC code or Taxonomy Operator-approved deterministic mapping can create a Company Industry Assignment automatically; all other evidence enters a Company Industry Review Item with advisory-only AI recommendations.
- [ ] Company Industry can no longer be silently populated from a role's Source Classification; existing polluted data has an approved detection and repair plan.
- [ ] Source Classification Path cardinality, source-qualified identity, hierarchy, ordering, and explicit-primary rules are testable for JobsDB, CTgoodjobs, and OfferToday; multiple returned paths are not truncated.
- [ ] Canonical Taxonomy Assignments point only to existing governed Job Subcategories and expose mapping/AI/operator provenance; invalid, fallback/default, unknown, and `create_new` outcomes remain Unassigned and appear as Job Taxonomy Review Items.
- [ ] No AI or background process can create Canonical Job Taxonomy nodes.
- [ ] Skill, Skill Mention, Skill Candidate, and Unreviewed Skill Mention have explicit non-overlapping contracts; `Provisional Skill(s)` is absent from UI/API language, and only governed Skills participate in ordinary search, recommendations, and analytics.
- [ ] Skill Candidates have explicit states, transitions, Taxonomy Operator permissions, audit history, and deterministic effects on every affected Skill Mention; no AI or background process can execute a Candidate decision.
- [ ] `Job Intelligence Governance` provides peer Job Taxonomy Review, Skill Candidates, and Company Industries areas; `Source Catalogs`, `AI Enrichment`, Job Detail, and Companies views cannot execute these governance decisions.
- [ ] Every governance write rejects missing/invalid Operator credentials, records the configured `operator_id`, never logs the credential, and cannot be invoked by background workers; read and decision interfaces do not depend on a future RBAC implementation.
- [ ] Static taxonomy and curation files pass deterministic reference-integrity validation.
- [ ] Database design specifies constraints, indexes, foreign-key/delete semantics, compatibility, migration, rollback, and data-repair behavior.
- [ ] Cutover preserves the approved core corpus/evidence, archives replaced legacy state, rebuilds only the approved Job Intelligence Projections in dependency order, validates recovery and counts, and supports rollback before writers reopen.
- [ ] Search, embeddings, analytics, and recommendations either consume the same accepted representations or document and test intentional differences.
- [ ] Backend response-model tests and frontend integration/contract tests cover taxonomy, industry, employment type, governed Skills, and provisional candidates.
- [ ] Complex-task artifacts `design.md` and `implement.md` are complete, converged, and reviewed before any child or implementation task is started.

## Out of scope

- Source Catalog discovery/publication, Crawl Scope authoring, crawler query semantics, and Task Control Board implementation; those remain in `07-18-task-control-board-ui` and its children.
- Automatic name-based cross-source classification mapping as a crawl authority.
- Full user accounts, login/session management, and multi-role RBAC; the first version uses the approved single-Operator adapter.
- Code or data migration before the planning review gate.

## Notes

- This is a complex, multi-deliverable planning task. It requires `design.md` and `implement.md` before any implementation start.
- The requirements interview has converged; technical design, child artifacts, and execution planning remain before review.
