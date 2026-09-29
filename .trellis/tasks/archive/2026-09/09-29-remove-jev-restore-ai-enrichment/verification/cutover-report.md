# Authoritative database cutover verification

Cutover date: 2026-09-30 (Asia/Hong_Kong)

## Target and safety gate

- Database identity: PostgreSQL database `jobsdb`, user `admin`, Compose service
  `postgres-db`.
- The frontend, backend API, scheduler, ingest, enrichment, embedding,
  retrieval, recommendation, and Scrapyd services were stopped before the
  final preflight. Only PostgreSQL and Redis remained running.
- A normal full custom-format PostgreSQL backup was created at
  `.backups/jobsdb-before-remove-jev-20260930.dump` (not tracked by Git).
- Backup size: 390 MB.
- Backup SHA-256:
  `3b8cb74b7f21da4a4a75182b4fa7691e917d0f00491532150861f28bee9f6d84`.
- `pg_restore --list` successfully read the archive (489 TOC entries,
  PostgreSQL 15.18).
- No provider request was made and no historical Job was queued for
  enrichment.

## Final preflight

- State: `ready`.
- Active retired work: 0.
- Completed Classification items requiring record-level reversal: 0.
- Skill maintenance batches requiring record-level reversal: 0.
- Jobs with proven retired-provider Skill data: 8,416.
- Proven automatic Skill mentions removed: 63,511.
- Proven automatic Skill assignments removed: 4,567.
- Proven operator mentions protected: 15.
- Proven operator assignments protected: 8.
- Ordinary AI mentions protected: 109,039.
- Ordinary AI assignments protected: 27,790.
- Ambiguous automatic assignments protected: 12,953.

Retired table row counts before removal:

| Table | Rows |
| --- | ---: |
| `classification_batch_run_items` | 0 |
| `classification_batch_runs` | 0 |
| `jev_crawl_quality_evaluations` | 0 |
| `jev_crawl_quality_observations` | 0 |
| `jev_duplicate_associations` | 64,860 |
| `jev_incident_triage_clusters` | 0 |
| `jev_incident_triage_evaluations` | 0 |
| `jev_online_skill_classifications` | 14,403 |
| `jev_operation_batch_items` | 69,018 |
| `jev_operation_batches` | 5 |
| `jev_related_jobs_evaluations` | 25,690 |
| `jev_run_attempts` | 104,953 |
| `jev_run_items` | 104,953 |
| `jev_runs` | 61,752 |
| `jev_runtime_settings` | 1 |
| `jev_search_rerank_evaluations` | 0 |
| `jev_skill_maintenance_batches` | 0 |

## Apply and postcheck

- Explicit confirmation token and verified-backup acknowledgement were
  supplied to the temporary tool.
- Apply state: `removed`.
- The transaction deleted only records whose source was directly proven as
  retired-provider automation, recomputed unresolved-evidence counts, removed
  the 17 retired tables and three retired review-setting columns, and created
  the two Related Jobs snapshot tables.
- The transaction verified that total Jobs, Jobs with `ai_enriched_at`, and
  ordinary enrichment-run counts were unchanged.
- A second confirmed apply returned `already_removed` and made no changes.

Independent post-cutover SQL verification:

- Retired tables remaining: 0.
- Related Jobs snapshot tables present: 2.
- Retired review-setting columns remaining: 0.
- Retired-provider Skill mentions / assignments remaining: 0 / 0.
- Operator mentions / assignments remaining: 15 / 8.
- Ordinary AI mentions / assignments remaining: 109,039 / 27,790.
- Ambiguous automatic assignments remaining: 12,953.
- Jobs: 22,045.
- Jobs with `ai_enriched_at`: 21,705.
- Ordinary enrichment runs: 0.

The temporary cutover executable and its dedicated tests were deleted after
this verification, before the final work commit. Recovery after this point
requires restoring the full backup together with the pre-cutover application
version; old application code is not compatible with the cut-over schema.
