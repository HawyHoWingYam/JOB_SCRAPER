# Implementation plan

1. [x] Read the AI Enrichment component, API request path, existing tests, and
   frontend error/link conventions.
2. [x] Add a component test that returns HTTP 409 with string detail
   `jobs profile is not configured` and asserts the current generic message is
   insufficient.
3. [x] Add or preserve structured active-run conflict coverage including the run
   ID.
4. [x] Update the run error mapping and render an actionable `#settings` link for
   Jobs profile readiness failures.
5. [x] Run focused Vitest, frontend lint/type/build checks, and review successful
   run behavior for regressions.
6. [x] Update specs only if the frontend error-mapping contract is reusable, then
   complete the Trellis quality check.

## Validation commands

- `npm --prefix frontend test -- --run frontend/src/components/ai/AIEnrichmentPage.test.jsx`
- `npm --prefix frontend run lint`
- `npm --prefix frontend run build`

## Risks and rollback

- Do not treat every 409 as profile readiness; preserve structured active-run
  handling first.
- Do not render arbitrary objects or raw response bodies.
- Rollback is frontend-only; the backend readiness gate remains intact.
