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
POST /api/companies/enrichment-runs
Content-Type: application/json

{
  "mode": "generate_missing",
  "requested_limit": 50,
  "regenerate_confirmed": false,
  "web_search_enabled": false
}
```

```python
CompanyEnrichmentRunService.create_pending_run(
    *,
    mode: Literal["generate_missing", "regenerate_existing"],
    requested_limit: int,
    company_ids: list[UUID] | None = None,
    web_search_enabled: bool = False,
) -> CompanyEnrichmentRun | None

CompanyEnrichmentRunService.create_retry_run_from_failed_items(
    run_id: str,
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
company_enrichment_runs.mode VARCHAR(32) NOT NULL
company_enrichment_runs.requested_limit INTEGER NOT NULL
companies.website VARCHAR(2048) NULL
companies.ai_description_updated_at TIMESTAMP NULL
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
- `generate_missing` selects non-deleted Companies whose `ai_description` is
  null/blank, ordered by `created_at ASC, id ASC`.
- `regenerate_existing` selects non-deleted Companies with non-blank
  descriptions, ordered by `ai_description_updated_at ASC NULLS FIRST, id ASC`,
  and requires `regenerate_confirmed=true`.
- `requested_limit` is a positive operator-entered quantity with no product
  maximum. The run freezes `min(requested_limit, eligible_count)` item IDs;
  runtime concurrency remains separately bounded.
- Run mode, requested limit, frozen IDs, and Web Search intent are persisted.
  Failed-item retry reuses only the original failed IDs with the original mode,
  limit, and Web Search intent; it never selects a replacement cohort.
- Successful Generate or Regenerate writes `Company.ai_description` and
  `ai_description_updated_at` together. Failed Regenerate preserves both old
  values. Search calls, citations, result objects, and page content remain transient.

### Diagnostics

- Logs and persisted/API errors may include provider/operation, endpoint kind,
  status, content type/length, received length, request ID, latency, envelope
  shape, exception type, and body SHA-256.
- A raw preview may show only safe shape information such as `{}`, `[]`, JSON
  top-level keys/count, or non-JSON byte length.
- AI profile configuration probes may return a bounded (maximum 512-character)
  `detail.error_message` for `ProfileRuntimeNotReadyError` and
  `LLMProfileNotReadyError`, because their messages contain only the profile
  scope and required setting/provider-format names. Do not pass arbitrary
  provider or transport exception text through this path; keep those errors
  behind `safe_llm_error_message` summaries.
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
| AI profile configuration probe rejects an incomplete draft | Return 422 with a bounded actionable `detail.error_message`; do not replace it with a generic exception-type summary |
| Active run exists and new request uses a different mode | Return active run's persisted mode unchanged |
| Search-enabled item gets timeout/connection/429/5xx | Retry once, then fail item if still unsuccessful |
| Search-enabled item gets 400, malformed envelope, missing final text, or invalid JSON | Fail immediately; no fallback |
| Chat response is `{}` or lacks `choices[0].message.content` | Non-retryable shape failure with safe shape/hash diagnostics |
| SSE event is malformed or lacks a terminal event after deltas | Non-retryable shape failure; never accept partial text |
| Company already has an AI description in a global run | Exclude from the run; do not overwrite |
| `requested_limit <= 0` or is not an integer | HTTP/Pydantic 422; create no run |
| Regenerate omits confirmation | HTTP/Pydantic 422; create no run |
| Requested quantity exceeds eligible count | Freeze every eligible Company; do not reject or cap to a product constant |
| Generate has no blank descriptions / Regenerate has no existing descriptions | Return `{status: "empty", run: null}` |
| Retry source run has no failed items | HTTP 400 |
| Regenerate item fails | Mark item failed; preserve its prior description and timestamp |

## 5. Good / Base / Bad Cases

- Good: the Company profile's current fingerprint passed a real Responses
  search probe; the operator explicitly checks Web Search; the run persists
  `true` and stores only the final description.
- Base: the operator leaves the checkbox off; Company generation uses Chat
  Completions and behaves like ordinary enrichment.
- Good: the operator requests 100,000 Generate items and 73 are eligible; the
  run persists `requested_limit=100000` and freezes the 73 oldest eligible IDs.
- Good: confirmed Regenerate processes the least recently generated Companies;
  a failed item keeps its previous description while successful items receive a new timestamp.
- Bad: infer search from `client.supports_web_search()` and automatically send
  every Company request to Responses. Local adapter support does not prove the
  relay accepts the operation and removes operator intent.
- Bad: catch a search error and silently call ordinary generation. The saved
  result would be labeled as searched when it was not.
- Bad: run `safe_llm_error_message` over a profile-readiness validation error
  and return only `LLM operation failed (error_type=ProfileRuntimeNotReadyError)`;
  the operator cannot tell which setting to correct.
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
- Settings API tests assert incomplete Job and Company profile probes preserve
  their bounded readiness diagnostic in the 422 `detail.error_message` field,
  while arbitrary provider failures remain summarized.
- API/service tests assert default false, 409 when unavailable, active-run mode
  precedence, persisted execution intent, deterministic Generate/Regenerate
  ordering, arbitrary positive limits, frozen identities, retry preservation,
  atomic description/timestamp writes, and no fallback/persistence on failure.
- Companies UI tests assert default-off, unavailable reason, explicit boolean
  POST, Mode and Run size payloads, no input maximum, Regenerate cancellation
  and confirmation, retry-failed action, and persisted active-run intent. Job
  surfaces must contain no Web Search control.
- Empty-schema bootstrap tests assert the Company enrichment tables and current
  columns are present in metadata; no in-place schema upgrade test exists.

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
company.ai_description = description
company.ai_description_updated_at = utc_now()
db.commit()
```

Create the run only after the current-fingerprint capability gate passes. Let a
search failure fail the item, and record only bounded exception type/status and
response shape/hash diagnostics.

For profile configuration tests, preserve only the typed readiness diagnostics:

```python
if isinstance(exc, (ProfileRuntimeNotReadyError, LLMProfileNotReadyError)):
    return bounded_message(str(exc), limit=512)
return safe_llm_error_message(exc)
```
