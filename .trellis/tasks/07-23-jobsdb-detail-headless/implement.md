# Implementation plan

1. Load backend scraper/detail-runtime specs and inspect existing JobsDB scraper tests.
2. Add a small mode resolver/helper at the scraper launch seam; preserve injected fetcher test paths.
3. Replace the hard-coded fresh-launch `headless=False` with the resolved mode flag and keep channel/executable fallback unchanged.
4. Ensure explicit `reuse_open_browser` remains an attach path independent of fresh-launch visibility.
5. Replace/route the profile-launch error through the shared recovery contract without emitting local-Edge guidance for normal headless launches.
6. Add tests for headless/headed launch kwargs, attach behavior, manual challenge payloads, cleanup, and legacy/default modes.
7. Run targeted backend tests and the relevant full backend quality checks; review against the parent acceptance criteria before the profile child consumes the seam.

## Current validation

- `python3 -m compileall -q backend/app backend/scripts backend/tests` passes.
- Frontend ESLint, Vitest (224 tests), and Vite production build pass.
- Backend pytest is pending because the current environment does not provide
  `pytest` or the installed backend dependency environment; manual
  headless/headed verification remains open.
