# Phase 3B crawl-content quality implementation plan

## TDD slices

1. [x] Strict controlled contract and bilingual/source-balanced fixtures.
2. [x] Pure deterministic baseline and bounded uncertain-candidate selector.
3. [x] Typed Jev request/runner and immutable observations using the shared ledger.
4. [x] Full-denominator metrics.
5. [x] PostgreSQL read-only minimized real snapshot and replay verifier.
6. [x] Development smoke stopped safely on the first ambiguous HTTP 520;
   held-out execution was correctly not started.
7. [x] Full local quality gate, result/spec/Issue update, and safe archive.

## Expected files

```text
backend/app/services/jev_crawl_quality.py
backend/app/services/jev_crawl_quality_corpus.py
backend/app/services/jev_crawl_quality_runner.py
backend/scripts/jev_crawl_quality_evaluation.py
backend/tests/fixtures/jev_crawl_quality_controlled_v1.jsonl
backend/tests/test_jev_crawl_quality_*.py
.trellis/spec/backend/jev-system-one.md
```

## Validation

```text
docker compose exec -T backend-api pytest -q tests/test_jev_crawl_quality_*.py
docker compose exec -T backend-api pytest -q tests/test_jev*.py tests/integration/test_jev_sandbox_cutover_rehearsal.py
docker compose exec -T backend-api ruff check <owned Python files>
docker compose exec -T backend-api black --check <owned Python files>
docker compose exec -T backend-api python -m compileall -q <owned Python files>
git diff --check
```

## Stop conditions

- Stop paid execution after an ambiguous/technical failure.
- Stop on artifact/hash/schema/privacy failure or budget exhaustion.
- Do not introduce product persistence/UI or call any crawl-side-effect service
  in this task, even if controlled gates pass.
