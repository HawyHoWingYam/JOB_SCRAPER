# Implementation plan

1. Load backend crawl-control, scraper, manual-action, and frontend task-control specs before edits; confirm the headless child seam is available.
2. Implement task-owned fresh-profile allocation and lifecycle with an injectable liveness/process adapter and lazy 24-hour orphan cleanup.
3. Add safe singleton-marker cleanup and a fail-closed Reset service/endpoint; make the operation idempotent and record structured recovery/reset events.
4. Thread allocated profile metadata through fresh Resume while retaining fixed profile metadata for explicit `reuse_open_browser` and preserving checkpoint/status filtering.
5. Update manual-action normalization/capability projections for legacy events, headless verification-browser opt-in, helper health, reset safety, and concrete diagnostics.
6. Update Task Details/API decoders/components to render explicit open-browser, reuse, fresh, and conditional Reset controls; preserve the existing recovery panel flow.
7. Add backend tests for allocation, TTL cleanup, dead/live/unknown liveness, marker cleanup, one-retry behavior, legacy normalization, and checkpoint preservation.
8. Add frontend tests for helper-offline, headless manual challenge, explicit strategy buttons, Reset confirmation/disabled states, and generic-action removal.
9. Run targeted tests, frontend lint/build, and manual QA in container headless mode plus explicit headed verification. Stop and return to planning if any acceptance criterion is not testable.

## Current validation

- Profile allocation/reset, fail-closed liveness, projection, Reset API, and
  frontend recovery-refresh regression coverage were added.
- `python3 -m compileall -q backend/app backend/scripts backend/tests` passes.
- Frontend ESLint, Vitest (224 tests), and Vite production build pass.
- Backend pytest is pending because the current environment does not provide
  `pytest` or the installed backend dependency environment; manual recovery
  verification remains open.

## Host helper follow-up validation

- Host helper now resolves macOS/Linux/Windows `chromium`, `chrome`, and
  `msedge` executables, with a Playwright Chromium fallback and explicit
  executable-path override.
- Host helper startup translates the Compose-only PostgreSQL hostname to the
  published macOS port and returns a normal `reuse-status` response instead of
  failing the UI health flow when the browser session is simply absent.
- Docker `/app/.host_browser_profiles/...` paths are translated only at the
  host process boundary; the API-visible path remains the live-browser registry
  key for CDP reuse.
- `backend/tests/test_host_manual_action_helper.py` and the JobsDB browser
  tests pass (16 tests); an actual macOS Chromium CDP launch/close smoke also
  passed.
- Frontend ESLint and Vitest pass (227 tests), including delayed Host Helper
  health detection after the initial offline probe.
- The broader cross-source pytest collection still requires the backend's full
  dependency set (`apscheduler` is absent from the lightweight helper venv).
