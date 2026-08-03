# Implementation Plan: Restore Employment Type registry

## Ordered Work

1. Create a GitHub issue for this child defect and link it to the parent OfferToday coverage issue (#46).
2. Add focused tests for the shared seed boundary: insert all seven rows, rerun idempotently, populate a partially missing registry, canonicalize incorrect labels/order, and report/preserve unknown codes.
3. Implement the shared seed/verification boundary using `EMPLOYMENT_TYPE_SEEDS`, with caller-owned transactions and no duplicated seed literals.
4. Extend empty-schema bootstrap to call the boundary inside its existing transaction and verify exact registry contents before success.
5. Add an explicit non-empty-database repair command that checks the expected table, modifies only Employment Type rows, and reports inserted/unchanged/conflicting results.
6. Add OfferToday persistence regression coverage proving canonical employment values no longer fail their foreign key.
7. Improve detail persistence diagnostics with bounded, sanitized database cause information while preserving stable failure categorization.
8. Extend the disposable PostgreSQL cutover/rebuild rehearsal to assert the exact seven-row registry after bootstrap/import and before service restart.
9. Run the repair command against the current local retained-data database, verify the registry, then process a small retry batch from task `175dd06d-2806-4693-bfe3-fb0a1e7b2709` before allowing the rest to continue.

## Validation

From `backend/`:

```bash
pytest tests/test_crawl_control_bootstrap.py
pytest tests/test_source_job_attributes.py tests/test_source_job_attribute_ingest.py tests/test_manual_job_intake.py
pytest tests/test_cross_source_crawl_logging.py tests/test_dispatch_plan_service.py
```

Run the relevant disposable PostgreSQL/Redis integration test when test service URLs are available:

```bash
pytest tests/integration/test_sandbox_cutover_rehearsal.py
```

Operational checks:

```sql
SELECT code, label, display_order
FROM employment_types
ORDER BY display_order;
```

Expected result: exactly seven canonical rows in the order defined by `EMPLOYMENT_TYPE_SEEDS`.

## Risk and Review Gates

- Review transaction ownership before changing bootstrap; seed code must not commit inside bootstrap's transaction.
- Test real PostgreSQL rollback semantics rather than relying only on SQLite behavior.
- Confirm repair touches only `employment_types`; it must not rebuild schema or delete crawl/job data.
- Review exception sanitization to ensure useful constraint metadata is retained without recording raw payloads.
- Before retrying all 1,112 remaining targets, run a small controlled batch and confirm both job persistence and task counters advance normally.

## Pre-Start Gate

- PRD convergence pass completed after selecting automatic canonicalization (option B).
- Obtain user review and approval before `task.py start` or any implementation.

## Completion Evidence

- GitHub Issue: #48, linked by the Trellis start hook.
- Current `jobsdb` repair: registry changed from 0 rows to the exact seven canonical rows; no schema or retained crawl/job data was deleted.
- Real PostgreSQL bootstrap and rollback tests: 10 passed.
- Real PostgreSQL Source Job Attribute/OfferToday persistence tests: 13 passed, including `full_time` plus `part_time` through `OfferTodayDetailPipeline`.
- Disposable PostgreSQL + Redis cutover rehearsal: passed two complete rebuild cycles with exact registry verification.
- Focused SQLite/service tests: 44 passed, 3 PostgreSQL-only skips before the dedicated test database was configured.
- Ruff, `compileall`, and scoped `git diff --check`: passed.
- Live crawl smoke was not launched because other OfferToday runs remain active/manual-action and the cancelled source task cannot be resumed. A later small detail task can reuse the retained pending backlog without changing this fix.
- Known unrelated baseline: `test_job_detail_schema_serializes_complete_source_attribute_arrays` references absent `Job.job_skill_mentions`; scoped mypy expands to existing legacy SQLAlchemy annotation errors.
