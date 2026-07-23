# Company Enrichment Run and Krill Web Search Contracts

## 1. Scope / Trigger

Use this contract when changing custom LLM transports, AI profile tests,
Company runtime capabilities, Company Enrichment run creation/execution, or the
Companies Web Search control.

The configured Krill profile has two operation-specific contracts. Ordinary
Job and Company generation uses OpenAI-compatible Chat Completions. Explicit
Company Web Search uses OpenAI-compatible Responses with the native search
tool. Adapter support alone is not evidence that the configured relay accepts
search; availability requires a successful probe for the current profile
fingerprint.

Job Enrichment never requests or exposes Web Search.

## 2. Signatures

Provider format and operations:

```text
custom_api_format = "openai_chat_completions"
POST {custom_base_url}/chat/completions
POST {custom_base_url}/responses

LLMClient.generate(prompt, web_search=False) -> str
LLMClient.generate_json(prompt, web_search=False) -> dict
LLMClient.probe_web_search(prompt) -> {ok, output_types}
```

Company run API and service:

```http
POST /api/v1/companies/enrichment-runs
Content-Type: application/json

{"web_search_enabled": false}
```

```python
CompanyEnrichmentRunService.create_pending_run(
    *, web_search_enabled: bool = False
) -> CompanyEnrichmentRun | None

CompanyEnrichmentService.enrich_company_description(
    company,
    db,
    force: bool = False,
    web_search_enabled: bool = False,
) -> dict
```

Persisted columns:

```text
company_enrichment_runs.web_search_enabled BOOLEAN NOT NULL DEFAULT FALSE
app_runtime_settings.companies_web_search_last_test_status VARCHAR(32) NULL
app_runtime_settings.companies_web_search_last_tested_at TIMESTAMP NULL
app_runtime_settings.companies_web_search_last_test_error TEXT NULL
app_runtime_settings.companies_web_search_last_test_latency_ms INTEGER NULL
app_runtime_settings.companies_web_search_last_test_fingerprint VARCHAR(128) NULL
```

## 3. Contracts

### Provider routing

- Ordinary `openai_chat_completions` calls send `messages`, use
  `/chat/completions`, allow 4096 output tokens, and use a 120-second timeout.
- Explicit `web_search=True` delegates through the same profile credentials to
  `/responses`, sends `tools: [{"type": "web_search"}]`, sets
  `reasoning.effort="low"`, allows 4096 output tokens, and uses a 180-second
  timeout.
- Custom operations make at most two total attempts and retry only transport
  timeouts/connections, HTTP 429, or HTTP 5xx failures.
- Empty, malformed, truncated, non-object, missing-final-message, unsupported
  tool, and invalid JSON results are non-retryable contract failures.
- A successful search probe contains both a typed `web_search_call` output item
  and non-empty final message text.

### Capability and run intent

- The Company profile test records ordinary model health separately from Web
  Search health. A failed or unsupported search test does not make ordinary
  Company generation unavailable.
- `ai.companies.web_search.available` is true only when the Company profile is
  ready, the search status is `passed`, and the stored search fingerprint
  exactly matches the current Company profile fingerprint.
- Missing, failed, unsupported, or stale probe state fails closed and exposes a
  bounded actionable reason.
- `web_search_enabled` is per-run, explicit, persisted, and default-off. An
  existing active run is returned unchanged; a later request cannot alter its
  mode.
- A new `web_search_enabled=true` request returns HTTP 409 unless the current
  Company capability is available.
- Execution reads the persisted run flag. Disabled runs use ordinary
  generation; enabled runs search. Search failure fails the item and never
  falls back to an unlabeled ordinary description.
- Global Company runs select only non-deleted companies whose
  `ai_description` is null or blank. They persist only the final
  `Company.ai_description`; search calls, citations, result objects, and page
  content remain transient.

### Diagnostics

- Logs and persisted/API errors may include provider/operation, endpoint kind,
  status, content type/length, received length, request ID, latency, envelope
  shape, exception type, and body SHA-256.
- A raw preview may show only safe shape information such as `{}`, `[]`, JSON
  top-level keys/count, or non-JSON byte length.
- Never include credentials, authorization headers, prompts, full job/company
  text, model output text, provider error bodies, citations, or webpage content.

## 4. Validation & Error Matrix

| Condition | Required result |
|---|---|
| Job profile ordinary generation | Chat Completions; no search tool |
| Company run omits `web_search_enabled` | Persist and return `false` |
| Company run requests search with current passed probe | Persist `true`; use Responses search during execution |
| Company search probe is absent, failed, unsupported, or stale | Capability unavailable; requested run returns 409 |
| Company ordinary probe passes but search probe fails | Ordinary Company generation remains ready |
| Active run exists and new request uses a different mode | Return active run's persisted mode unchanged |
| Search-enabled item gets timeout/connection/429/5xx | Retry once, then fail item if still unsuccessful |
| Search-enabled item gets 400, malformed envelope, missing final text, or invalid JSON | Fail immediately; no fallback |
| Chat response is `{}` or lacks `choices[0].message.content` | Non-retryable shape failure with safe shape/hash diagnostics |
| SSE event is malformed or lacks a terminal event after deltas | Non-retryable shape failure; never accept partial text |
| Company already has an AI description in a global run | Exclude from the run; do not overwrite |

## 5. Good / Base / Bad Cases

- Good: the Company profile's current fingerprint passed a real Responses
  search probe; the operator explicitly checks Web Search; the run persists
  `true` and stores only the final description.
- Base: the operator leaves the checkbox off; Company generation uses Chat
  Completions and behaves like ordinary enrichment.
- Bad: infer search from `client.supports_web_search()` and automatically send
  every Company request to Responses. Local adapter support does not prove the
  relay accepts the operation and removes operator intent.
- Bad: catch a search error and silently call ordinary generation. The saved
  result would be labeled as searched when it was not.
- Bad: log `str(exc)` or an extracted response preview. Provider exceptions and
  outputs can echo prompts, authorization data, or searched content.

## 6. Tests Required

- Provider tests assert Chat/Responses endpoint routing, request shapes,
  budgets, timeouts, typed search output, and Job requests without tools.
- Regression tests cover `{}`, provider error envelopes, incomplete reads,
  bounded retry, malformed/truncated JSON, non-object envelopes, malformed or
  incomplete SSE, missing final messages, and invalid JSON without retry.
- Security tests assert keys, prompts, provider bodies, extracted text,
  citations, and webpage content are absent from exception messages and logs.
- Runtime settings tests assert passed/failed/unsupported search states and
  exact fingerprint invalidation without blocking ordinary Company readiness.
- API/service tests assert default false, 409 when unavailable, active-run mode
  precedence, persisted execution intent, missing-description-only targeting,
  no fallback/persistence on search failure, and migration upgrade/downgrade.
- Companies UI tests assert default-off, unavailable reason, explicit boolean
  POST, persisted active-run mode, and unchanged missing-description targeting
  text. Job surfaces must contain no Web Search control.
- Alembic checks assert revision `20260723_120000` is the single head and the
  development database is at that head before runtime smoke tests.

## 7. Wrong vs Correct

### Wrong

```python
if llm.supports_web_search():
    description = await llm.generate(prompt, web_search=True)
except Exception as exc:
    logger.warning("search failed: %s", exc)
    description = await llm.generate(prompt)
```

This auto-enables search, leaks raw exception details, and silently changes the
meaning of the persisted result.

### Correct

```python
description = await llm.generate(
    prompt,
    web_search=bool(run.web_search_enabled),
)
```

Create the run only after the current-fingerprint capability gate passes. Let a
search failure fail the item, and record only bounded exception type/status and
response shape/hash diagnostics.
