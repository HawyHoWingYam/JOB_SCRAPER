# Implementation plan

1. Confirm current source/spec context for the JobsDB scraper, crawl-control contracts, manual-action normalization, and frontend task-control components.
2. Implement the headless child first:
   - resolve reviewed `crawl_mode` at JobsDB fresh launch;
   - pass the derived `headless` flag into the existing Playwright fallback helper;
   - preserve explicit CDP attach for `reuse_open_browser`;
   - update unit tests for both launch modes and manual recovery.
3. Implement profile/recovery backend primitives:
   - allocate and persist task-owned fresh profile paths;
   - add injectable process/registry liveness checks;
   - add safe stale-lock marker cleanup, one retry per Resume, terminal cleanup, and lazy TTL orphan cleanup;
   - normalize legacy events and enrich manual-action/recovery event payloads;
   - add a Reset endpoint/action with fail-closed responses.
4. Update capability/action projections and frontend Task Details to expose explicit open-browser, reuse, fresh-profile, and conditional Reset controls while sharing the existing helper flow.
5. Add backend unit/integration tests, frontend component/API tests, and regression coverage for the affected task shape and legacy payloads.
6. Run the quality gate: targeted backend tests, frontend tests/lint/type checks, then the full relevant suite and manual QA in a headless container plus an explicit headed verification flow.
7. Review cross-child acceptance criteria, update specs if a reusable profile/recovery contract was learned, and only then activate/start implementation.

## Validation commands

- `pytest -q backend/tests -k 'jobsdb or manual_action or crawl_job_dispatch or task_control'`
- `npm --prefix frontend test -- --runInBand` (or the repository’s documented frontend test command)
- `npm --prefix frontend run lint`
- `npm --prefix frontend run build`
- Targeted Playwright launch tests with mocked Chromium and process/registry adapters.

## Risk and rollback points

- Risk: changing profile paths can break reuse of an existing browser. Keep fixed headed profile metadata unchanged and gate new paths behind `fresh_profile`.
- Risk: dispatch-plan resume contracts may reject a new field. Extend contracts compatibly and preserve the existing strategy literals.
- Risk: frontend action projection drift. Reuse normalized capabilities and add decoder/component tests before changing labels.
- Rollback: disable new reset action and fresh-profile allocator while retaining mode-aware launch; never run destructive profile deletion without the liveness guard.

## Current validation

- Python compileall passes for backend application, scripts, and tests.
- Frontend ESLint, the full Vitest suite (224 tests), and the Vite production
  build pass.
- Backend pytest and live manual headless/headed verification remain pending
  because this checkout lacks the backend test/dependency environment.
