# Design: Krill Chat Completions and Company Web Search

## Design summary

Introduce an OpenAI-compatible Chat Completions custom format whose ordinary path uses `/chat/completions` and whose explicitly requested search path delegates to a Responses transport using the same base URL, key, and model. Persist the Company run's opt-in flag, gate that flag on a separately persisted upstream capability probe, and keep all search material transient.

The new path is selected explicitly in AI Settings. Existing `anthropic` and `openai_responses` formats are not reinterpreted or automatically migrated.

## Boundaries

### Provider transport

`backend/app/ai/llm_client.py` owns protocol selection, parsing, retries, and sanitized response diagnostics.

- Add `openai_chat_completions` to the custom API format catalog.
- Add an `OpenAIChatCompletionsClient` for ordinary `generate` and `generate_json` calls:
  - `POST {base_url}/chat/completions`;
  - `model`, `messages`, and a 4096-token default output budget;
  - extract only `choices[0].message.content` after validating the envelope;
  - reject `web_search=True` unless the client is using its explicit Responses companion path.
- The same client may delegate `web_search=True` and `probe_web_search()` to `OpenAIResponsesClient` constructed with the same credentials. This is a local contract capability, not proof that an arbitrary relay supports it.
- Preserve the existing standalone `OpenAIResponsesClient` and Anthropic client behavior.

This keeps endpoint knowledge inside the provider module. Job and Company services continue to call the `LLMClient` interface and do not build provider payloads.

### Capability probe and runtime status

The current `supports_web_search()` method means only that the local adapter knows how to attempt the contract. Availability must additionally require a successful upstream probe for the current Company profile fingerprint.

Add a client probe operation that retains response-envelope metadata long enough to verify:

1. the HTTP request succeeded;
2. at least one typed `web_search_call` occurred;
3. a non-empty final message was extractable.

Persist Company search test metadata separately from the ordinary Company profile result in `app_runtime_settings`:

- status (`passed`, `failed`, or `unsupported`);
- tested timestamp;
- sanitized error/reason;
- latency;
- configuration fingerprint.

Expose a stable runtime object, for example:

```json
{
  "web_search": {
    "available": true,
    "reason": null,
    "last_test_status": "passed",
    "last_tested_at": "...",
    "fingerprint_matches": true
  }
}
```

The ordinary Company test can pass while its search test fails. In that state Company Enrichment remains ready, while the search option is disabled. Any profile change makes `fingerprint_matches=false` and therefore `available=false` until retested.

For the Job profile, replace the trivial `OK`-only check with a representative `generate_json` probe containing several typed fields and enough output to exercise the parser. The probe must verify the parsed values rather than only HTTP 200.

### Company run contract

Add `web_search_enabled BOOLEAN NOT NULL DEFAULT FALSE` to `company_enrichment_runs` through Alembic and the SQLAlchemy model.

`POST /api/v1/companies/enrichment-runs` accepts an optional body:

```json
{"web_search_enabled": true}
```

Omitting the body or field preserves backward compatibility and means `false`. Run serialization always returns the persisted flag.

Creation rules:

- an existing active run is returned unchanged; the new request cannot mutate its mode;
- `true` is accepted only when the current Company search capability is available;
- unavailable search returns HTTP 409 with the stored actionable reason;
- target selection remains the existing missing-description query.

The run service passes the persisted flag into every item execution. Recovery reads it from the run row, so a process restart cannot lose the operator's choice.

### Company generation

Change `CompanyEnrichmentService` from implicit capability-driven search to explicit intent:

```text
generate company description(company, web_search_enabled=false)
```

- `false`: ordinary generation with no search tool and no search-specific prompt claim;
- `true`: Responses Web Search through the provider client;
- upstream search failure: item fails; no ordinary fallback;
- success: strip and persist only the final description string.

The prompt may instruct the model to use public sources to verify company identity, sector, products, and location, but should not ask it to return citations because citations are intentionally not persisted.

### Companies UI

Add a default-off checkbox or switch beside the global Company Enrichment action.

- Render it only on the Companies surface, never on Job Enrichment.
- Disable it while an active run exists.
- Enable it only when `company_runtime_status.web_search.available` is true.
- When unavailable, show the backend reason and direct the operator to test the Company profile in AI Settings.
- Send `{web_search_enabled: boolean}` when creating the run.
- Display the mode reported by an active run rather than the local draft toggle.

The global-run hint continues to say that only companies without descriptions are targeted.

## Failure and retry policy

- Ordinary Chat Completions: 120-second request timeout, 4096 output tokens, at most two total attempts for transient timeout/connection/429/5xx failures.
- Responses Web Search: `reasoning.effort=low`, 4096 output tokens, 180-second request timeout, at most two total attempts for the same transient classes.
- No retry for 4xx contract rejection (other than 429), unsupported tool, malformed envelope, missing final message, empty `{}`, or invalid JSON.
- Preserve the configured Job and Company batch concurrency values; do not add search-specific fan-out.

These defaults are intentionally bounded. They remove the observed 60-second/1024-token bottleneck without adopting the one-hour timeout shown in generic first-party examples.

## Sanitized diagnostics

Create one response-diagnostic shape used by both transports:

- provider/operation and endpoint kind, not the API key or full URL query;
- HTTP status, content type, declared/received length, request ID, and elapsed time;
- envelope shape such as choice count or output item types;
- bounded preview suitable for recognizing `{}` or an error envelope;
- SHA-256 of the received body for correlation.

Never log request messages, authorization headers, full job/company prompts, fetched source content, citations, or unbounded provider bodies. Item error messages receive a shorter sanitized summary; detailed metadata goes to application logs.

## Data and compatibility

- One Alembic migration adds the run flag and Company search-probe metadata with safe nullable/default handling for existing rows.
- Existing Company runs backfill to `false`.
- Existing settings remain valid. The operator selects `openai_chat_completions` for the configured Krill Job and Company profiles and reruns both tests; credentials remain unchanged.
- Existing pure Responses users can keep `openai_responses`.
- No search result or citation table is introduced.

## Rollout and rollback

1. Deploy schema and code.
2. Select the new format for the Krill Job profile, run the representative test, then run a small ordinary Job Enrichment sample.
3. Select/test the Company profile; confirm ordinary readiness and separate search availability.
4. Run a small Company batch with search disabled, then an explicitly enabled search batch.
5. Increase to normal batch size only after item errors and latency are acceptable.

Rollback disables the Company search control and restores the prior format selection. The additive columns can remain; old runs read as non-search. No persisted search material requires cleanup.

## Important trade-offs

- Persisting the run flag and probe result adds schema work, but prevents restart ambiguity and false capability advertising.
- A dual-protocol client is slightly deeper than two unrelated settings profiles, but keeps one Krill credential/profile and routes by operation exactly as the authenticated probes require.
- Explicit failure lowers completion rate during relay incidents, but preserves the truth that a search-enabled result was actually searched.
