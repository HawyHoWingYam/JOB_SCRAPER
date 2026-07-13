# OfferToday Phase A-B execution plan

## Checklist

1. [x] Audit the current dirty worktree and retain only Phase A/B-aligned hunks; record any overlap with unrelated edits.
2. [x] Freeze v1 canonical candidate/hash and exact verifier routing; capture before-change generic/strict results for locally available Plan 2 artifacts.
3. [x] Finish typed cursor/request/transport/page/evidence/candidate contracts and payload-builder compatibility tests.
4. [x] Finish the condition-local cursor runner, separate supplemental cohort handling, retry/restart/terminal semantics, and conservation tests.
5. [x] Finish typed browser transport, context identity, all runtime lifecycle ownership, cleanup, and service tests.
6. [x] Finish v2 observation/artifact schemas and strict replay, including tamper/leak/order/budget/no-write negative fixtures.
7. [x] Finish the frozen bake-off model, metrics, comparison gates, and deterministic decision tests.
8. [x] Finish the three CLI commands, baseline/current-database gate, budgets, artifact export, offline parent validation, exit codes, and strict verification.
9. [x] Run the focused suite, complete backend suite, production-default guards, artifact regression, compilation/static checks as applicable, and `git diff --check`.
10. [x] Review the scoped diff against Tasks 1-8 and obtain the live review gate.
11. [x] If approved and environment-ready, capture fresh baselines, run repeat 1 and 2, verify each, compare offline, independently recompute, then freeze only one accepted candidate.
12. [x] Record an explicit rejected/no-candidate stop if no variant passes; do not begin Phase C automatically.

## Focused Verification

```powershell
python -m pytest -q `
  backend/tests/test_offertoday_listing_contract.py `
  backend/tests/test_offertoday_listing_runner.py `
  backend/tests/test_offertoday_browser_runtime.py `
  backend/tests/test_offertoday_pagination_bakeoff.py `
  backend/tests/test_offertoday_research_live_service.py `
  backend/tests/test_offertoday_research_observation_service.py `
  backend/tests/test_offertoday_research_calibration.py `
  backend/tests/test_offertoday_search_space.py `
  backend/tests/test_offertoday_research_artifacts.py `
  backend/tests/test_offertoday_research_conservation.py `
  backend/tests/test_offertoday_research_stage_gate.py `
  backend/tests/test_offertoday_pagination_stage_gate.py `
  backend/tests/test_offertoday_research_census_cli.py `
  backend/tests/test_offertoday_research_stability.py `
  backend/tests/test_offertoday_detail_pipeline.py `
  backend/tests/test_offertoday_canonical_and_identity.py `
  backend/tests/test_crawl_job_runtime.py `
  backend/tests/test_offertoday_standalone_crawl.py
```

## Full and Artifact Verification

```powershell
python -m pytest -q backend/tests
git diff --check
python backend/scripts/offertoday_research.py verify-artifact --artifact <artifact>
python backend/scripts/offertoday_research_census.py verify-run --artifact <artifact>
```

## Live Review Inputs

- Scoped source/test diff and passing deterministic outputs.
- Unchanged production-default guard evidence.
- Exact frozen seed, budgets, variant definitions, code/provenance hash, and artifact root.
- Two fresh matching baselines for each repeat and current database equality.

## Rollback Points

- Stop before browser startup on baseline or parent-artifact mismatch.
- Stop the run on cursor/auth/WAF/IP/identity/gap/conservation/leak/budget failure.
- Preserve every valid rejected artifact; never amend thresholds after live artifacts exist.
- Restart a browser-lost condition from page 1; never resume a cursor mid-condition.
