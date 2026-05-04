# AI Runtime Settings Design

> Last updated: 2026-05-03

## Summary

Add a dedicated frontend settings page for AI Enrichment runtime controls. The page must let operators persist and update:

- AI enrichment run concurrency
- active LLM provider
- provider-specific API key
- provider-specific model
- provider-specific base URL / endpoint format where applicable

These settings must be stored in the database, survive backend restarts, and apply immediately to new AI enrichment work without requiring a service restart.

## Goals

- Replace `.env` as the only runtime control surface for AI enrichment settings.
- Let operators change AI runtime settings from the UI and persist them safely.
- Make new AI enrichment runs use the updated provider and concurrency immediately after save.
- Keep already-running enrichment runs stable and unaffected by mid-run settings changes.
- Expose enough runtime status in the UI to show whether the configured provider is actually active or degraded.

## Non-Goals

- Do not build a general-purpose platform settings framework.
- Do not change configuration for non-AI subsystems in this iteration.
- Do not hot-swap providers inside requests that are already in flight.
- Do not introduce multi-tenant or per-user settings.

## Current State

- Backend runtime configuration is loaded from `backend/app/config.py` via Pydantic settings and `.env`.
- AI provider selection and provider credentials are resolved directly from the global `settings` object in `backend/app/ai/llm_client.py`.
- The active LLM client is cached as a singleton and only changes when process state is reset.
- AI enrichment run concurrency is currently read from `settings.ai_enrichment_run_concurrency` when a run starts.
- The frontend has no real settings route yet. The sidebar footer shows a `Settings` button, but it is not wired to a view.

## Proposed User Experience

### Navigation

- Reuse the existing sidebar footer `Settings` entry.
- Route that entry to a new dedicated page, not a modal and not a panel inside the AI Enrichment console.

### Settings Page Structure

The page contains two main sections:

1. `AI Runtime`
   - active provider selector
   - provider-specific fields
   - runtime status summary
   - degraded/fallback status if applicable

2. `AI Enrichment Throughput`
   - integer concurrency control
   - explanatory note that the setting affects new runs only

### Provider Form Presentation

Use provider-specific field groups instead of a universal mega-form.

- `gemini`
  - API key
  - model
- `anthropic` / `claude`
  - API key
  - model
  - base URL
- `custom`
  - API key
  - model
  - base URL
  - API format
- `zhipu`
  - API key
- `mock`
  - no secret fields
  - show explanatory copy only

Only fields relevant to the selected provider are editable in the main form.

### Secret Field UX

- API keys are never returned to the browser in plaintext after persistence.
- The page shows:
  - whether a key exists
  - a masked preview
- Leaving the input blank means “preserve existing stored key”.
- Entering a value means “replace stored key”.
- The UI should clearly distinguish:
  - existing stored key present
  - new replacement key entered but not yet saved

### Save / Apply Behavior

When the operator clicks `Apply Settings`:

1. persist the configuration to the database
2. rebuild effective runtime settings
3. clear and rebuild the LLM client singleton if provider settings changed
4. return current runtime status
5. show success or failure inline on the page

Result semantics:

- new AI requests use the updated runtime settings immediately
- new AI enrichment runs use the updated concurrency immediately
- already-running enrichment runs continue with the settings they started with

## Persistence Design

### Storage Model

Use a singleton-style runtime settings table. One logical row holds the persisted operator-controlled AI runtime config.

Recommended table name:

- `app_runtime_settings`

Recommended fields:

- `id`
- `llm_provider`
- `ai_enrichment_run_concurrency`
- `anthropic_api_key`
- `anthropic_model`
- `anthropic_base_url`
- `gemini_api_key`
- `gemini_model`
- `custom_api_key`
- `custom_model`
- `custom_base_url`
- `custom_api_format`
- `zhipu_api_key`
- `updated_at`

This is intentionally narrow and AI-specific. It is not a generic JSON settings blob.

### Fallback Rules

Effective runtime settings resolve in this order:

1. persisted DB value
2. `.env` / Pydantic `settings` fallback

This allows:

- existing local setups to keep working before any operator saves config
- saved DB config to survive restart
- partially populated DB rows to inherit missing defaults from `.env`

## Runtime Reload Semantics

### Concurrency

- The run service reads effective concurrency when a run starts.
- A saved concurrency change affects only subsequent runs.
- No attempt is made to resize worker pools for runs already in progress.

### Provider and Credentials

- Saving provider-related settings invalidates the cached LLM client singleton.
- The next LLM-bound request rebuilds the client using effective runtime settings.
- The save endpoint should also attempt an eager rebuild so the page can report runtime readiness immediately.

### Status Reporting

The backend should expose:

- configured provider
- actual active provider
- active model when available
- degraded status
- degradation reason

This allows the UI to distinguish:

- “saved successfully”
- “runtime loaded successfully”
- “saved but fell back to mock”

## Backend API Design

Add a dedicated settings API namespace:

- `GET /api/v1/settings/ai`
- `PUT /api/v1/settings/ai`

### GET Response

The GET response should include:

- persisted configuration in UI-safe shape
- effective configuration summary
- runtime status

UI-safe config means:

- no plaintext API keys
- include `has_api_key`
- include masked preview if available

### PUT Request

The PUT request should accept:

- selected provider
- provider-specific editable fields
- concurrency

Validation rules:

- concurrency must be a bounded positive integer
- required fields must be validated against the selected provider
- URL fields must be syntactically valid when provided
- unsupported provider values must be rejected

### PUT Response

The PUT response should include:

- saved config in UI-safe shape
- effective config summary
- runtime status after attempted reload
- validation or degradation errors when present

## Frontend Design

### New View

Add a dedicated `settings` view to the app-level view switcher.

Recommended new component:

- `frontend/src/components/settings/AISettingsPage.jsx`

### Page States

The page should explicitly render:

- initial loading
- successful load
- field validation errors
- save success
- save failure
- runtime degraded after save

### Copy Requirements

The page should clearly communicate:

- settings are persisted
- new runs use updated settings immediately
- active runs are not interrupted
- provider readiness may degrade to mock if credentials are invalid or missing

## Security Boundary

This iteration accepts database persistence for provider secrets in plaintext columns, but the system must never echo them back in plaintext through the API or UI.

Constraints:

- redact or mask secrets in responses
- do not log secret values
- do not send stored secret values back to the browser

Plaintext DB storage is an explicit iteration-1 tradeoff. The design must keep secret read/write handling isolated enough that encryption-at-rest can be added later without changing the API contract.

## Testing Requirements

### Backend

- migration coverage for the new settings table
- settings resolution precedence
- provider-specific validation
- secret masking in GET responses
- blank secret on PUT preserves existing stored key
- new secret on PUT replaces stored key
- runtime reload after save
- degraded status reporting when reload falls back
- concurrency update visible to subsequent AI runs

### Frontend

- settings navigation from sidebar
- initial page load
- provider-specific field rendering
- masked key display
- save flow
- validation error rendering
- degraded runtime banner rendering
- concurrency and provider update in a single submit

## Risks and Mitigations

### Risk: Provider reload partially succeeds

Mitigation:

- persist first
- reload second
- return runtime status explicitly
- never claim provider is active unless reload confirms it

### Risk: Ambiguity around existing API key handling

Mitigation:

- blank input means preserve
- explicit entered value means replace
- UI copy must say this clearly

### Risk: Future spread into general config management

Mitigation:

- keep this table and API narrow
- avoid generic JSON settings abstractions in this iteration

## Final Design Decisions

- settings are stored in the database
- `.env` remains fallback only
- sidebar `Settings` becomes a real page
- form fields are provider-specific
- save applies immediately to new runs and new requests only
- runtime status is shown separately from persisted config state
- provider secrets are stored in plaintext DB columns for this iteration, but never returned in plaintext
