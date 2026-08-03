# Restore Employment Type registry after database rebuild

## Goal

Make a fresh PostgreSQL rebuild immediately usable by detail persistence by restoring the governed Employment Type registry as part of database initialization, and provide a safe one-time repair path for the current non-empty local database.

## Background

- OfferToday detail task `175dd06d-2806-4693-bfe3-fb0a1e7b2709` had 1,141 targets. Its first 29 detail requests succeeded upstream, but all 29 targets failed while persisting.
- PostgreSQL reported a foreign-key violation on `job_employment_types.employment_type_code`: values such as `full_time` and `part_time` did not exist in `employment_types`.
- The current `employment_types` table contains zero rows. The task was manually cancelled, so its remaining targets are retryable rather than lost.
- `EMPLOYMENT_TYPE_SEEDS` is the existing authority for the seven governed values (`backend/app/job_intelligence/source_attributes/module.py:30`), but database bootstrap has no seed consumer.
- Empty-schema bootstrap creates and verifies ORM tables, while intentionally refusing every non-empty database (`backend/scripts/bootstrap_db.py:33`).
- The Source Job Attributes contract requires the registry to contain the seven governed rows; detail projection assumes those parent rows already exist.

## Requirements

### R1. Canonical registry ownership

- `EMPLOYMENT_TYPE_SEEDS` remains the single source of truth for Employment Type code, label, and display order.
- Bootstrap and repair code must consume that authority rather than duplicate the seven values.

### R2. Empty-database bootstrap

- A successful empty-schema bootstrap must create the current schema and all seven Employment Type rows atomically.
- Bootstrap must verify the registry's exact canonical contents before reporting success.
- The existing refusal to operate on a non-empty database must remain unchanged; bootstrap must not become an in-place migration or general repair mechanism.

### R3. Existing-database repair

- Provide an explicit, narrowly scoped, idempotent repair operation for a non-empty database whose Employment Type registry is missing rows.
- Missing canonical rows must be inserted. Existing canonical codes with a non-canonical label or display order must be updated to the values in `EMPLOYMENT_TYPE_SEEDS`.
- Unknown extra codes must not be deleted automatically; report them for operator review.
- The repair operation must not create, drop, or alter schema objects and must not modify unrelated data.

### R4. Persistence diagnostics

- When detail persistence fails, operators must receive a sanitized diagnostic that identifies the database constraint/root cause well enough to distinguish missing registry data from a generic `IntegrityError`.
- Diagnostics must not expose full job payloads or secrets.

### R5. Regression and operational verification

- Cover empty bootstrap, non-empty bootstrap refusal, seed-boundary idempotency, missing/conflicting seed handling, and OfferToday detail persistence against a populated registry.
- Retained-data cutover/rebuild rehearsal must prove the canonical registry exists before crawl workers are started.
- After repairing the current database, retrying or resuming work must use the existing retryable targets; the fix must not require discarding the crawl task's retained data.

## Acceptance Criteria

- [x] AC1: Bootstrapping a zero-table database commits the current ORM schema and exactly the seven rows defined by `EMPLOYMENT_TYPE_SEEDS` in one transaction.
- [x] AC2: If schema creation, registry insertion, or registry verification fails, bootstrap does not leave a partially initialized database.
- [x] AC3: Running bootstrap against any non-empty database still raises `DatabaseBootstrapError` before schema or data mutation.
- [x] AC4: The explicit repair operation inserts missing canonical rows, corrects non-canonical labels/display ordering, reports but preserves unknown extra codes, and can be rerun without further changes or duplicates.
- [x] AC5: Repair tests cover missing rows, incorrect canonical labels/display ordering, and unknown extra codes.
- [x] AC6: OfferToday detail persistence succeeds for canonical employment types after bootstrap/repair, including at least `full_time` and `part_time`.
- [x] AC7: A persistence failure records/logs a sanitized, actionable database cause rather than only `persist_failure:IntegrityError`.
- [x] AC8: The disposable PostgreSQL cutover/rebuild rehearsal verifies all seven registry rows before services restart.
- [x] AC9: The current local database can be repaired without dropping its retained crawl/job data, after which retryable targets from task `175dd06d-2806-4693-bfe3-fb0a1e7b2709` can be processed normally.

## Out of Scope

- Changing OfferToday listing coverage, pagination, category, or keyword behavior.
- Adding new Employment Type values or changing the canonical seven-value taxonomy.
- Weakening bootstrap's zero-table precondition.
- Building a general-purpose migration framework or repairing unrelated registry tables.
- Automatically restarting the cancelled crawl task as part of database repair.
