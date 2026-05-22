# Canonical Job Store

## Current Responsibilities

This scope stores the normalized, user-facing job and company records. It is the serving surface for search, detail pages, recommendations, export, AI enrichment, and embeddings.

## Current Implementation Map

- Models: `backend/app/models/job.py`, `backend/app/models/company.py`
- Repositories: `backend/app/repositories/job_repository.py`, `backend/app/repositories/company_repository.py`
- Mapping: `backend/app/utils/data_mapper.py`, `backend/app/utils/source_identity.py`
- APIs: `backend/app/api/jobs.py`, `backend/app/api/companies.py`
- Backfill: `backend/app/services/source_identity_backfill_service.py`
- Tests: `backend/tests/test_job_repository_upsert.py`, `backend/tests/test_api_taxonomy_compat.py`, `backend/tests/test_jobsdb_detail_repair_service.py`

## Tables and Column Use

| Table | Key columns | Column purpose |
| --- | --- | --- |
| `companies` | `id` | Internal UUID primary key used by `jobs.company_id` |
| `companies` | `company_id` | Compatibility identifier, still unique for existing API/code paths |
| `companies` | `source_site`, `source_company_id` | Source-aware identity; unique together for JobsDB and CTgoodjobs coexistence |
| `companies` | `name`, `industry`, `location` | Search/display metadata |
| `companies` | `ai_description` | Company AI enrichment output |
| `companies` | `metadata` | Source-specific or extra scraped fields |
| `companies` | `is_deleted`, `created_at`, `updated_at` | Soft-delete and freshness fields |
| `jobs` | `id` | Internal UUID primary key used by joins and worker events |
| `jobs` | `job_id` | Compatibility identifier, unique and source-prefixed where needed |
| `jobs` | `source_site`, `source_job_id` | Source-aware identity; unique together |
| `jobs` | `company_id`, `title`, `description` | Core job content and company relation |
| `jobs` | `subcategory_id` | Canonical governed job taxonomy leaf |
| `jobs` | `source_classification_id/name`, `source_subclassification_id/name` | Source classification fields captured before/alongside canonical taxonomy |
| `jobs` | `ai_summary`, `ai_enriched_at` | AI job enrichment output and timestamp |
| `jobs` | `experience_*`, `salary_*`, `location`, `employment_type`, `posted_date` | Structured search/filter fields |
| `jobs` | `raw_data` | Source payload retained for debugging, original URL, and repair/backfill |
| `jobs` | `search_vector` | Legacy/plain search support field |
| `jobs` | `is_deleted`, `created_at`, `updated_at` | Soft-delete and freshness fields |

## Data and Control Flow

1. Ingest worker maps staged `crawl_job_listings` payloads through `data_mapper`.
2. Company upsert resolves source-aware company identity and writes `companies`.
3. Job upsert writes `jobs` with source identity, source classification, raw payload, and normalized structured fields.
4. AI enrichment updates `jobs.ai_summary`, experience fields, taxonomy, and skill relations.
5. Embedding worker reads the current job/company/taxonomy state and writes `job_embeddings`.
6. Search/export/detail APIs query `jobs` joined to `companies`, taxonomy, and skills.

## Constraints and Indexes

- `companies` has `UNIQUE (source_site, source_company_id)` plus unique `company_id`.
- `jobs` has `UNIQUE (source_site, source_job_id)` plus unique `job_id`.
- `jobs.company_id` references `companies.id`; `jobs.subcategory_id` references `job_subcategories.id`.
- Query indexes exist on common filters such as title, source fields, salary, experience, taxonomy, soft-delete, and created timestamp.

## Current Database Snapshot

- `companies`: 2 rows
- `jobs`: 3 rows

This is much smaller than the staging table count, so the current local database appears to have a substantial pre-publication backlog or test data skew.

## Tests and Coverage

- Upsert tests cover source-aware identity and compatibility IDs.
- API taxonomy tests verify search/detail serialization and CTgoodjobs URL handling.
- Ingest worker tests cover canonical row creation from staged crawl data.

## Known Gaps or Risks

- `job_id` and `company_id` compatibility columns still coexist with source-aware identity, which increases invariants to maintain.
- `raw_data` is useful for repair but can create storage, privacy, and schema drift concerns.
- `search_vector` is typed as string, while semantic search now relies on `job_embeddings`; its current ownership should be clarified.
- AI, source, normalized, and compatibility facts currently live on the same wide `jobs` row.
- The small published-job count compared with staged listings should be monitored as a lifecycle health signal, not just a local snapshot observation.

## Optimization Backlog

- Derive compatibility IDs from `(source_site, source_job_id)` and `(source_site, source_company_id)` once legacy API callers are migrated.
- Define `raw_data` retention and redaction rules, including which source keys are required for repair/backfill.
- Split or clearly tag source facts, normalized facts, and AI-derived facts so update ownership and auditability are explicit.
- Clarify or retire `search_vector` if lexical search no longer depends on persisted text vectors.
- Add health/reporting around staged-to-published ratios by source and crawl phase.

## Follow-up Audit Questions

- Should `job_id`/`company_id` compatibility columns eventually become derived-only API fields?
- Which `raw_data` keys are required for support and which can be dropped after ingest?
- Should `jobs` be split into source facts, normalized facts, and AI-derived facts?
- What is the expected ratio of staged listings to published jobs?
