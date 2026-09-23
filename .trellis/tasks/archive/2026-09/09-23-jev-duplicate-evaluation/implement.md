# Phase 3A duplicate evaluation implementation plan

## TDD slices

1. **Controlled contract and fixtures** — complete
   - Red: strict schema/hash/group/strata and transitive-trap tests.
   - Green: add versioned bilingual pair fixtures and loader/verifier.
   - Check: fixture-focused pytest plus deterministic replay.
2. **Pure candidate generator** — complete
   - Red: symmetric union, stable tie/order, top-K cap, missing evidence,
     same-source repost, cross-source hard negatives, and recall@K tests.
   - Green: implement normalized lexical and frozen-vector candidate adapters.
   - Check: no database/session dependency in pure scoring.
3. **Read-only real exporter** — complete
   - Red: PostgreSQL-only, `SET TRANSACTION READ ONLY`, bounded jobs/pairs,
     minimization, exact file set/hash, source identity, embedding provenance,
     and forbidden raw-field tests.
   - Green: export/verify manifest against the current three-source corpus.
   - Check: repeat export with frozen capture time and compare semantic output.
4. **Typed Jev pair runner** — complete
   - Red: exact choice request, receipt bindings, abstain/error states,
     stop-on-ambiguity, persistent budget, unchanged-invalid-key zero-call gate,
     and restart idempotence.
   - Green: reuse Phase 1 native adapter/run/ledger with isolated state DB.
   - Check: loopback fake provider only; no real call while fingerprint is
     unchanged.
5. **Metrics and report** — complete
   - Red: blocker miss, false association, zero denominator, low-coverage false
     success, option reversal, strata, latency/tokens/cost, and deterministic
     proceed/defer/inconclusive tests.
   - Green: JSON and Markdown report with frozen gates echoed verbatim.
6. **Real bounded evaluation** — complete
   - Export and verify a capped real snapshot; run free baselines first.
   - If the credential fingerprint is unchanged, produce an inconclusive report
     without dispatch. If changed, reserve one USD 0.05 maximum development
     smoke and continue only after a typed successful answer.
7. **Quality and integration gate** — in progress
   - Run all duplicate-evaluation tests after each slice.
   - Run complete Jev backend regression, formatting/lint/compile, PostgreSQL
     read-only rehearsal, artifact replay, secret scan, and `git diff --check`.
   - Attempt broad backend/frontend suites and classify only independently
     reproduced pre-existing failures separately.
   - Update the Jev spec and bound GitHub issue; archive without committing
     unrelated dirty-worktree changes.

## Expected files

```text
backend/app/services/jev_duplicate_evaluation.py
backend/app/services/jev_duplicate_corpus.py
backend/app/services/jev_duplicate_runner.py
backend/scripts/jev_duplicate_evaluation.py
backend/tests/fixtures/jev_duplicate_controlled_v1.jsonl
backend/tests/test_jev_duplicate_*.py
.trellis/spec/backend/jev-system-one.md
```

Existing Phase 1 modules may receive narrow reusable helpers and tests. Product
models, routes, Related Jobs, Job Browser, and production database schema are
not changed in this task.

## Validation commands

```text
docker compose exec -T backend-api sh -lc 'pytest -q tests/test_jev_duplicate_*.py'
docker compose exec -T backend-api sh -lc 'pytest -q tests/test_jev*.py tests/test_ai_settings.py tests/test_sandbox_cutover.py'
docker compose exec -T backend-api ruff check <owned Python files>
docker compose exec -T backend-api black --check <owned Python files>
docker compose exec -T backend-api python -m compileall -q <owned Python files>
git diff --check
```

## Stop conditions

- Do not call the real provider with the known rejected key fingerprint.
- Stop on artifact/hash/provenance failure, uncertain reservation, missing
  maximum price bound, or a failed development smoke.
- Do not implement product persistence/UI merely because offline gates pass;
  that requires a separate Phase 3B rollout task.
