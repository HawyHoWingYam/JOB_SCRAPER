# Data Lifecycle: Normalization

## Current Responsibilities

Normalization converts source-specific fields into canonical job, company, category, location, salary, experience, and skill-adjacent data.

## Current Implementation Map

- Source contracts: `backend/app/sources/contracts.py`
- Source parsers: `backend/app/sources/jobsdb/parsers.py`, `backend/app/sources/ctgoodjobs/parsers.py`
- Identity utilities: `backend/app/utils/source_identity.py`
- Category normalizers: `backend/app/services/job_category_normalizer.py`, `source_category_registry.py`
- Skill normalizer: `backend/app/services/skill_normalizer.py`

## Data and Control Flow

Source adapters produce canonical job dictionaries. Ingest then maps these into `jobs`, `companies`, taxonomy fields, raw payload fields, and later AI skill mentions. Source identity prefixes keep cross-source IDs distinct.

## Tests and Coverage

- `backend/tests/test_api_taxonomy_compat.py`
- `backend/tests/test_skill_governance.py`
- `backend/tests/test_ctgoodjobs_html_fetcher.py`
- `backend/tests/test_jobsdb_spider.py`
- `backend/tests/test_ctgoodjobs_spider.py`

## Known Gaps or Risks

- Some normalization happens inside source adapters and some inside repositories/services.
- Source-specific taxonomy mapping is still a living boundary as CTgoodjobs coverage expands.
- Skill normalization has many governance rules and can affect dashboard/reporting semantics.
- Ingest still accepts loosely shaped canonical dictionaries before mapping into jobs, companies, taxonomy fields, and raw data.
- Source identity compatibility/backfill paths are necessary today but increase the number of valid ID forms.

## Optimization Backlog

- Introduce a versioned Pydantic canonical payload that adapters must produce before `run_ingest_worker.py` persists rows.
- Keep source parsers focused on source extraction and move shared normalization into `data_mapper.py` or dedicated mapping services.
- Version taxonomy inputs and skill normalization rules so reports can explain which rules produced a stored classification.
- Retire source identity backfill/compatibility code after migration verification proves all persisted rows use canonical source IDs.

## Follow-up Audit Questions

- Should canonical payloads be validated by Pydantic before ingestion?
- Should source identity migration logic be retired after all data is converged?
- Should taxonomy and skill normalization be separately versioned?
