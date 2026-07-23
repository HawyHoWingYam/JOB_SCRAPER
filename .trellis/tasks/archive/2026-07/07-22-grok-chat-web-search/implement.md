# Implementation plan: Krill Chat Completions and Company Web Search

## 1. Provider protocol and tests

- Add `openai_chat_completions` to the backend provider catalog and settings validation, keeping existing format values intact.
- Implement the Chat Completions transport, response-envelope validation, JSON parsing, operation-specific timeout/output budget, bounded transient retry, and sanitized diagnostics in `backend/app/ai/llm_client.py`.
- Reuse or deepen the Responses transport so Web Search can verify typed `web_search_call` plus a final message and send low reasoning effort with a 4096-token budget.
- Add focused backend unit tests for:
  - Chat endpoint, headers, messages, budget, timeout, and content extraction;
  - successful JSON parsing;
  - `{}`, error envelope, incomplete read, missing choice/message, malformed/truncated JSON;
  - non-retryable contract/output errors and bounded transient retries;
  - Responses Web Search payload and typed-output verification;
  - absence of secrets/prompts/full bodies in diagnostics.

## 2. Profile tests and persisted search capability

- Add Company Web Search probe metadata to the runtime settings model and Alembic migration.
- Extend runtime settings serialization/fingerprint handling so profile changes invalidate the previous search result.
- Replace the Job `OK` probe with representative structured JSON validation.
- Make the Company test report and persist ordinary health separately from Web Search health.
- Expose `web_search.available` and its actionable reason in Company runtime status/capabilities.
- Update AI Settings tests for successful, failed, unsupported, and stale-fingerprint search probes and for the new custom API format option.

## 3. Persist Company run intent

- Add `company_enrichment_runs.web_search_enabled` with a database default/backfill of `false`.
- Add the field to the SQLAlchemy model, API request schema, run response schema/serializer, and run creation service.
- Keep omitted request bodies backward-compatible with `false`.
- Reject a requested search run with HTTP 409 when current capability is unavailable.
- Ensure returning an existing active run preserves and reports that run's original mode.
- Pass the persisted flag through background execution and startup recovery.
- Add backend tests for default-off creation, enabled creation, capability rejection, active-run behavior, serialization, persistence, and recovery.

## 4. Make Company search explicit

- Change Company Enrichment service methods to accept `web_search_enabled=False` explicitly.
- Remove automatic search derived solely from `supports_web_search()`.
- Use ordinary generation when false and Responses Web Search when true.
- Keep the missing-description target query unchanged and persist only `Company.ai_description`.
- Propagate sanitized search failures to the run item without fallback.
- Add service/run tests proving disabled runs never search, enabled runs do search, failures remain failures, and existing descriptions are not globally overwritten.

## 5. Add the Companies UI control

- Load the stable Company Web Search capability on the Companies page/hook.
- Add a default-off Company-only switch near the global run button.
- Disable it with the backend reason when unavailable or while an active run exists.
- POST the explicit boolean and display the persisted active-run mode.
- Preserve the existing "missing descriptions only" explanation.
- Extend `CompaniesPage.test.jsx` for default-off, enabled POST, unavailable reason, stale/failed probe, active-run mode, omitted legacy capability, and unchanged targeting text.

## 6. Verification and rollout check

Run targeted checks first, then the package gates:

```bash
cd backend && pytest tests/test_llm_client.py tests/test_ai_settings.py tests/test_company_enrichment.py
cd backend && pytest
cd frontend && npm test -- src/components/companies/CompaniesPage.test.jsx src/components/settings/AISettingsPage.test.jsx
cd frontend && npm test
cd frontend && npm run build
```

Then perform sanitized live checks using the configured Krill profile without printing the key:

1. representative Job JSON probe through Chat Completions;
2. Company ordinary probe with search disabled;
3. Company Responses Web Search probe confirming a typed search call and final answer;
4. one small persisted Company run in each mode;
5. inspect logs for diagnostic usefulness and absence of secrets/prompt/search content.

## Risk and rollback points

- Migration: verify existing run rows read `web_search_enabled=false` and both Alembic upgrade/downgrade paths work.
- Provider selection: do not reinterpret existing `openai_responses`; rollback is a settings selection change.
- Capability state: fail closed when status is absent, stale, or inconsistent.
- Batch cost: keep the search toggle off during rollout until the small enabled run succeeds.
- Error hygiene: block release if any test captures authorization headers, prompts, complete provider bodies, citations, or webpage content.

## Verification notes

- Authenticated sanitized probes passed for Job Chat JSON generation, Company
  ordinary Chat generation, and Company Responses Web Search with a typed
  `web_search_call` and final message.
- No persisted global Company run was started during rollout verification.
  The current global endpoint has no bounded item limit and would process every
  company with a missing description, so invoking it would exceed the intended
  probe/smoke-test scope.
