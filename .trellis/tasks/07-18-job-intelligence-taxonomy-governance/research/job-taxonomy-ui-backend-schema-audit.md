# Cross-layer audit: job taxonomy, source classifications, industry, job type, and skills

Date: 2026-07-18  
Status: preliminary evidence audit; domain and task-boundary decisions are still open  
Scope: frontend display and filtering, backend contracts and enrichment logic, relational schema, static taxonomy data, and tests

## Executive conclusion

The seven labels under review do not describe one taxonomy. The current product exposes at least five distinct models, but the UI and some ingest code blur their boundaries:

| Current label | Actual concept | Current authority | Persistence | Main problem |
|---|---|---|---|---|
| Job Taxonomy | Canonical three-level job classification: Domain → Category → Subcategory | Project-owned taxonomy plus enrichment decision | `jobs.subcategory_id` and the canonical taxonomy tables | Also called `Classification` and `AI Category`; the authority and fallback state are not visible |
| Job Type | Employment arrangement/type copied from a source | Source payload | `jobs.employment_type` free text | No normalized Job Type model; the UI name implies stronger semantics than the data has |
| Industry | Company industry | Company record | `companies.industry` free text | Ingest can populate it from a job's source classification, contaminating a company concept with a role concept |
| Classifications / Subclassifications | Source-native job taxonomy nodes | Each external Source | Denormalized source ID/name snapshots on jobs; source catalog definitions elsewhere | Labels omit the `Source` qualifier in some screens, and API/runtime depth is inconsistent |
| Skills | Governed canonical technical skills | Project-owned skill taxonomy and governance rules | Skill Category → Technology → Skill, plus `job_skills` and resolved mentions | Multiple data structures encode the same association; governed visibility is implicit |
| Provisional Skills | Unresolved technical mentions awaiting governance | Skill-normalization and offline curation workflow | `job_skill_mentions` with `resolution=review_candidate`, linked to `skill_review_candidates` | They are not actually Skills yet; UI is display-only and offers no governance/provenance context |

The system already contains the right broad separation between source-native classifications and the canonical job taxonomy. The largest confirmed semantic defect is the Industry field. The largest product-model gap is that canonical, source-native, and provisional concepts are represented together without a consistent language or governance surface.

## Current cross-layer flow

```text
Source listing/detail
  ├─ source classification/subclassification snapshots ──────┐
  ├─ source employment label ──> jobs.employment_type         │
  └─ company payload ──────────> companies.industry           │
                              (sometimes filled from source classification)
                                                               │
AI enrichment                                                  │
  ├─ source-bound taxonomy slice + LLM decision                │
  │    └─ Canonical Domain / Category / Subcategory            │
  │         └─ jobs.subcategory_id                             │
  └─ extracted skill terms                                    │
       ├─ match_existing ──> governed Skill + JobSkill         │
       ├─ review_candidate ─> provisional mention/candidate    │
       ├─ generic_tag                                          │
       └─ reject                                               │
                                                               │
UI                                                             │
  ├─ Job Browser: employment type + canonical taxonomy + industry
  ├─ Job Detail: source taxonomy + company industry + canonical taxonomy
  │               + governed skills + provisional terms
  ├─ AI Runs: source classification/subclassification filters
  └─ Dashboard: canonical categories and governed skills only
```

## What is already sound

- The `Job` model separates source-native classification snapshots from its canonical `subcategory_id`; its `job_taxonomy` property returns the full canonical Domain/Category/Subcategory path (`backend/app/models/job.py:68-75`, `backend/app/models/job.py:185-201`).
- The domain glossary and ADR-0001 correctly state that Source Taxonomy is authoritative for Crawl Scope and Canonical Job Domains are descriptive after collection, not executable crawl categories (`CONTEXT.md:5-35`, `docs/adr/0001-source-native-taxonomies-define-crawl-scope.md:1-3`).
- Job Detail is the clearest current UI: it separately renders Source classification, Source sub-classification, Company industry, governed Skills, Provisional Skills, and Job Taxonomy (`frontend/src/components/JobDetailModal.jsx:301-377`).
- Governed skills and unresolved mentions are intentionally separated. `Job.skills_list` exposes only governed visible `match_existing` mentions; `provisional_skills_list` exposes only `review_candidate` mentions (`backend/app/models/job.py:110-170`).
- Provisional-skill governance does exist as an offline dry-run/apply workflow. Merge and generic actions rewrite mentions and mark the candidate resolved (`backend/scripts/govern_skill_review_candidates.py:31-89`, `backend/scripts/govern_skill_review_candidates.py:92-138`, `backend/scripts/govern_skill_review_candidates.py:192-236`).
- The static canonical job taxonomy is structurally clean in the checked snapshot: 25 domains, 88 categories, and 223 subcategories, with no duplicate canonical paths found.

## Findings

### A-01 — Company Industry is contaminated by role classification

Classification: confirmed semantic defect; high impact.

- In the ingest worker, a fallback/new company payload sets `industry` to the job's `source_classification_name` (`backend/app/workers/run_ingest_worker.py:311-317`).
- The CTgoodjobs mapper repeats that fallback when company industry is absent (`backend/app/utils/data_mapper.py:279-288`).
- The Job Browser's `Industry` filter is an exact filter over `Company.industry`, and its options come from distinct values in that same column (`backend/app/api/jobs.py:337-344`, `backend/app/api/jobs.py:909-923`).

Result: a source-native role bucket such as `Information Technology` can become a property of the company and then appear as an Industry filter. This makes Industry neither a trustworthy company taxonomy nor a trustworthy job taxonomy.

### A-02 — One canonical concept has three UI names, while one source concept loses its qualifier

Classification: confirmed UX/domain-language defect; high impact.

- Job Browser calls the canonical path `Job Taxonomy` (`frontend/src/components/FilterPanel.jsx:142-154`).
- Add Job calls the same `job_taxonomy.path` `Classification` (`frontend/src/components/jobs/AddJobPage.jsx:328-332`).
- Dashboard calls canonical results `Jobs by AI Category` (`frontend/src/components/charts/CategoryChart.jsx:96-127`).
- AI Enrichment calls source-native fields simply `Classifications` and `Subclassifications`, even though its state fields are `source_classification_names` and `source_subclassification_names` (`frontend/src/components/ai/AIEnrichmentPage.jsx:893-911`).

Result: `Classification` can mean either a source-owned node or a canonical project-owned path depending on screen. The existing glossary explicitly says these must not be conflated.

### A-03 — Job Type is only an ungoverned employment label

Classification: confirmed model limitation; product decision required.

- The frontend's `Job Type` control reads and writes `employment_type` (`frontend/src/components/FilterPanel.jsx:127-139`).
- The backend performs exact equality over `Job.employment_type` (`backend/app/api/jobs.py:337-343`).
- `Job` has `employment_type` as a nullable string and has no separate `job_type` field or relationship (`backend/app/models/job.py:87-95`).

This may be acceptable if the intended concept is strictly Employment Type (`Full time`, `Contract`, and similar). It is misleading if `Job Type` is intended to mean profession, function, seniority, work mode, or a canonical type shared across Sources.

### A-04 — Provisional Skills have a CLI governance loop but no product governance loop

Classification: confirmed operability and UX gap; medium-to-high impact.

- Job Detail shows raw provisional terms as Skill tags without status, frequency, recommendation, provenance, or an action (`frontend/src/components/JobDetailModal.jsx:339-359`).
- A provisional item is a mention whose free-string `resolution` is `review_candidate`, optionally linked to a global candidate (`backend/app/models/job_skill_mention.py:21-39`).
- Candidate status is also a free string and the schema has no check constraint (`backend/app/models/skill_review_candidate.py:15-23`).
- Governance recommendations and rewrite logic exist in scripts/services, but the API has no candidate review/approve/reject route; API usage is limited to filtering AI-run inputs by candidate names (`backend/app/api/ai.py:129`, `backend/app/api/ai.py:584`).

This is not a missing backend mechanism. It is a missing operator-facing mechanism and language boundary: a provisional term is presented beside governed Skills even though it is a review item, not yet a member of the Skill Taxonomy.

### A-05 — Source classification APIs have incompatible identities and depth

Classification: confirmed contract defect; high impact for source-taxonomy UI.

- The list endpoint is source-aware and delegates to `SourceCategoryRegistry` (`backend/app/api/category_routes.py:21-51`).
- The detail endpoint accepts only an integer, looks only in `JOBSDB_CATEGORIES`, and cannot represent CTgoodjobs or OfferToday qualified IDs (`backend/app/api/category_routes.py:54-61`).
- The shared list contract flattens source-specific hierarchy and metadata; the current control-board PRD separately records that OfferToday has two levels while the shared endpoint returns roots only (`.trellis/tasks/07-18-task-control-board-ui/prd.md:12-24`).

The API therefore advertises a multi-source collection but retains a JobsDB-only item contract.

### A-06 — OfferToday classification persistence is lossy

Classification: confirmed data-loss behavior; high impact if multiple functions are meaningful.

The canonical source contract reads only `job_functions[0]` and only its first child, silently dropping any additional functions or subclasses (`backend/app/sources/contracts.py:203-226`). The current Job schema can persist only one classification and one subclassification snapshot (`backend/app/models/job.py:72-75`).

This is either a defect or an undocumented cardinality decision. The repository does not currently establish that OfferToday functions are always singular or that only the first is authoritative.

### A-07 — Invalid canonical classifier output silently becomes a fallback path

Classification: confirmed observability risk; medium impact.

When a classifier selects a domain/category/subcategory outside the source-bound allowed slice, the normalizer returns the slice's default path rather than preserving an explicit failure state. It also accepts a new subcategory when `resolution == create_new` (`backend/app/services/job_category_normalizer.py:452-479`).

The Dashboard distinguishes specific from fallback buckets, which is useful, but an individual job's API/UI path does not explain whether the path was confidently selected or substituted. A normalized path therefore looks equally authoritative in Job Detail regardless of resolution provenance.

### A-08 — Search embeddings emphasize source taxonomy but omit canonical taxonomy

Classification: confirmed representation mismatch; product/search decision required.

The embedding document includes source classification/subclassification names and governed skills, but not the canonical Domain/Category/Subcategory path or provisional/generic terms (`backend/app/services/embedding_document_builder.py:22-73`). Recommendation logic separately uses canonical taxonomy and canonical skill overlap.

This can make semantic retrieval and structured/recommendation ranking reason over different representations of the same job. It may be intentional, but the contract is undocumented and untested.

### A-09 — Schema integrity allows taxonomy/governance drift

Classification: confirmed schema risks; severity varies by operation.

- `jobs.subcategory_id` has a foreign key but no delete action, while Category → Subcategory uses cascade. Deleting a category can cascade toward subcategories and then be blocked by assigned jobs (`backend/app/models/job.py:68-75`, `backend/app/models/job_category.py:15-30`, `backend/app/models/job_subcategory.py:15-30`).
- Mention `resolution` and candidate `status` are unconstrained strings; mentions are not unique per job/normalized term (`backend/app/models/job_skill_mention.py:14-39`, `backend/app/models/skill_review_candidate.py:15-23`).
- Deleting a Skill sets `job_skill_mentions.skill_id` to null, allowing a historical `match_existing` mention with no matched Skill; the computed governed list then silently skips it (`backend/app/models/job_skill_mention.py:23-29`, `backend/app/models/job.py:124-132`).
- Candidate `first_seen_job_id` and `last_seen_job_id` have no `ondelete`, which can block deletion of referenced jobs (`backend/app/models/skill_review_candidate.py:21-23`).
- `crawl_job_listings` stores only classification, not subclassification, and its crawl/published job UUIDs are not database foreign keys (`backend/app/models/crawl_job_listing.py:44-68`).
- `jobs.job_id` remains globally unique even though a source-qualified uniqueness constraint also exists, which can reject identical upstream IDs from different Sources (`backend/app/models/job.py:41-47`).

### A-10 — Skill static-data rules disagree with the seed taxonomy

Classification: confirmed static-data inconsistency; runtime impact needs a database-state check.

The checked static skill taxonomy contains 8 categories, 33 technologies, and 88 skills. Its curation files contain references that do not resolve against that seed snapshot:

- Canonical aliases target `Wi-Fi`, `Vue 3`, and `PCI DSS`, but those canonical names are absent from `skill_taxonomy.json` (`backend/app/data/skill_curation_rules.json:3-6`, `backend/app/data/skill_curation_rules.json:36-39`).
- The Oracle merge target references `Database / SQL / Oracle`, which is absent from the seed taxonomy (`backend/app/data/skill_backfill_curations.json:275-281`).
- Jira and Confluence curations reference a `Platforms` category, while the seed places both under `Product & Delivery / Collaboration Tools` (`backend/app/data/skill_backfill_curations.json:439-454`, `backend/app/data/skill_taxonomy.json:171-197`).

The governance script can create target nodes, so this is not necessarily an immediate exception. It does mean the curation files and declared seed taxonomy are competing sources of truth.

### A-11 — Frontend filter cardinality and backend shapes disagree

Classification: confirmed UI limitation; medium impact.

The query contract represents `subcategory_ids` as an array, but the Job Browser renders a single `<select>`, reads only `subcategory_ids[0]`, and overwrites the array with zero or one value (`frontend/src/components/FilterPanel.jsx:142-154`). Either the API should be explicitly single-select or the UI should support the existing multi-value contract.

The AI Enrichment source filters correctly support multiple values but key options and requests by display names rather than source-qualified classification IDs (`frontend/src/components/ai/AIEnrichmentPage.jsx:390-402`, `frontend/src/components/ai/AIEnrichmentPage.jsx:893-911`). Same-name nodes across Sources can therefore collapse into one option.

### A-12 — Cross-layer tests do not protect the most important contracts

Classification: confirmed coverage gap; high regression risk.

- No backend tests exercise `Job.skills_list`, `provisional_skills_list`, `job_taxonomy`, or `JobDetailSchema` serialization.
- Job Detail frontend tests use hand-built payloads and can pass with only `{path}` even though `JobTaxonomySchema` requires all IDs and names (`frontend/src/components/JobDetailModal.test.jsx:27-29`, `backend/app/schemas/job.py:43-52`).
- `JobCreateSchema`/`JobSchema` omit `source_site` and `source_job_id` even though the model stores them; no response-contract test catches the omission (`backend/app/schemas/job.py:7-23`, `backend/app/models/job.py:41-67`).
- Industry and employment-type tests are fixture-level only; no backend tests define normalization, null, duplicate, or source-compatibility semantics.
- Existing unsupported-source-taxonomy tests concentrate on AI run selection, not the Job API/UI contract (`backend/tests/test_ai_enrichment_runs.py:141-193`, `backend/tests/test_ai_enrichment_runs.py:233-275`).

## UI surface inventory

| Surface | Canonical taxonomy | Source taxonomy | Job type | Industry | Skills | Provisional |
|---|---:|---:|---:|---:|---:|---:|
| Job Browser cards/filters | path + subcategory filter | source filter only | yes | yes | no | no |
| Job Detail | full path | classification + subclassification names | employment type | company industry | governed | displayed |
| Add Job result | path labelled `Classification` | no | captured in form | company form field | governed | not displayed |
| AI Enrichment run builder | used for eligibility/exclusion | name-based multi-filters | no | no | candidate filters in backend | indirect |
| Dashboard Category chart | canonical category/fallback buckets | diagnostics only | no | no | no | no |
| Dashboard Skill chart | no | no | no | no | governed only | no backlog signal |
| Crawl control board | not an execution authority | source catalog/Crawl Scope | no | no | no | no |

## Preliminary boundary recommendation

Keep the active `task-control-board-ui` program responsible for pre-dispatch Source Taxonomy, Source Catalog Revisions, and Crawl Scope. Treat the broader canonical taxonomy / employment type / company industry / skill governance audit as a separate, cross-linked domain program because it operates primarily after collection and affects Job Browser, enrichment, search, recommendations, and company data.

This recommendation does not prevent shared terminology or links. It prevents Canonical Job Taxonomy and Skill governance changes from becoming hidden dependencies of crawler-control correctness.

## Decisions still required

These must be resolved one at a time in the design interview:

1. Whether this becomes a separate planning task or expands the current control-board parent.
2. Whether the canonical Domain/Category/Subcategory tree's product name is `Canonical Job Taxonomy`, `Job Taxonomy`, or another term.
3. Whether `Job Type` means only Employment Type; if not, what independent concept it denotes.
4. Whether Industry is company-owned, job-owned, or both as separate named attributes; existing source-classification fallback must not remain implicit.
5. Whether source classification persistence is one primary path or a many-valued set for Sources such as OfferToday.
6. Whether provisional terms should remain visible on jobs, live only in a governance queue, or both with explicit state.
7. Which actor can approve/reject/merge Skill Candidates and canonical taxonomy fallbacks.
8. Whether existing polluted Industry and taxonomy data may be destructively recomputed or needs a compatibility migration.

## Current scope guardrail

This document records evidence only. It does not authorize schema, backend, frontend, seed-data, or migration changes, and it does not change the implementation scope of any existing child task.
