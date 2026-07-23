# Support Grok chat completions and company web search

## Goal

Make ordinary Job Enrichment reliable with the configured Krill relay and Grok 4.5, while allowing an operator to explicitly enable Web Search only for Company Enrichment runs that generate missing `Company.ai_description` values.

## Background

- The configured custom profiles use `grok-4.5`, `https://api.krill-ai.com/v1`, and currently select the `openai_responses` adapter.
- Krill's supplied integration example uses `POST /v1/chat/completions` with `messages` and returns `choices[0].message.content`.
- Run `4e5b991d-21c6-4557-9e8d-0639783ea34a` completed with 31 successes and 493 failures out of 524 items. The failures comprised 466 empty `{}` responses, 19 incomplete chunked reads, 6 provider response-body decoding errors, and 2 malformed or missing-final-message responses.
- The failing ordinary enrichment path used Responses with a 60-second timeout, a 1024-token output budget, and no explicit low reasoning effort. This could return reasoning without a final message, truncate output, or time out.
- Authenticated sanitized probes against the configured Krill profile established the actual contract:
  - ordinary `/chat/completions` succeeds;
  - Chat Completions rejects `tools: [{"type":"web_search"}]` with HTTP 400;
  - `/responses` accepts the Web Search tool and returns typed reasoning, `web_search_call`, and final message output;
  - Responses Web Search combined with strict JSON Schema returns parseable structured JSON.
- Job and Company enrichment already use distinct LLM profile scopes. Job Enrichment does not request Web Search. Company Enrichment builds its description prompt from company metadata and up to five recent jobs, then persists only `Company.ai_description`.
- The current Company Enrichment service automatically searches whenever the selected local client class claims support. That class-level claim does not prove that the configured upstream relay accepted a real search request.

## Requirements

### R1 — Route ordinary enrichment through Chat Completions

- Add an OpenAI-compatible Chat Completions custom API format that uses the configured base URL, key, and model.
- Job Enrichment must never include a search tool. When the configured Krill profile selects the new format, its ordinary requests must use `/chat/completions`.
- Company Enrichment with Web Search disabled must also use ordinary Chat Completions when this format is selected.
- Existing custom Anthropic and OpenAI Responses formats must remain compatible and retain their current routing.
- The corrected path must use a sufficiently large output budget and timeout for Grok 4.5, and must distinguish retryable transport/provider failures from non-retryable protocol or output-shape failures.

### R2 — Restrict Web Search to explicit Company runs

- Web Search belongs exclusively to Company Enrichment. Job Enrichment must not expose, accept, or invoke it.
- Each global Company Enrichment run must have a `web_search_enabled` option that defaults to `false` and is persisted with the run.
- Only a run explicitly created with `web_search_enabled=true` may call Krill `/responses` with `tools: [{"type":"web_search"}]`.
- Search results are transient model context used only to improve the final company description. Persist only `Company.ai_description`; do not separately persist citations, search results, fetched excerpts, or raw webpage content.
- The global run continues to select only companies whose description is missing. Enabling search must not overwrite existing descriptions. Replacement requires a separate explicit re-generation action.

### R3 — Gate search on a real upstream capability probe

- Testing the Company profile must separately report ordinary generation health and Web Search health.
- Web Search is available only when a representative authenticated upstream search probe for the current profile fingerprint succeeds and returns both a search call and a final answer.
- A failed or unsupported search probe must not block ordinary Company Enrichment, but it must disable the Web Search run option and expose an actionable reason.
- Changing the Company profile invalidates the prior search capability result until the new fingerprint is tested successfully.
- The feature must continue using the configured Krill relay and must not require or introduce a direct xAI API key.

### R4 — Fail explicitly and preserve scope boundaries

- If an enabled Web Search request fails during execution, mark that company item failed with an actionable, sanitized error. Do not silently fall back to ordinary generation.
- Web Search must not alter any Job Enrichment input or output, including taxonomy, skills, experience, or other governed job data.
- An active run's persisted mode is authoritative. A later create request must not silently change the mode of an already active run.

### R5 — Strengthen validation and diagnostics

- The settings test for the Job profile must exercise representative structured JSON generation, not only a short plain-text `OK` response.
- Capture sanitized response diagnostics sufficient to distinguish HTTP/provider errors, body-decoding or incomplete-read failures, protocol mismatch, missing final output, invalid JSON, and truncation.
- Diagnostics may include status, content type and length, request ID, latency, response item/choice shape, a bounded safe preview, and a hash. They must not include credentials, request prompts, full job descriptions, fetched webpage content, or unbounded provider bodies.
- Retries must be bounded and apply only to transient timeouts, connection failures, rate limits, and 5xx responses. Contract errors, unsupported tools, missing final messages, and invalid JSON must fail without retry loops.
- Preserve the existing configurable Company Enrichment concurrency; enabling search must not silently increase it.

## Acceptance Criteria

- [ ] AC1 (R1): Selecting the new Chat Completions format sends ordinary generation to `/chat/completions`, parses `choices[0].message.content`, and produces valid enrichment JSON.
- [ ] AC2 (R1): Job Enrichment never sends a Web Search tool; the configured Krill profile can be switched and successfully tested on the new format without changing its base URL, key, or model; existing Anthropic and OpenAI Responses profiles retain their existing adapters.
- [ ] AC3 (R2): Company run creation accepts `web_search_enabled`, defaults it to `false` when omitted, persists it, returns it in run responses, and retains it across background execution or process recovery.
- [ ] AC4 (R2): Only a Company run with the persisted flag set to `true` sends a Web Search request through `/responses`; disabled runs use ordinary generation.
- [ ] AC5 (R2): Search-enabled global runs still target only missing descriptions and persist only the final `Company.ai_description`.
- [ ] AC6 (R3): The Companies UI shows a default-off Web Search control only for Company Enrichment, enables it only after the current profile fingerprint passes a real search probe, and otherwise shows the probe's reason.
- [ ] AC7 (R3): Ordinary Company Enrichment remains available when its model probe passes but its search probe fails; no direct xAI credential is required.
- [ ] AC8 (R4): A mid-run search failure fails the affected item visibly and never creates an unlabeled ordinary fallback description.
- [ ] AC9 (R4): Enabling Company Web Search cannot change any Job Enrichment request or output.
- [ ] AC10 (R5): A representative Job profile test exercises structured JSON generation and catches empty, malformed, truncated, or missing-final-output responses before a costly batch starts.
- [ ] AC11 (R5): Regression tests cover `{}`, provider error envelopes, incomplete response bodies, missing final messages, malformed or truncated JSON, successful Chat Completions output, and successful typed Responses Web Search output.
- [ ] AC12 (R5): Logs and persisted item errors expose bounded sanitized diagnostics without credentials, prompts, full job data, search results, or raw webpages.

## Out of Scope

- Switching away from Krill or purchasing direct xAI access.
- Retrying the already completed failed enrichment runs before the corrected profile passes its representative tests.
- Persisting citations, search result objects, webpage excerpts, or raw fetched content.
- Automatically rewriting existing company descriptions as part of a global run.
- Adding Web Search to Job Enrichment or allowing it to influence governed job data.
