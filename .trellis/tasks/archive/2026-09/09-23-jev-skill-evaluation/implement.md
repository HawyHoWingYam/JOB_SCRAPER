# Jev Phase 1B implementation plan

## TDD seams

1. **Versioned manifest and controlled fixtures**
   - Add strict dataclasses/Pydantic schemas, canonical hashes, grouped split
     validation, bilingual explicit-answer fixtures, negation/preference/
     incidental/missing/reordered cases.
   - Tests fail on duplicate IDs, group leakage, hash drift, unsupported labels,
     missing strata, and mutable/unknown fields.
2. **Pure baselines and question builders**
   - Extract/reuse local Skill similarity and exact/alias snapshot matching.
   - Build bounded evidence/recommendation System One requests with stable
     taxonomy codes and deterministic reordered variants.
   - Tests cover exact, alias, generic/reject, missing option, Chinese/mixed
     text, stable tie-breaks, and zero database writes.
3. **Read-only real-corpus export**
   - PostgreSQL-only read-only transaction, bounded sample, minimal fields,
     canonical description/taxonomy hashes, connected grouping and temporal
     split, explicit weak/unresolved reference provenance.
   - Tests assert `SET TRANSACTION READ ONLY`, deterministic output, no raw_data,
     no mutation imports/calls, and fail-closed artifact verification.
4. **Evaluation runner and immutable observations**
   - Validate/plan offline; live run only with explicit confirmation. Reuse the
     Phase 1A native adapter and cumulative budget reservations in an isolated
     evaluation database/artifact session; stop after ambiguous failure.
   - Tests cover one-call smoke, retries sharing allowance, unavailable/
     invalid/abstained observations, resume idempotence, secret-safe artifacts,
     and no production writes.
5. **Metrics and report**
   - Separate controlled correctness from real-reference agreement; retain all
     unresolved/errors in denominators; report strata, stability, latency,
     tokens and integer-microdollar spend.
   - Tests cover all-pass, low-coverage false success, zero denominator,
     budget-limited inconclusive, and deterministic proceed/defer output.
6. **Live bounded execution**
   - Validate artifacts, run one development smoke with the configured real
     credential, and continue only if typed response succeeds and budget bound
     is verified. Generate JSON + Markdown reports.
7. **Quality gates**
   - Focused backend tests after every slice; complete Jev tests, lint/compile,
     artifact replay, `git diff --check`, Trellis check, spec update and issue
     review. Full project suites are attempted and pre-existing failures are
     reported separately.

## Commands

```text
docker compose exec -T backend-api pytest -q tests/test_jev_evaluation_*.py
docker compose exec -T backend-api python scripts/jev_skill_evaluation.py validate --controlled ...
docker compose exec -T backend-api python scripts/jev_skill_evaluation.py plan --controlled ...
docker compose exec -T backend-api python scripts/jev_skill_evaluation.py report --controlled ... --observations ...
git diff --check
```

## Safety

- Never print/store the key from `docs/jev.md`.
- Never invoke enrichment, taxonomy synchronization, Candidate decision, or
  production Jev run endpoints during evaluation.
- Real export requires DB-enforced read-only transaction and bounded rows.
- Do not send full `raw_data`; minimize/strip contact details from model state.
- Do not tune frozen held-out gates after seeing held-out output.
