# Current job-intelligence data migration inventory

Research date: 2026-07-18  
Method: read-only SQL against the running local PostgreSQL service plus model/source inspection  
Important: ingest and enrichment workers were active during the audit, so counts are a point-in-time snapshot and changed slightly between queries. A real cutover must quiesce writers and take one consistent snapshot.

## Core corpus and recoverable evidence

| Dataset | Snapshot | Migration implication |
|---|---:|---|
| Jobs | 17,596 live records | Preserve identities and business corpus |
| Jobs with non-empty `raw_data` | 17,596 | Source evidence is available for rebuild |
| Companies | 4,657 records | Preserve identities and company corpus |
| Companies with non-empty metadata | 4,656 | Company/source evidence is almost universally available |
| OfferToday Jobs | 12,351 | All checked raw payloads contain `jobFunctions`; multi-path recovery is possible |
| JobsDB Jobs | 3,798 | Raw source payload exists; source classification/subclassification evidence exists |
| CTgoodjobs Jobs | 1,447 | Classification evidence exists; current data has no subclassification |

Core Job and Company identities, source identities, raw payloads/metadata, descriptions, URLs, dates, salaries, and unrelated enrichment are not disposable taxonomy projections.

## Company Industry quality

| Metric | Snapshot |
|---|---:|
| Companies with nonblank legacy `industry` | 4,052 |
| Distinct raw industry strings | 69 |
| Companies whose industry equals a joined Job's Source Classification | 1,687 |
| Companies without a usable industry value | 605 |

The legacy `Company.industry` string is not safe to translate directly into governed HSIC assignments. JobsDB and CTgoodjobs ingestion intentionally populated it from job classifications; the generic worker could also override true OfferToday company-industry evidence. Preserve the old value and metadata in an audit snapshot, then derive governed Company Industry Assignments only from valid company-owned evidence or reviewed mappings.

## Canonical Job Taxonomy state

| Metric | Snapshot |
|---|---:|
| Jobs with no `subcategory_id` | approximately 13,758 |
| Jobs with a `subcategory_id` | approximately 3,838–3,843 |
| Database Job Domains | 8 |
| Database Job Categories | 13 |
| Database Job Subcategories | 23 |
| Governed/seed taxonomy nodes in those tables | 0 |

Every current database taxonomy node is `created_by=ai` and `is_auto_created=true`. The database does not contain the structurally clean static taxonomy snapshot (25 domains, 88 categories, 223 subcategories) as governed seed state. Existing assignments should therefore be archived for audit but not migrated as accepted Canonical Taxonomy Assignments.

## Employment Type state

The legacy column is a nullable free-text string and frequently contains source-local labels or comma-joined combinations. Examples observed in the database include:

- JobsDB: `Full time`, `Contract/Temp`, `Part time`, `Full time, Part time`, `Casual/Vacation`.
- CTgoodjobs: `Full-time`, `Other`, `Full-time, Other`, `N, A`, `Contract`, `Full-time, Contract`, `Temporary, Contract`.
- OfferToday: `全職`, `兼職`.

The old string is valuable Source Employment Label evidence but is not a safe canonical value. Preserve it in the migration snapshot/raw evidence and rebuild governed multi-value Employment Types through explicit normalization rules.

## Skill and embedding state

| Dataset | Snapshot |
|---|---:|
| Skill Categories | 0 |
| Skill Technologies | 0 |
| Canonical Skills | 0 |
| `job_skills` links | 0 |
| `review_candidate` Skill Mentions | approximately 22,459 |
| `generic_tag` Skill Mentions | approximately 237 |
| Pending Skill Candidates | approximately 5,456 |
| Job Embeddings | 2,931 (about 16.7% Job coverage) |

The database has no governed Skill taxonomy or governed Job-Skill links. Existing mentions/candidates are derived extraction state, and embeddings are both incomplete and based on the old document contract. Archive aggregate/audit evidence if needed, then rebuild these projections after the governed taxonomy and assignment contracts exist.

## Recommended cutover boundary

### Preserve

- Job and Company IDs and source-qualified identities.
- Job descriptions, company facts, original URLs, dates, salaries, and unrelated business fields.
- `Job.raw_data`, Company metadata, raw source labels/codes, and legacy values in an immutable migration snapshot.
- AI summaries and experience enrichment unless a later requirement explicitly changes their contracts.

### Reset and rebuild

- Canonical Job Taxonomy database seed state, `jobs.subcategory_id`, assignment provenance, and review items.
- Governed Employment Type projections and filters, while retaining legacy/raw labels as evidence.
- Source Classification Path projections, reconstructed from raw payloads and checked against the legacy single-value columns.
- Company Industry Assignments, reviewed mappings, and review items; the legacy free-text field becomes audit evidence only.
- Skill taxonomy seed state, Skill Mentions/Candidates, governed Job-Skill links, and taxonomy metrics.
- Embeddings after accepted Canonical Taxonomy Assignments and governed Skills have been rebuilt.

### Operational requirements

1. Quiesce ingest, enrichment, embedding, and any API writes that touch these datasets.
2. Take a consistent database backup plus an immutable export of every legacy field being replaced.
3. Install new schema and governed seed revisions.
4. Reconstruct raw evidence and create Unknown/review states rather than guessing.
5. Rebuild derived assignments, mentions, governed links, and embeddings in dependency order.
6. Validate counts, provenance coverage, unresolved queues, and search/filter behavior before reopening writers.
7. Retain an explicit rollback point until cross-layer validation passes.

## Read-only verification queries

The audit used aggregate `SELECT` statements inside `BEGIN TRANSACTION READ ONLY`, including counts over `jobs`, `companies`, `job_domains`, `job_categories`, `job_subcategories`, `job_skill_mentions`, `skill_review_candidates`, `job_skills`, and `job_embeddings`. No database mutations were performed.
