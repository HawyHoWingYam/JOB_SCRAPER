# Implementation plan

1. Add backend contract fields/action kinds and structured dismissal request /
   response/error contracts.
2. Add a row-locked service operation that finds the latest `crawl.failed`,
   enforces terminal state and expected sequence, and idempotently appends the
   source-neutral dismissal event.
3. Add the mutation API and ensure task snapshots ignore the Board-only event
   for lifecycle/status normalization.
4. Extend Board event loading/projection to suppress only a dismissal matching
   the current failure, and expose Dismiss only on `failed_run`.
5. Add backend tests for success, unchanged task reads/status, idempotency,
   stale sequence, non-failed rejection, and later-failure visibility.
6. Add the frontend API command/action label/handler and refresh behavior.
7. Add frontend tests for failed-only rendering, immediate mutation/refresh,
   and mutation failure feedback.
8. Run focused backend tests in `backend-api`, frontend Vitest/ESLint, Ruff or
   repository-standard lint, compile checks, and `git diff --check`.
9. Use the public action to dismiss the historical CTGoodJobs failure and
   verify its attention count drops while Task Details/Logs remain readable.

## Risky seams

- Appending an unknown event can accidentally become the latest task snapshot
  event and erase normalized failure metadata; lifecycle selection must remain
  explicit.
- Checking only job status without the failure sequence can hide a newer retry
  failure.
- Filtering the job itself instead of one Board item would change Task Details
  or automation latest-outcome semantics.
- Optimistic frontend removal without a server refresh can mask a rejected
  stale dismissal.

## Validation commands

```bash
docker exec backend-api python -m pytest -q /app/tests/test_crawl_control_api.py
docker exec backend-api python -m pytest -q /app/tests/test_dispatch_plan_service.py
cd frontend && npm test -- --run src/features/taskControl/board/TaskControlBoardPage.test.jsx
cd frontend && npm run lint
python3 -m compileall -q backend/app backend/tests
git diff --check
```

## Completion evidence

- Backend Crawl Control API and snapshot suites: `40 passed`.
- Frontend full Vitest suite: `239 passed`; ESLint and production build passed.
- Ruff, `compileall`, and `git diff --check` passed.
- Historical CTGoodJobs task `a454498d-7954-4039-82f0-ae0f06882e4e`
  dismissed failure sequence `3` through the public endpoint. The durable
  dismissal is event sequence `4`; CTGoodJobs attention count changed from
  `1` to `0`, while Task Details remains `failed` with its issue and events.
  After an API restart the count remained `0`; replay returned the original
  sequence `4` with `replayed=true` and the dismissal event count remained `1`.
