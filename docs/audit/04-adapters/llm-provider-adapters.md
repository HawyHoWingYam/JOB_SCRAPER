# Adapter Boundary: LLM Provider Adapters

## Current Responsibilities

LLM provider adapters normalize Anthropic/Claude, Gemini, Custom, Zhipu, and Mock providers behind job enrichment, company enrichment, runtime settings, readiness checks, and provider status reporting.

## Current Implementation Map

- Provider clients and provider specs: `backend/app/ai/llm_client.py`
- Runtime settings service: `backend/app/services/ai_runtime_settings_service.py`
- Settings API/UI: `backend/app/api/settings.py`, `frontend/src/components/settings/AISettingsPage.jsx`
- Job/company enrichment APIs: `backend/app/api/ai.py`, `backend/app/api/companies.py`
- Job enrichment worker: `backend/app/workers/run_enrichment_worker.py`
- Runtime model: `backend/app/models/app_runtime_settings.py`

## Data and Control Flow

The app stores separate `jobs` and `companies` runtime profiles in `app_runtime_settings`. Protected job and company enrichment endpoints call `ensure_profile_runtime_ready`, which requires a successful profile test for the current config fingerprint. Settings APIs mask saved secrets and expose provider status, active model, support flags, and last-test fingerprints.

`claude` is supported as a compatibility alias that uses Anthropic settings and the Anthropic client builder. The custom provider defaults to Anthropic-compatible request format and can also use `openai_responses`, which is the custom path that supports web-search requests. Company enrichment requests web search only when the selected client reports support.

## Tests and Coverage

- `backend/tests/test_llm_client.py`
- `backend/tests/test_ai_runtime_settings_service.py`
- `backend/tests/test_ai_settings_api.py`
- `backend/tests/test_ai_enrichment_dispatch_api.py`
- `backend/tests/test_company_enrichment_service.py`
- `backend/tests/test_enrichment_run_service.py`
- `backend/tests/test_enrichment_worker.py`
- `frontend/src/components/settings/AISettingsPage.test.jsx`

## Known Gaps or Risks

- Run and item rows do not snapshot provider name, model, config fingerprint, capability flags, latency, token usage, cost, or provider request IDs.
- Provider readiness is fingerprint-based at dispatch time, but drift after dispatch is only indirectly visible through settings status.
- Custom provider supports multiple wire formats, so validation and UI mapping can diverge from concrete provider capabilities.
- Secret storage is database-backed with response masking; encryption, rotation, backup handling, and audit policy remain unresolved.
- Job and company enrichment share provider primitives but still have different execution models and retry behavior.

## Optimization Backlog

- Define a shared provider probe contract and capability matrix covering JSON mode, web search, max token behavior, retryable errors, and model identity.
- Persist provider, model, config fingerprint, capability snapshot, and request telemetry on enrichment run and item records.
- Add drift warnings when saved runtime settings no longer match the fingerprint used by queued or running work.
- Decide the secret storage boundary for API keys, including encryption-at-rest or external secret manager ownership.
- Clarify whether the `claude` alias should remain backend-only compatibility or become a visible UI provider option.

## Follow-up Audit Questions

- Should company enrichment move onto the same durable worker path before provider telemetry is added?
- Should provider readiness tests be required per scope, per model, or per provider credential?
- Which provider errors should be normalized for operator retry versus surfaced as raw provider detail?
