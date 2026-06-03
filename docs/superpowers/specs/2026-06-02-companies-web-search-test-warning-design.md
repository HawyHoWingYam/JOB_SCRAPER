# Companies Web Search Test Warning Design

## Goal

Extend the `Companies` profile test flow so it verifies both model connectivity and web-search capability, while keeping runtime readiness gated by the model check only.

## Scope

- Modify `POST /api/v1/settings/ai/test` so `companies` probes return a separate web-search check.
- Keep the top-level test successful when model connectivity works, even if web search is unavailable.
- Surface the web-search result in `AISettingsPage` as an explicit warning or success detail.

## Non-Goals

- No new persisted runtime status tier.
- No change to `requires_test` / `is_ready` semantics.
- No change to company enrichment execution behavior outside clearer preflight visibility.

## Backend Design

- Keep the existing model probe as the primary pass/fail check.
- For `scope=companies`, append a second lightweight probe:
  - If the draft client reports `supports_web_search() == false`, do not send a web-search request. Return `attempted=false`, `supported=false`, `ok=false`, plus a human-readable warning.
  - If the draft client reports `supports_web_search() == true`, send a minimal `web_search=true` prompt and capture success or failure separately from the model probe.
- Return a richer payload:
  - `ok`
  - `scope`
  - `configured_provider`
  - `active_provider`
  - `model`
  - `latency_ms`
  - `config_fingerprint`
  - `model_check`
  - `web_search_check` for `companies`

## Frontend Design

- Keep the current test button and request shape.
- Update success feedback for `Companies` to show:
  - model check success
  - web-search success, unsupported warning, or probe-failed warning
- Unsupported or failed web-search checks should not render as a top-level error when the model check passed.

## Testing

- Backend:
  - `companies` + unsupported provider returns HTTP 200 with `ok=true` and `web_search_check.supported=false`
  - `companies` + supported provider returns HTTP 200 with `web_search_check.ok=true`
  - `companies` + supported provider but failing web-search probe returns HTTP 200 with warning details
- Frontend:
  - `Test Companies configuration` renders warning text when web search is unsupported
  - `Test Companies configuration` renders success text when web search passes
