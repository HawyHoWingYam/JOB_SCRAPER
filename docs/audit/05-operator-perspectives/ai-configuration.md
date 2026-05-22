# Operator Perspective: AI Configuration

## Current Responsibilities

This perspective covers selecting LLM providers, entering credentials, testing profiles, saving runtime settings, and controlling enrichment concurrency.

## Current Implementation Map

- Frontend: `frontend/src/components/settings/AISettingsPage.jsx`
- Backend: `backend/app/api/settings.py`
- Service: `backend/app/services/ai_runtime_settings_service.py`
- Provider clients: `backend/app/ai/llm_client.py`
- Model: `backend/app/models/app_runtime_settings.py`

## Data and Control Flow

Operators edit separate job and company profiles. The frontend submits only relevant provider fields, hides saved secrets by default, and can test a draft profile before save. Backend returns persisted/effective config plus runtime status.

## Tests and Coverage

- `frontend/src/components/settings/AISettingsPage.test.jsx`
- `backend/tests/test_ai_settings_api.py`
- `backend/tests/test_ai_runtime_settings_service.py`
- `backend/tests/test_llm_client.py`

## Known Gaps or Risks

- Runtime readiness depends on successful test fingerprints, but saved settings and test results are still easy to reason about separately in the UI.
- Secret lifecycle and auditability are sensitive.
- Provider aliases such as `claude`, custom Anthropic-compatible endpoints, and `openai_responses` web-search mode expand the capability matrix beyond a simple provider dropdown.
- Runtime settings persist secrets in the database and rely on masking for API responses.

## Optimization Backlog

- Persist and display provider/model/fingerprint drift warnings when saved settings no longer match the last successful test.
- Move API key storage to encrypted columns or an external secrets manager, with explicit audit events for secret changes.
- Show provider readiness in the dashboard, AI console, and settings page using one backend status contract.
- After saving a tested profile, refresh frontend runtime state so operators can see the exact effective provider and fingerprint.

## Follow-up Audit Questions

- Should settings save require test pass for changed profiles?
- Should secret updates be logged without exposing values?
- Should provider health be shown in the dashboard and AI console?
