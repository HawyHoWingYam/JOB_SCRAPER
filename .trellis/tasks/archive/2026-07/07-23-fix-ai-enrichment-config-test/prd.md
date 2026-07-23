# Fix AI enrichment configuration test errors

## Goal

Make the AI Enrichment settings test actionable when a draft profile is invalid or not ready. The operator must see the safe, specific reason for the failed test instead of only a generic `LLM operation failed (error_type=ProfileRuntimeNotReadyError)` summary.

## Background and confirmed facts

- `POST /api/v1/settings/ai/test` validates the submitted draft profile before probing the provider in `backend/app/api/settings.py:216-233`.
- Profile validation raises `ProfileRuntimeNotReadyError` for an unconfigured provider, unsupported provider, missing required settings, or unsupported custom API format in `backend/app/services/ai_runtime_settings_service.py:781-814`.
- The test endpoint's broad exception handler currently passes those safe validation errors through `safe_llm_error_message`, which hides the original message in `backend/app/api/settings.py:318-351` and `backend/app/ai/llm_client.py:284-292`.
- The settings UI only reads `payload.detail.error_message` and otherwise falls back to `Configuration test failed` in `frontend/src/components/settings/AISettingsPage.jsx:904-912`.
- This behavior was introduced by the `6992bd85` error-sanitization change; the requested fix is limited to preserving actionable profile-validation diagnostics and covering the regression.

## Requirements

1. Preserve a bounded, secret-safe, human-readable reason when AI profile validation fails during a configuration test.
2. Keep provider/upstream failure sanitization unchanged for errors that could contain credentials, prompts, or raw upstream response details.
3. Keep the existing 422 response shape compatible with the settings UI (`detail.error_message` and `config_fingerprint` where available).
4. Ensure the UI displays the returned diagnostic for both job AI Enrichment and Company profiles; retain the generic fallback only when the server provides no diagnostic.
5. Add regression coverage for the failing validation path and the UI error rendering/request flow without requiring a live LLM provider.

## Acceptance Criteria

- [x] Testing an unconfigured or incomplete AI Enrichment draft returns HTTP 422 with a specific safe message such as the missing profile setting, not `LLM operation failed (error_type=ProfileRuntimeNotReadyError)`.
- [x] The frontend shows that specific message in the configuration-test feedback alert for both profile scopes.
- [x] Upstream/provider errors continue to use the existing bounded safe summary behavior.
- [x] Backend and frontend regression tests pass, and no unrelated working-tree changes are modified.

## Out of scope

- Changing provider requirements, API-format options, LLM probe prompts, runtime readiness rules, or persisted settings schema.
- Changing the HTTP status code or introducing a new error envelope.
- Fixing an actual provider/network failure reported by a live deployment.
