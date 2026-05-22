# Execution Unit: Operator Scripts

## Current Responsibilities

Operator scripts bootstrap databases, launch host-side headed workers, recover failed runs, reset or backfill data, seed and govern taxonomy/skills, run batch enrichment, test LLM settings, verify migrations, and produce local health reports.

## Current Implementation Map

- Runtime setup: `backend/scripts/bootstrap_db.py`, `init_db.py`, `prepare_headed_crawl_worker_host.py`
- Host worker launch: `run_headed_crawl_worker_host.cmd`, `run_headed_crawl_worker_host.ps1`, `launch_headed_crawl_worker_window.cmd`, `run_headed_crawl_worker.py`
- Recovery/backfill: `recover_failed_crawl_auto_runs.py`, `backfill_jobsdb_details.py`
- AI operations: `batch_enrich_jobs.py`, `reset_ai_derived_data.py`, `backup_legacy_ai_data.py`, `test_llm.py`
- Data cleanup: `clear_mock_data.py`
- Taxonomy and migration: `seed_taxonomy.py`, `migrate_job_categories.py`, `converge_taxonomy_schema.py`, `verify_migration.py`, `migrate_skills_to_hierarchy.py`, `migrate_skills_to_relational.py`, `remove_skills_array_column.sql`
- Governance: `govern_skill_history.py`, `govern_skill_review_candidates.py`, `govern_job_taxonomy.py`
- Research/reporting: `research_ctgoodjobs_probe.py`, `operator_health_report.py`

## Data and Control Flow

Scripts run out-of-band from the web UI and share the same database, Redis streams, runtime settings, source parsers, and provider settings used by services. Some scripts are read-only reports; others mutate runtime data, taxonomy rows, enrichment state, or migration state.

Dry-run behavior exists for some governance, seed, migration, and batch enrichment paths, but it is not uniform across all mutating scripts. Script output and exit behavior are script-specific, so automation has to know each command's conventions.

## Tests and Coverage

- `backend/tests/test_operator_health_report.py`
- `backend/tests/test_recover_failed_crawl_auto_runs.py`
- `backend/tests/test_host_headed_runtime_bootstrap.py`
- `backend/tests/test_bootstrap_db.py`
- `backend/tests/test_batch_enrich_jobs.py`
- `backend/tests/test_job_taxonomy_governance.py`
- `backend/tests/test_seed_taxonomy.py`
- `backend/tests/test_skill_history_governance.py`

## Known Gaps or Risks

- Important recovery, governance, taxonomy, cleanup, and batch enrichment flows are still script-first rather than API-backed operator actions.
- Mutating scripts do not all follow a dry-run-first contract with explicit execute confirmation.
- Output format, exit codes, and error reporting are not standardized across scripts.
- Host runtime scripts are Windows-specific in places.
- Script effects may not be visible in the frontend unless they update shared runtime tables or events.
- There is no central script registry that documents ownership, mutability, required environment, and rollback expectations.

## Optimization Backlog

- Add a script registry with owner, purpose, mutability, dry-run support, required environment, and expected audit output for each script.
- Standardize mutating scripts around `--dry-run` default behavior, explicit `--execute`, optional `--json`, and documented exit codes.
- Write structured audit records for data-changing scripts or route high-value actions through API-backed operator endpoints.
- Promote frequently used recovery, taxonomy, and batch enrichment workflows into authenticated operator APIs.
- Add smoke tests that assert mutating script CLIs expose the standard dry-run/execute/json flags.

## Follow-up Audit Questions

- Which scripts are safe to keep as local-only maintenance tools?
- Which script actions need frontend visibility or approval before execution?
- Should script audit records be stored in a general operator action table?
