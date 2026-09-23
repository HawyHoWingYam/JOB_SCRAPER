# Jev Phase 1A implementation plan

## TDD seams

The user approved these public seams with the phased plan: Settings GET/PUT and UI; bounded run start/status/stop/resume; the native System One decision interface; and final browser E2E. Mock only the external HTTP transport and time. Each numbered slice follows red → green and runs its focused tests before the next slice.

## Ordered slices

1. **Native protocol contract**
   - Add request/response types and a transport-injected async adapter.
   - Tests: exact URL/body/auth behavior with a fake HTTP boundary; noul/choice/score decoding; usage; timeout, non-2xx, malformed and invalid responses; secret-safe errors.
2. **Jev settings persistence and HTTP round-trip**
   - Add Jev-owned settings/allowance models, validation, masked serialization, and extend Settings GET/PUT.
   - Tests: defaults, partial update, invalid range/HTTPS validation, blank-secret preservation, masking, and no external call on GET/PUT.
3. **Atomic allowance ledger**
   - Reserve/settle/uncertain operations using integer microdollars and row locks/conditional state.
   - Tests: exact arithmetic, exhaustion, concurrent reservations, retry/restart sharing, under/over reconciliation, ambiguous failure, and no reservation without a price bound.
4. **Bounded run lifecycle**
   - Add frozen run/item/attempt records plus start/status/stop/resume routes and cooperative execution.
   - Tests: snapshot immutability, stable membership/order, attempt receipts, cancellation, terminal idempotence, retry behavior, and zero paid dispatch from read paths.
5. **Settings and run UI**
   - Extend `AISettingsPage` with basic/advanced Jev controls and masked secret behavior; add bounded-run launch/status/stop controls at the agreed operations surface.
   - Tests: load/edit/save round-trip, validation messages, allowance display, advanced controls, frozen-run display, disabled/unavailable states, and no fetch that starts work during render.
6. **Cross-layer integration and E2E harness**
   - Verify frontend payloads against live backend test server and a local fake System One server. Add a browser E2E framework/config if none exists.
   - E2E: configure mock endpoint and credential, save/reload, start a bounded run, observe receipt/usage/allowance, stop or complete, verify Settings changes affect only a later run, and confirm no real external request occurs.
7. **Cutover and rollback verification**
   - Update bootstrap metadata parity and retained export/import handling for new current-schema tables where required.
   - Verify empty bootstrap, non-empty refusal, disposable cutover rehearsal, and feature-disable rollback.

## Focused validation commands

Commands may be narrowed during red/green cycles; final Phase 1A verification must include:

```text
cd backend && pytest -q tests/test_jev_system_one.py tests/test_jev_settings.py tests/test_jev_budget.py tests/test_jev_runs.py
cd backend && pytest -q tests/test_ai_settings.py tests/test_classification_batch_runtime.py tests/test_crawl_control_bootstrap.py
cd frontend && npm test -- --run src/components/settings/AISettingsPage.test.jsx
cd frontend && npm run lint
cd frontend && npm run build
<new browser E2E command against backend + local fake System One server>
git diff --check
```

## Full-stage gates

- Run backend and frontend full suites after the focused Phase 1A tests pass.
- Confirm no request reached the real endpoint and no allowance was charged during tests.
- Run `trellis-check`, update the applicable specs, perform code review against issue #63, and only then complete/archive Phase 1A.
- Phase 1B remains blocked until the frozen configuration, native decision, and cumulative allowance interfaces are verified.

## Risk and rollback points

- Never copy the bearer credential from `docs/jev.md` into tracked content or test output.
- Preserve unrelated dirty work in overlapping Settings/model files and inspect hunks before every edit.
- If the external host differs from the verified System One schema, record unavailable/invalid receipts and stop; do not weaken validation.
- Feature rollback is `enabled=false`; records stay available for audit. Schema deployment follows the complete sandbox cutover rather than an in-place migration.
