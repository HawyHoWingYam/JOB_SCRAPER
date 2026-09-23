# Jev Phase 1A design

## Interfaces and seams

Phase 1A introduces three deep modules behind four public seams:

1. `GET/PUT /api/settings/ai` extends the existing Settings interface with future-run Jev defaults and masked credential state.
2. A Jev run interface starts, reads, stops, and resumes bounded decision work. Every run freezes resolved settings, endpoint/model identity, rubric version, work membership, and allowance identity.
3. A budget module exposes one atomic operation: reserve before dispatch, then settle or retain an uncertain reservation. Callers do not calculate remaining allowance themselves.
4. A native System One adapter accepts bounded state plus named typed questions and returns typed answers, token usage, latency, and an explicit answered/abstained/unavailable/invalid outcome. HTTP transport is injected at the external seam for tests.

The browser Settings page and HTTP routes are the public test seams. Tests use the real service/database behavior and fake only the external System One transport and time.

## Configuration contract

The existing Jobs and Companies LLM profiles remain unchanged. Add a separate Jev profile because `docs/jev.md` specifies a native System One endpoint, not a chat-completions provider. Store and expose:

- enabled state;
- full System One endpoint (HTTPS outside tests), model, masked API key presence/preview;
- total evaluation allowance, initially USD 10.00;
- conservative per-input-token/per-output-token rates or an explicit maximum USD reservation per request;
- sample limit, batch/question limit, concurrency, retry limit, request timeout;
- evidence and recommendation display thresholds.

Persist currency amounts as integer microdollars. Persist thresholds as decimal strings or fixed precision, never binary floats. PUT validates the complete prospective configuration before mutation. Blank secret input preserves the current key. Loading or saving settings never tests the provider or starts paid work.

Each run snapshots the resolved values. Later Settings changes apply only to a new run. Raising or resetting the cumulative allowance is an explicit operation; ordinary Settings saves cannot replenish spent or reserved amounts.

## Native System One adapter

The configured value is a full endpoint. The adapter sends `POST` directly rather than handing the full path to the official SDK, whose base URL handling would append `/v1/systemone` again. The wire request contains `state`, `model`, and a non-empty named `questions` mapping. Supported question types are `noul`, `choice`, and `score`.

The adapter validates HTTP status, JSON structure, answer type/name correspondence, returned model, and non-negative `usage.input_tokens` / `usage.output_tokens`. Network failure, timeout, non-2xx response, malformed JSON, invalid response, and missing answer remain distinguishable unavailable/invalid results. Responses and errors are bounded and secret-safe. Retry is owned by the run module so every attempt receives a budget reservation and is auditable.

## Budget and run data flow

```text
Settings defaults
  → start run and freeze configuration/work
  → estimate conservative attempt charge
  → atomically reserve against one cumulative allowance
  → dispatch one external attempt
  → settle from validated usage and configured prices
  → persist decision/error receipt
  → release only the demonstrably unused reservation
```

Reservations include concurrent attempts. A timeout or ambiguous transport failure retains an uncertain charge until reconciled; it is never silently released. A retry is a new attempt under the same cumulative allowance. Cancellation prevents new reservations and lets an in-flight attempt settle. Restarting or retrying a run does not create a fresh USD 10 allowance.

The native response has token counts but no dollar amount. Therefore live dispatch is unavailable unless configuration supplies a defensible price calculation or a maximum request charge. The UI labels locally calculated spend as an allowance ledger, not provider billing truth.

## Persistence and deployment

Use new Jev-owned tables for settings, allowances, runs, items/attempts, and immutable receipts. Do not add Jev columns to the already dirty `app_runtime_settings` table. Register models in `app.models` so the complete current metadata is bootstrapped from an empty sandbox.

The project intentionally has no in-place schema migration runtime. Deployment follows the documented sandbox cutover: stop services, export retained data, clear, deploy the complete code set, bootstrap the empty schema, import, verify, and start. Tests update exact metadata parity. Runtime feature rollback disables Jev and preserves its audit records; database downgrade is outside the current-schema contract.

## UI behavior

Add a Jev section to the existing Settings page. Basic controls show enablement, endpoint/model, masked credential, allowance and remaining amount. Advanced controls show rates/maximum reservation, sample/batch limits, concurrency, retries, timeout, and separate display thresholds. Field help distinguishes queue eligibility, list/display limits, model scores, and measured accuracy.

The run surface shows frozen settings, total/spent/reserved/remaining microdollars rendered as USD, item counts, status, errors, Stop, and resume/retry behavior. No page read or save operation performs a paid request.

## Recovery and rollback

- disabled/missing-secret/untested-price configurations are readable but cannot start paid work;
- budget exhaustion is a normal stopped/unavailable outcome, not a negative semantic decision;
- invalid or unavailable responses preserve the work item for later retry/review;
- cooperative Stop prevents the next attempt and retains completed receipts;
- disabling Jev restores existing product behavior without deleting source records or audit history.
