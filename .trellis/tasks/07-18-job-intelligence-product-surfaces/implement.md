# Job intelligence product surfaces implementation plan

## Dependencies

- Requires reviewed/readable child 2–5 response and decision contracts.
- Requires the reviewed foundation conflict, idempotency, and audit conventions consumed by those contracts.
- Do not begin against guessed payloads; backend fixture exports are the readiness gate.

## Ordered checklist

1. [x] Load `trellis-before-dev` for frontend/backend and reread parent/child artifacts plus backend fixtures.
2. [x] Add failing contract tests for governance summary/queues/details/decisions and updated Job/Company/filter schemas.
3. [x] Add `jobIntelligenceApi` adapter and response normalization with no domain inference.
4. [x] Build route shell, deep-link state, peer area navigation, pending badges, and local-operator notice.
5. [x] Build shared queue/evidence/recommendation/dialog/audit Modules and stale-version behavior.
6. [x] Implement Job Taxonomy Review area against real endpoints.
7. [x] Implement Skill Candidates area and all four confirmation variants.
8. [x] Implement Company Industries revision/tree/mapping/review/audit area.
9. [x] Update Job Browser filters/cards/chips and query utilities to stable multi-value contracts.
10. [x] Update Job Detail, Add Job, Companies, AI Enrichment, and Dashboard terminology/data states/deep links.
11. [x] Add accessibility/responsive/error/empty/conflict tests and perform browser visual/keyboard QA.
12. [x] Run full frontend and backend contract validation.

## Validation

```bash
cd frontend && npm run lint
cd frontend && npm test
cd frontend && npm run build
cd backend && pytest -q tests/test_job_intelligence_response_contracts.py
python3 ./.trellis/scripts/task.py validate 07-18-job-intelligence-product-surfaces
```

Manual QA matrix:

- three governance areas at desktop and narrow viewport;
- keyboard-only queue/tree/dialog flow;
- valid decision, stale conflict, API error, empty queue, Unknown evidence;
- Job Browser multi-filters and active chips;
- Job Detail assigned/unassigned and governed/unreviewed variants;
- long English/Chinese HSIC breadcrumbs and multiple `+N` displays.

## Completion evidence (2026-07-20)

- Frontend: ESLint passed with zero warnings; all 26 files / 172 tests passed;
  Vite production build passed.
- Backend Product contracts: 21 tests passed. Adjacent Source, Canonical,
  Company Industry, Skill, architecture, and AI Enrichment gates passed for a
  total of 137 relevant tests, with PostgreSQL files run sequentially against
  `job_intelligence_product_surfaces_test`.
- Backend static gates: targeted Ruff, Black check, mypy, and `compileall`
  passed.
- Browser QA: desktop and 500px narrow layouts, all three governance areas,
  tab/queue keyboard navigation, explicit narrow Back, dialog focus/Escape,
  long hash/ID and English/CJK stress text, and large counts showed no
  document-level horizontal overflow or console warnings/errors.
- Retired-term audit found no user-facing `Job Type`, `AI Category`, bare
  canonical `Classification`, or `Provisional Skills`. Compatibility fields
  remain evidence-only and render under governed/current terminology.
- No live publication, activation, migration, backfill, corpus mutation,
  embedding cutover, or production smoke was executed by this child.

## Risk and rollback points

- Keep new route behind a local feature flag until all three areas have stable contracts.
- Do not retain legacy labels as hidden fallbacks in shared render helpers.
- If one domain endpoint is delayed, show its scoped unavailable state; do not fake data or block other areas.
- Application rollback may restore old UI while new backend projections remain; no destructive data action belongs to this child.
