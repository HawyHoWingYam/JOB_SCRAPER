# Live `jobsdb` schema-lineage preflight

Date: 2026-07-20

Status: read-only evidence; **no live migration/stamp approval**

## Purpose

`bootstrap_db.py` intentionally refuses a non-empty database without an
`alembic_version` table. The live `jobsdb` database is in that state, so an
operator must prove the historical schema boundary before any stamp or upgrade.
Stamping a later revision merely because the current application starts would
skip required migrations and is forbidden.

## Read-only observations

All queries ran inside `BEGIN READ ONLY`; no dump, backup, stamp, migration,
service stop, Catalog publication, or data mutation was performed.

| Boundary evidence | Live result | Interpretation |
|---|---|---|
| `alembic_version` | table absent | lineage must be established explicitly |
| `crawl_job_executions` and its ownership columns | present | `20260716_120000` effects are present |
| `scraper_pacing_settings` | present with JobsDB, CTgoodjobs, and OfferToday defaults | `20260716_180000` effects are present |
| `enrichment_runs.cancelled_items` and `stop_requested_at` | present | `20260718_120000` columns are present |
| `ux_enrichment_runs_one_active` | present with the expected active-status predicate | `20260718_120000` index is present |
| `enrichment_runs.excluded_items` | absent | `20260718_150000` has not run |
| Source Catalog tables | absent | `20260718_180000` has not run |
| Job Intelligence governance tables | absent | `20260718_210000` through `20260719_160000` have not run |
| Automation revision/lifecycle columns and tables | absent | `20260720_120000` has not run |
| Dispatch Plan columns and tables | absent | `20260720_180000` has not run |
| `crawl_job_listings.crawl_job_id -> crawl_jobs.id` FK | absent | final `20260720_210000` convergence has not run |

The live non-terminal Crawl Job inventory at observation time was:

```text
162 queued                  / trigger_type=manual / no Schedule
13  manual_action_required  / trigger_type=manual / no Schedule
0   dispatching, running, or cancelling
```

These jobs are not evidence of a running external process. They still must be
cancelled and reach terminal acknowledgement before the cutover preflight can
be ready.

## Candidate lineage

The only candidate supported by the observed boundary is:

```text
20260718_120000
```

Do **not** stamp `20260718_150000`, `20260718_180000`,
`20260720_120000`, or `20260720_180000`: each would claim at least one
missing migration effect as already applied.

This read-only observation identifies a candidate; it is not by itself
authority to stamp live. Before any live stamp, the approved operator flow must:

1. create a pre-migration custom-format backup and record its SHA-256 identity;
2. restore that exact backup to a distinct database ending in
   `_cutover_restore`;
3. stamp **the restored database only** at `20260718_120000`;
4. upgrade the restored database to repository head `20260720_210000`;
5. run schema/FK/trigger parity and the Crawl Control dry-run against the
   restored database;
6. compare preserved counts with the source backup;
7. proceed to the live stamp only if all evidence is reviewed and identical.

Any unexpected table, column, constraint, migration failure, or preserve-count
drift invalidates the candidate and returns the rollout to NO-GO.

## Read-only evidence queries

The boundary was checked with `information_schema.columns`, `pg_indexes`, and
`information_schema.tables` under a read-only transaction. Re-run those checks
immediately before backup; do not reuse this dated observation as a live stamp
authorization.
