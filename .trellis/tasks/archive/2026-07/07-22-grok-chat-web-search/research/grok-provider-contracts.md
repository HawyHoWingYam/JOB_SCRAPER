# Grok 4.5 / Krill provider contract research

## xAI first-party contract

* [Responses API text generation](https://docs.x.ai/developers/model-capabilities/text/generate-text) documents `POST https://api.x.ai/v1/responses` (and SDK `client.responses.create`) with `model`, `input` (string or role/content items), optional `stream`; responses expose `output_text` and structured output items. Grok 4.5 reasoning examples use long HTTP timeout (the page explicitly shows `httpx.Timeout(3600.0)`).
* [Reasoning](https://docs.x.ai/docs/guides/reasoning) identifies Grok 4.5 as a reasoning model and exposes `reasoning_effort` (effort level parameter). Reasoning can produce analysis/reasoning output items in Responses; clients should not assume only a single message content string.
* [Structured outputs](https://docs.x.ai/docs/guides/structured-outputs): primary contract is `response_format: {type: "json_schema", json_schema: {name, schema, strict: true}}` (JSON mode is also described). Tool-call arguments are always strict JSON-schema-conforming (`strict` implicitly true). This is the server contract, versus prompt-only “return JSON”.
* [Web search tool](https://docs.x.ai/developers/tools/web-search): Responses API tool declaration is `{ "type": "web_search" }`; SDK equivalent `tools=[web_search()]`; optional `allowed_domains` (example `web_search(allowed_domains=["grokipedia.com"])`). Responses include citations/sources (JS example destructures `sources`). Page’s support matrix explicitly lists xAI SDK and OpenAI Responses API; the tool is supported by Responses-compatible SDKs. Search is therefore a server-side tool, not a Chat Completions message field.
* [Chat Completions API](https://docs.x.ai/docs/api-reference#chat-completions) is OpenAI-compatible (`POST /v1/chat/completions`, `model`, `messages`, sampling params, `response_format` for JSON schema). The web-search documentation’s support matrix does **not** list Chat Completions for hosted `web_search`; use Responses for native search. Verify model availability/limits against [models](https://docs.x.ai/docs/models).

## Krill (`api.krill-ai.com`) evidence

Public unauthenticated probing found only `GET https://api.krill-ai.com/v1/models` returning HTTP 401 JSON `{"error":{"message":"missing Authorization","type":"unauthorized_error"},"type":"error"}`. `https://api.krill-ai.com/docs`, `/openapi.json`, and `/v1` returned Cloudflare HTTP 520. No publicly retrievable Krill documentation or tutorial was found in the endpoint itself; consequently there is no first-party evidence that Krill exposes Grok 4.5 or forwards xAI hosted `web_search`. Treat any claim of support as unverified until Krill supplies an authenticated OpenAPI/docs page and a working request example. The only defensible protocol statement is that `/v1/models` resembles an OpenAI-style route; it does not establish Chat Completions, Responses, or tool support.

### Authenticated capability probe (2026-07-22)

A minimal probe used the already configured Krill credential without printing the secret or sending job data:

* `POST /v1/chat/completions` with `grok-4.5` and no tools returned HTTP 200 in 1.73 seconds, model `grok-4.5-build-free`, and `choices[0].message.content = "KRILL_CHAT_OK"`. Basic Chat Completions is supported.
* The same Chat Completions endpoint with `tools: [{"type":"web_search"}]` returned HTTP 400 `invalid_request_error`. Krill does not accept the xAI hosted-search tool through Chat Completions using this contract.
* `POST /v1/responses` with `tools: [{"type":"web_search"}]`, `reasoning.effort = low`, and `max_output_tokens = 4096` returned HTTP 200 in 7.25 seconds. Its typed output contained `reasoning`, two `web_search_call` items, and a final `message` citing the requested xAI documentation URL. Krill does support hosted Grok web search through Responses.
* A second Responses probe combined the same web-search tool with strict `text.format.type = json_schema`. It returned HTTP 200 in 7.55 seconds with `reasoning`, `web_search_call`, and a final message whose text parsed as the requested JSON object. Krill therefore supports the contract needed for structured web-assisted enrichment.

These results supersede the earlier unauthenticated uncertainty for this configured profile. They do not prove that every Krill model or future relay version supports the same capabilities, so runtime probing remains necessary.

## Repository comparison (evidence)

`OpenAIResponsesClient` is selected only when `custom_api_format == "openai_responses"` ([llm_client.py:793-806](../../../backend/app/ai/llm_client.py#L793-L806)). It posts to `${base_url}/responses`, payload `{model,input,stream:false,max_output_tokens}` and, when requested, `tools:[{type:"web_search"}]` ([llm_client.py:539-591](../../../backend/app/ai/llm_client.py#L539-L591)). Thus the local payload is close to xAI Responses web-search shape, but omits xAI structured `response_format` and `reasoning_effort`; JSON extraction relies on a prompt and post-hoc parsing ([llm_client.py:609-616](../../../backend/app/ai/llm_client.py#L609-L616)).

Custom provider settings require key/model/base URL/api format ([ai_runtime_settings_service.py:39-45](../../../backend/app/services/ai_runtime_settings_service.py#L39-L45)); there is no field for reasoning effort, response schema, or search-domain filters. Runtime status reports `supports_web_search` from the instantiated client ([llm_client.py:1092-1097](../../../backend/app/ai/llm_client.py#L1092-L1097)), so a Krill endpoint selected as Responses is advertised as search-capable solely by client class, not by an upstream capability probe.

## Risks and options

1. **Compatibility risk:** This configured Krill profile supports basic Chat Completions and Responses-based hosted web search, but rejects the same hosted-search tool on Chat Completions. Route operations by verified protocol and do not report `supports_web_search=true` for another profile until a real tool call returns a typed `web_search_call` plus a final message.
2. **Schema risk:** `JobInsightExtractor` asks for JSON in prose and parses it; xAI structured outputs can enforce schema. Add schema plumbing (`response_format`) and validate the returned parsed object, retaining prompt fallback for providers without support.
3. **Reasoning/latency risk:** Grok 4.5 reasoning may require `reasoning_effort` and long timeouts; current web-search timeout is 120 s ([llm_client.py:48-49,581-585](../../../backend/app/ai/llm_client.py#L48-L585)), below xAI’s documented 3600 s example. Make timeout and effort configurable.
4. **Protocol option supported by evidence:** Use Krill Chat Completions for ordinary enrichment and Krill Responses for explicitly requested web-assisted enrichment, with strict JSON schema, low reasoning effort, larger output budget, longer timeout, and an authenticated capability gate.
