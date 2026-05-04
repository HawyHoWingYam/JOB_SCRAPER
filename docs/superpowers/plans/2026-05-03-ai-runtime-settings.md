# AI Runtime Settings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a persisted AI settings page that lets operators update enrichment concurrency and provider-specific runtime configuration from the UI, with changes applying immediately to new runs and new AI requests.

**Architecture:** Introduce a singleton database-backed runtime settings row plus a small resolver layer that merges persisted values with existing `.env` fallbacks. Route LLM client construction and enrichment concurrency through that resolver, expose a dedicated FastAPI settings API, and add a real frontend settings view wired from the existing sidebar footer.

**Tech Stack:** React 19 + Vite, FastAPI, SQLAlchemy ORM, Alembic, PostgreSQL, pytest, Vitest

---

## File Structure

**Create**

- `backend/app/models/app_runtime_settings.py`
- `backend/app/services/ai_runtime_settings_service.py`
- `backend/app/api/settings.py`
- `backend/alembic/versions/20260503_170000_add_app_runtime_settings.py`
- `backend/tests/test_ai_runtime_settings_service.py`
- `backend/tests/test_ai_settings_api.py`
- `frontend/src/components/settings/AISettingsPage.jsx`
- `frontend/src/components/settings/AISettingsPage.css`
- `frontend/src/components/settings/AISettingsPage.test.jsx`

**Modify**

- `backend/app/models/__init__.py`
- `backend/app/config.py`
- `backend/app/ai/llm_client.py`
- `backend/app/services/ai_enrichment_service.py`
- `backend/app/services/enrichment_run_service.py`
- `backend/app/api/__init__.py`
- `backend/app/main.py` only if route registration needs adjustment
- `frontend/src/App.jsx`
- `frontend/src/components/Sidebar.jsx`
- `frontend/src/components/Sidebar.test.jsx`

## Task 1: Persist AI Runtime Settings in the Database

**Files:**

- Create: `backend/app/models/app_runtime_settings.py`
- Create: `backend/alembic/versions/20260503_170000_add_app_runtime_settings.py`
- Modify: `backend/app/models/__init__.py`
- Test: `backend/tests/test_ai_runtime_settings_service.py`

- [ ] **Step 1: Write the failing tests**

Add tests that prove:

- the runtime settings row can be created and fetched
- missing fields are allowed so `.env` fallback remains possible
- secret fields are stored but not required for every provider
- a single logical row is used for runtime settings

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest backend/tests/test_ai_runtime_settings_service.py -q`

Expected: FAIL because the runtime settings model and migration do not exist yet.

- [ ] **Step 3: Add the model and migration**

Implement a singleton-style `AppRuntimeSettings` model with explicit columns for:

- `llm_provider`
- `ai_enrichment_run_concurrency`
- `anthropic_api_key`, `anthropic_model`, `anthropic_base_url`
- `gemini_api_key`, `gemini_model`
- `custom_api_key`, `custom_model`, `custom_base_url`, `custom_api_format`
- `zhipu_api_key`
- `updated_at`

Use one-row semantics in service logic instead of trying to enforce singleton behavior in the schema.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest backend/tests/test_ai_runtime_settings_service.py -q`

Expected: PASS for the model and persistence tests.

## Task 2: Build the Effective Runtime Settings Resolver

**Files:**

- Create: `backend/app/services/ai_runtime_settings_service.py`
- Modify: `backend/app/config.py`
- Test: `backend/tests/test_ai_runtime_settings_service.py`

- [ ] **Step 1: Write the failing tests**

Add tests that prove:

- persisted DB values override `.env` defaults
- empty DB fields fall back to existing `settings`
- blank secret update preserves the stored key
- masked secret previews are returned in a UI-safe payload
- provider-specific required fields are validated against the selected provider

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest backend/tests/test_ai_runtime_settings_service.py -q`

Expected: FAIL because no resolver or validation layer exists yet.

- [ ] **Step 3: Implement the runtime settings service**

Implement service responsibilities:

- fetch or initialize the singleton row
- merge persisted settings with `backend/app/config.py` fallback values
- expose UI-safe serialization with `has_api_key` and masked preview
- preserve stored keys when update payload leaves secret fields blank
- validate concurrency bounds and provider-specific required fields

Keep secret handling isolated in this service so encryption can be added later without changing API contracts.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest backend/tests/test_ai_runtime_settings_service.py -q`

Expected: PASS with resolver precedence, masking, and validation covered.

## Task 3: Make LLM Runtime Reloadable from Persisted Settings

**Files:**

- Modify: `backend/app/ai/llm_client.py`
- Test: `backend/tests/test_ai_runtime_settings_service.py`

- [ ] **Step 1: Write the failing tests**

Add tests that prove:

- provider/client construction reads effective settings from the runtime settings service
- resetting the cached client forces a rebuild from newly persisted config
- runtime status reports configured provider, active provider, model, degraded flag, and degradation reason

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest backend/tests/test_ai_runtime_settings_service.py -q`

Expected: FAIL because `llm_client.py` still reads directly from global Pydantic settings and caches only process-start values.

- [ ] **Step 3: Implement reloadable runtime resolution**

Refactor `backend/app/ai/llm_client.py` so:

- effective provider config comes from the runtime settings service, not directly from `settings`
- existing reset behavior is reusable from the settings update flow
- provider reload can be attempted eagerly after save
- runtime status distinguishes persisted config from active provider fallback behavior

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest backend/tests/test_ai_runtime_settings_service.py -q`

Expected: PASS for reload and status-reporting behavior.

## Task 4: Expose a Dedicated AI Settings API

**Files:**

- Create: `backend/app/api/settings.py`
- Modify: `backend/app/api/__init__.py`
- Test: `backend/tests/test_ai_settings_api.py`

- [ ] **Step 1: Write the failing tests**

Add API tests covering:

- `GET /api/v1/settings/ai`
- `PUT /api/v1/settings/ai`
- masked secret response behavior
- blank secret preserving previous stored key
- provider validation errors
- successful save plus runtime reload status
- degraded runtime status if reload falls back to mock

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest backend/tests/test_ai_settings_api.py -q`

Expected: FAIL because the settings router and endpoints do not exist yet.

- [ ] **Step 3: Implement the API**

Add:

- `GET /api/v1/settings/ai`
- `PUT /api/v1/settings/ai`

Response payload should include:

- persisted config in UI-safe shape
- effective config summary
- runtime status

On `PUT`, persist first, then attempt eager runtime reload, then return both persistence and runtime outcome.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest backend/tests/test_ai_settings_api.py -q`

Expected: PASS for both routes and all validation/status behavior.

## Task 5: Route Enrichment Runtime Through the New Resolver

**Files:**

- Modify: `backend/app/services/enrichment_run_service.py`
- Modify: `backend/app/services/ai_enrichment_service.py`
- Modify: `backend/tests/test_enrichment_run_service.py`

- [ ] **Step 1: Write the failing tests**

Add or extend tests that prove:

- new enrichment runs read concurrency from effective runtime settings instead of only `backend/app/config.py`
- provider changes affect new AI requests after reload
- already-running runs keep their original concurrency behavior

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest backend/tests/test_enrichment_run_service.py backend/tests/test_ai_runtime_settings_service.py -q`

Expected: FAIL because concurrency and provider resolution are not yet routed through persisted runtime settings.

- [ ] **Step 3: Implement runtime wiring**

Update the enrichment services so:

- run concurrency comes from the effective runtime settings resolver
- AI request paths use the reloadable LLM client behavior from Task 3
- the semantics remain: new runs pick up new settings, old runs stay stable

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest backend/tests/test_enrichment_run_service.py backend/tests/test_ai_runtime_settings_service.py -q`

Expected: PASS with no regression in the existing run-monitor behavior.

## Task 6: Add the Frontend Settings View and Navigation

**Files:**

- Create: `frontend/src/components/settings/AISettingsPage.jsx`
- Create: `frontend/src/components/settings/AISettingsPage.css`
- Modify: `frontend/src/App.jsx`
- Modify: `frontend/src/components/Sidebar.jsx`
- Test: `frontend/src/components/settings/AISettingsPage.test.jsx`
- Test: `frontend/src/components/Sidebar.test.jsx`

- [ ] **Step 1: Write the failing tests**

Add frontend tests covering:

- sidebar footer settings navigation opens a real settings page
- page loads settings from `GET /api/v1/settings/ai`
- provider-specific fields render correctly for the selected provider
- masked key state is shown without plaintext
- concurrency input renders and updates

- [ ] **Step 2: Run the tests to verify they fail**

Run: `npm test -- src/components/settings/AISettingsPage.test.jsx src/components/Sidebar.test.jsx`

Expected: FAIL because the settings page and navigation wiring do not exist yet.

- [ ] **Step 3: Build the page shell**

Implement a dedicated settings page that:

- fits the existing visual language
- has an `AI Runtime` section
- has an `AI Enrichment Throughput` section
- dynamically swaps field groups by selected provider
- clearly explains that blank secret fields preserve existing values

- [ ] **Step 4: Run the tests to verify they pass**

Run: `npm test -- src/components/settings/AISettingsPage.test.jsx src/components/Sidebar.test.jsx`

Expected: PASS for navigation and initial page rendering.

## Task 7: Implement Save Flow, Status Banners, and Degraded Runtime Feedback

**Files:**

- Modify: `frontend/src/components/settings/AISettingsPage.jsx`
- Modify: `frontend/src/components/settings/AISettingsPage.css`
- Test: `frontend/src/components/settings/AISettingsPage.test.jsx`

- [ ] **Step 1: Write the failing tests**

Add UI tests covering:

- successful save
- provider switch plus field update in one submit
- blank secret preserving existing key
- validation error rendering
- runtime degraded banner rendering
- updated runtime summary after save

- [ ] **Step 2: Run the tests to verify they fail**

Run: `npm test -- src/components/settings/AISettingsPage.test.jsx`

Expected: FAIL because submit handling, runtime status banners, and degraded feedback are not yet implemented.

- [ ] **Step 3: Implement the save flow**

Implement:

- `PUT /api/v1/settings/ai` submit handling
- inline success/error banners
- runtime status card showing configured provider, active provider, model, and degraded state
- “new runs only” copy for concurrency changes

- [ ] **Step 4: Run the tests to verify they pass**

Run: `npm test -- src/components/settings/AISettingsPage.test.jsx`

Expected: PASS for save flow, validation, and degraded runtime feedback.

## Task 8: Run Final Verification

**Files:**

- Test only

- [ ] **Step 1: Run backend verification**

Run: `pytest backend/tests/test_ai_runtime_settings_service.py backend/tests/test_ai_settings_api.py backend/tests/test_enrichment_run_service.py -q`

Expected: PASS

- [ ] **Step 2: Run frontend verification**

Run: `npm test -- src/components/settings/AISettingsPage.test.jsx src/components/Sidebar.test.jsx src/components/ai/AIEnrichmentPage.test.jsx`

Expected: PASS

- [ ] **Step 3: Run syntax/build sanity checks**

Run: `python -m py_compile backend/app/models/app_runtime_settings.py backend/app/services/ai_runtime_settings_service.py backend/app/api/settings.py backend/app/ai/llm_client.py`

Run: `npm run build`

Expected: backend compile succeeds, frontend build succeeds

## Acceptance Checklist

- A real settings page exists in the frontend
- AI runtime config is persisted in the database
- `.env` remains fallback only
- New runs use updated concurrency immediately
- New AI requests use updated provider settings immediately after save/reload
- Existing runs are not interrupted
- Provider secrets never return to the UI in plaintext
- Runtime degraded state is visible in the UI
