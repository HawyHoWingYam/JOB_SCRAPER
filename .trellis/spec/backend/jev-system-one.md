# Jev System One Settings and Bounded Runs

## Scenario: budgeted native System One decisions

### 1. Scope / Trigger

Use this contract whenever code configures Jev, sends a native System One
request, accounts for Jev allowance, exposes a bounded run, or renders Jev run
operations in the Settings UI. Jev is not an LLM chat-provider profile and must
not be routed through the existing chat/completions clients.

### 2. Signatures

HTTP interfaces:

```text
GET  /api/settings/ai
PUT  /api/settings/ai                  { ..., jev: JevSettingsUpdate }
GET  /api/jev/runs?limit=20
POST /api/jev/runs                     JevRunCreateRequest
GET  /api/jev/runs/{run_id}
POST /api/jev/runs/{run_id}/execute-next
POST /api/jev/runs/{run_id}/stop
POST /api/jev/runs/{run_id}/resume
POST /api/jev/runs/{run_id}/retry-failed
```

Owned database tables:

```text
jev_runtime_settings
jev_budget_reservations
jev_runs
jev_run_items
jev_run_attempts
```

Production Skill adoption also owns `jev_online_skill_classifications` and
`jev_skill_maintenance_batches`. Historical Skill backfill is represented by
ordinary `enrichment_runs` with `source_type="jev_skill_backfill"`; it must not
introduce another queue or bypass the enrichment outbox/worker.

The provider call is exactly `POST <configured-full-endpoint>` with a bearer
credential. Do not append `/v1/systemone` in the adapter.

### 3. Contracts

- Settings store `enabled`, full endpoint, model, masked secret state, integer
  microdollar allowance/rates/maximum request reservation, sample and question
  limits, concurrency, retry limit, timeout, and fixed-millis evidence and
  recommendation thresholds.
- Default cumulative allowance is `10_000_000` microdollars (USD 10). Spent and
  reserved amounts survive retries and process restarts. A Settings update may
  not lower allowance below `spent + reserved`.
- Blank `jev.api_key` preserves the saved secret. GET responses expose only
  `has_api_key` and `api_key_preview`; run snapshots store only a SHA-256 key
  fingerprint, never the credential.
- A run freezes endpoint, model, price bounds, work membership/order, rubric,
  retry/concurrency limits, thresholds, and key fingerprint. Later Settings
  edits affect only later runs.
- Every external attempt atomically reserves its configured positive
  `max_request_reservation_microdollars` before dispatch. Known input/output
  token rates reconcile validated usage in integer microdollars, rounded up:

  ```text
  ceil((input_tokens * input_rate + output_tokens * output_rate) / 1_000_000)
  ```

  An explicitly validated provider `usage.cost` in USD takes precedence and is
  rounded up to integer microdollars. Without provider cost or both verified
  rates, a successful request conservatively settles the full maximum.
  Transport ambiguity or a calculated charge above the maximum
  retains the reservation as `uncertain`; it is never silently released.
- Native request JSON is `{state, model, questions}`. Named questions use
  `noul`, `choice`, or `score`. Responses must return the exact question names
  and matching answer types, a model, bounded probabilities, non-negative token
  usage, and measured `latency_ms` in the persisted receipt. OpenRouter's
  documented `id`, `provider`, and `usage.cost` receipt fields are accepted and
  persisted when present; unrecognized fields remain schema errors.
- Reading Settings/run state and saving defaults never calls System One. Paid
  work starts only at the explicit `execute-next` seam (the UI smoke action
  first creates one bounded run, then explicitly executes its only item).
- The Settings page owns basic/advanced controls and run operations. It renders
  allowance as locally calculated guardrail data, not provider billing truth.
- Online Skill classification and historical backfill use the same dispatch
  builder for the input fingerprint. Backfill preview recomputes that exact
  fingerprint from frozen original candidate/evidence plus the current Job,
  taxonomy and runtime identity; a parallel approximation is forbidden.
- Job Detail and Candidate reads whitelist audit fields (`status`, model,
  request ID, reported cost and error code). They never expose credentials,
  endpoint configuration, full answers or evidence snapshots and never call the
  provider.
- Stronger-model Skill maintenance has a separate model and cumulative budget.
  Its scheduler performs a free eligibility check, persists recoverable work
  before dispatch, and allows at most one pending/running batch. SQLite
  timestamps read without `tzinfo` are interpreted as UTC before comparison.
- New Skill proposals remain a visible aggregate diff containing the frozen
  batch/taxonomy identity, candidate, parent Technology and both confidences.
  Approval is explicit; unresolved/conflicting proposals remain held.

### 4. Validation & Error Matrix

| Condition | Required behavior |
|---|---|
| Public non-HTTPS endpoint | Settings `422`; loopback HTTP is test/local only |
| Blank model, invalid limit/threshold/rate | Settings `422` with field location |
| Allowance below spent plus reserved | Settings `422`; ledger is unchanged |
| Disabled Jev, missing key, or missing max reservation | Run create `409`; no provider call |
| Duplicate active purpose or invalid work | Run create `422`; no provider call |
| Allowance reservation cannot fit | Execute `409` with `jev_allowance_exhausted` and remaining microdollars |
| Key changed after run creation | Execute `409`; frozen run is not silently rebound |
| Timeout/network/non-2xx | Item fails with secret-safe unavailable receipt; charge remains uncertain |
| Malformed JSON/schema or answer mismatch | Item fails as invalid; charge remains uncertain |
| Stop before dispatch | Pending items become cancelled; no new reservation |
| Resume non-cancelled run or retry beyond frozen limit | `409`; existing receipts remain unchanged |

### 5. Good / Base / Bad Cases

- **Good:** an operator saves masked settings, creates a bounded run, reserves
  allowance, receives typed answers plus usage/latency, settles actual priced
  usage, and sees the frozen model and remaining allowance in the UI.
- **Base:** Jev is disabled or unavailable. Existing deterministic Job/Skill
  behavior remains unchanged and read surfaces remain usable.
- **Bad:** page render, Settings save, retry, or process restart creates a new
  USD 10 pool or sends an unreserved request.
- **Bad:** treat token usage as a trustworthy dollar amount without configured
  rates, release a timeout reservation, return upstream bodies, or persist the
  bearer credential in run JSON/logs/test artifacts.

### 6. Tests Required

- Adapter unit tests assert exact endpoint/auth/body, all three answer types,
  usage, deterministic latency, bounded values, non-2xx, transport failure,
  malformed response, answer mismatch, and secret-safe diagnostics.
- Settings tests assert defaults, partial update, mask/blank-secret behavior,
  HTTPS/public-HTTP validation, allowance floor, and zero provider calls.
- Ledger/run tests assert atomic conditional reservation, exact integer
  settlement, exhaustion, idempotency, uncertain charges, frozen configuration,
  stable order, stop/resume/retry, retry limit, and no maximum/no dispatch.
- Route tests assert create/read/list/stop/resume/execute and structured budget
  exhaustion. The real HTTP integration test uses only a loopback fake server.
- Browser E2E uses an isolated backend database and loopback fake System One;
  assert save/reload, masked secret, exactly one provider request, typed receipt,
  usage, allowance change, and old-run frozen model after a Settings edit.
- Disposable PostgreSQL cutover rehearsal asserts all five Jev tables are
  excluded from retained artifacts and empty after rebuild/import/verification.

### 7. Wrong vs Correct

#### Wrong

```python
# Dispatch first, account later; a concurrent caller can overspend.
result = await client.evaluate(request)
settings.spent_microdollars += estimate(result.usage)
```

#### Correct

```python
reservation = ledger.reserve(attempt_key=attempt_key, microdollars=maximum)
result = await client.evaluate(request)
ledger.settle(reservation.id, actual_microdollars=priced_usage)
```

For ambiguous transport failure, call `ledger.mark_uncertain(...)`, not
`release(...)`. Only a request proven not to have been dispatched may release a
reservation.

## Scenario: offline source-preserving duplicate evaluation

### 1. Scope / Trigger

Use this contract before Jev can create a Suspected Duplicate Association.
Evaluation may read frozen Job evidence and embeddings, but it may not merge,
hide, delete, canonicalize, or otherwise mutate source Jobs.

### 2. Contracts

- Controlled fixtures use explicit construction, bilingual strata, immutable
  pair hashes, connected group splits, and the three outcomes
  `same_vacancy`, `different_vacancy`, and `insufficient`.
- Candidate generation is a deterministic symmetric union of per-Job lexical
  and embedding top-K neighbors. Candidate recall is scored separately from
  pair judging; omitted positives remain misses.
- Real export is PostgreSQL-only and begins `SET TRANSACTION READ ONLY`. Its
  artifact contains exactly `manifest.json`, `jobs.jsonl`,
  `candidate-pairs.jsonl`, and `policy.json`, with every content file SHA-256
  bound. Raw payloads, raw descriptions, contacts, credentials, and vectors are
  excluded.
- Each pair asks one bounded choice question. Unavailable, invalid,
  budget-skipped, and `insufficient` outcomes never become negative evidence.
- Frozen gates are candidate recall@10 `>= 0.95`, answered precision `>= 0.95`,
  positive recall `>= 0.80`, false-association rate `<= 0.02`, actionable
  coverage `>= 0.60`, technical failure `<= 0.05`, and option-order stability
  `>= 0.95`.
- Even when controlled gates pass, release remains `inconclusive` until real
  English and Traditional-Chinese slices have independent human reference
  labels. Model agreement and existing projections are not accuracy.

### 3. Tests Required

- Strict fixture hash/schema/group/strata tests.
- Pure symmetric/top-K/deterministic candidate and blocker-recall tests.
- PostgreSQL read-only, minimization, manifest tamper, and replay tests.
- Exact question/receipt/cost/credential-gate runner tests.
- Full-denominator metric tests for blocker misses, non-answers, low coverage,
  zero denominators, and option-order stability.

## Scenario: offline crawl-content quality evaluation

- Route deterministic WAF/IP block/terminal-unavailable evidence before Jev;
  do not spend model budget to rediscover source/runtime facts.
- Transport/parser failure and missing evidence are `insufficient`, not content
  negatives. Only structurally successful but semantically uncertain content is
  eligible for Jev.
- Real snapshots read `crawl_job_listings` in a PostgreSQL read-only transaction
  and emit only bounded visible excerpts, source/status metadata, and hashes.
  Raw payloads, response bodies, URLs, headers, cookies, auth state, challenge
  content, and contact details are forbidden.
- Evaluation may write only Jev run/attempt receipts and local artifacts. It may
  not invoke repair, retry, resume, reset, dispatch, browser-helper, event, or
  product-flag writes.
- One ambiguous provider failure retains its reservation, stops the sequence,
  and makes the quality result inconclusive; it is never retried implicitly or
  converted into a quality label.

## Scenario: offline bounded search relevance evaluation

- Freeze candidate membership and source-qualified identities before any Jev
  judgment. Candidate recall and reranking quality are separate metrics.
- A reranker may reorder only the bounded candidate set. It may not alter scope,
  structured filters, facets, totals, pagination/export membership, or applied
  scope.
- Search pages and exports must slice the same complete deterministic ordering;
  source identity is the final tie key in evaluation artifacts.
- Provider unavailable/invalid/budget failure returns the baseline order and
  remains a technical evaluation failure.
- Do not claim relevance improvement without a measured NDCG/MRR comparison on
  frozen held-out judgments. Provider ambiguity yields `inconclusive` and no
  additional paid request.

## Scenario: offline operational incident triage

- Normalize and cluster immutable event observations before model work. Preserve
  every event ID/count while removing URLs, credentials, and variable IDs from
  the model-visible symptom.
- Triage output is advisory only. It may not change deterministic issue class or
  severity and may not call retry, resume, cancel, reset, dismiss, browser, or
  event-write paths.
- Repeated-event compression alone is not a product gate. Release needs observed
  operator outcomes and review-time baselines to measure actionable recall,
  false-safe rate, coverage, stability, and time/cost reduction.
- Evidence selection, derived refresh, and provider routing remain deferred
  until each has a measured bottleneck and its own independent evaluation gate.

## Scenario: offline Skill evaluation before rollout

### 1. Scope / Trigger

Use this contract before allowing Jev to suggest governed Skill evidence or
Candidate decisions. Evaluation is read-only with respect to Jobs, Mentions,
Candidates, taxonomy, and governed facts. A passing evaluation authorizes only
an operator-confirmed review surface; it never authorizes automatic writes.

### 2. Signatures

The offline entry point is `backend/scripts/jev_skill_evaluation.py` with
`validate`, `plan`, `export-real`, `run`, and `report` commands. Controlled
fixtures are strict JSONL. Real artifacts contain exactly `manifest.json`,
`cases.jsonl`, and `taxonomy.json`. Paid observations bind the run ID, fixture
manifest hash, rubric/model identity, reservation receipt, typed outcome,
usage, latency, and safe error code.

### 3. Contracts

- Controlled development and held-out cases use explicit-answer construction,
  stable IDs/hashes, bilingual strata, and connected group IDs. A group may
  never occur in both splits.
- Real export is PostgreSQL-only and begins with `SET TRANSACTION READ ONLY`.
  It has a hard row cap, excludes `raw_data` and raw descriptions, strips HTML
  and contact details, and freezes taxonomy/case hashes in a verified manifest.
- Jobs connected through company identity or an exact normalized-description
  fingerprint share a group. Whole groups receive a temporal development or
  held-out assignment; row ratios may be uneven to preserve leakage safety.
- Existing AI projections are correlated `weak_reference` values, never human
  truth. A release decision additionally requires independently reviewed
  English and Traditional-Chinese real slices.
- Evidence support and Candidate recommendation are scored separately. Every
  eligible abstained, unavailable, invalid, and unresolved case stays in the
  coverage/error denominator. Reports include provenance/language/source
  strata, p50/p95 latency, tokens, and integer-microdollar spend.
- Frozen held-out gates are: evidence answered correctness `>= 0.90`, Candidate
  top-1 correctness `>= 0.85`, technical failure `<= 0.05`, actionable coverage
  `>= 0.60`, and option-reordering stability `>= 0.95`.
- `run` requires an explicit paid confirmation, a persistent state database,
  and a positive maximum request reservation. A technical or uncertain result
  stops the sequence. Process restart must not create a fresh USD 10 pool.

### 4. Validation & Error Matrix

| Condition | Required behavior |
|---|---|
| Fixture hash drift, duplicate ID, or group leakage | Reject before any provider request |
| Non-PostgreSQL real export | Reject; do not simulate read-only guarantees |
| Artifact file/hash/schema drift | Fail closed; do not score |
| Missing paid confirmation or maximum reservation | Reject with zero requests |
| HTTP/transport/schema failure | Persist safe unavailable/invalid receipt, retain uncertain reservation, stop |
| Missing controlled denominator or bilingual independent reference | Report `inconclusive`, never pass |
| Frozen controlled gate missed | Report `defer` |
| Every gate/reference requirement met | Report `proceed_limited_review` only |

### 5. Good / Base / Bad Cases

- **Good:** validate frozen artifacts, plan against the remaining cumulative
  allowance, pass one development smoke, run the bounded set, and emit a
  reproducible report without product-data writes.
- **Base:** credentials are invalid or independent references are absent. Keep
  current deterministic behavior and report `inconclusive`.
- **Bad:** call model agreement accuracy, omit abstentions/errors from a
  denominator, split duplicate/company-connected rows, or rerun after an
  ambiguous failure without accounting for the uncertain reservation.

### 6. Tests Required

- Fixture tests cover schema/hash drift, group leakage, bilingual/scenario
  coverage, and reordered options.
- Corpus tests cover PostgreSQL enforcement, minimization, connected grouping,
  temporal split integrity, manifest hashes, and forbidden raw fields.
- Runner tests cover explicit bounded dispatch, observation bindings,
  cumulative allowance, stop-on-failure, idempotent resume, and secret safety.
- Metric tests cover zero denominators, unresolved/error retention, stability,
  provenance/language strata, latency percentiles, and proceed/defer outcomes.
- A live smoke uses the configured real endpoint only after local tests pass;
  invalid credentials end paid execution without retry.

### 7. Wrong vs Correct

#### Wrong

```python
accuracy = matching_answers / answered_answers  # correlated labels, dropped cases
```

#### Correct

```python
agreement = matching_answers / all_eligible_cases
reference_provenance = "existing_ai_projection"  # weak, not validated truth
```

## Scenario: production suspected-duplicate associations

### 1. Scope / Trigger

Use this contract when Jev evaluates whether two retained Source Jobs may be the
same concrete vacancy. This is an association workflow, never a Job merge,
canonicalization, suppression, deletion or source-identity rewrite.

### 2. Signatures

```text
GET  /api/jobs/{job_id}/duplicate-associations
POST /api/jobs/{job_id}/duplicate-associations/evaluate
POST /api/jobs/{job_id}/duplicate-associations/{association_id}/review
     Idempotency-Key: <1..255 chars>
     {"action":"confirm" | "reject"}
```

Owned storage is `jev_duplicate_associations`. Future-run Settings fields are
`duplicate_enabled`, `duplicate_candidate_limit` (1..10), and
`duplicate_corpus_limit` (2..1000). Product execution uses the existing online
model, online cumulative allowance and maximum-request reservation.

### 3. Contracts

- Candidate generation is a bounded lexical top-K over active Source Jobs and
  reuses the deterministic offline scorer. It does not use Related Jobs title
  deduplication and does not infer transitive clusters.
- Each pair is canonicalized by ordered `source_site:source_job_id` identities.
  Its evidence fingerprint binds both minimized snapshots and rubric version.
- The typed question has exactly `same_vacancy`, `different_vacancy`, and
  `insufficient`. Source text is evidence, never instructions.
- `same_vacancy` creates only `proposed`; a local operator explicitly confirms
  or rejects it. Neither action mutates either Job.
- `different_vacancy` is retained as a non-visible rejection. Insufficient,
  invalid, unavailable and over-budget outcomes never become an association.
- Job Detail reads only current-fingerprint `proposed` and `confirmed` rows.
  Changed/deleted Job evidence makes an old claim non-current without deleting
  its audit record.
- Review is domain-scoped idempotent and emits an append-only governance audit.
  Its replay JSON uses ISO timestamps, not native `datetime` objects.
- New production Jev integration tests and the Jev browser fixture use an
  isolated PostgreSQL database ending in `_test`; SQLite is not an accepted
  substitute for UUID, JSON, index, constraint or lock behavior.

### 4. Validation & Error Matrix

| Condition | Required behavior |
|---|---|
| Duplicate evaluation disabled | `409`, zero provider requests |
| Job missing/deleted or unsupported source | `404`/`422`, no run |
| No eligible pair or exact current receipt | Return zero new candidates, no paid request |
| Jev says same vacancy | Persist `proposed`; preserve both Jobs |
| Jev says different/insufficient | No visible association |
| Provider unavailable/invalid or budget exhausted | Preserve both Jobs; no confirm control |
| Evidence changes after a result | Old result is not returned as current; new fingerprint may run |
| Same idempotency key/same review | Replay first result and one effective mutation |
| Same idempotency key/different review | `409` conflict |
| Test database name lacks `_test` | Refuse before engine open, DDL or cleanup |

### 5. Good / Base / Bad Cases

- **Good:** Job Detail runs one bounded evaluation, displays the other Source
  Job and Jev confidence, and confirms an association while both cards remain.
- **Base:** no candidate or Jev is unavailable. Job Detail remains usable and
  neither Source Job changes.
- **Bad:** hide one listing, copy facts between listings, treat an unavailable
  result as different, reuse Related Jobs title deduplication, or test only on
  SQLite.

### 6. Tests Required

- PostgreSQL service tests cover canonical pairing, exact-fingerprint replay,
  changed-evidence invalidation, proposal persistence, bidirectional reads,
  idempotent review, audit JSON and unchanged `jobs.is_deleted` values.
- Component tests cover proposal/confirm UI and non-blocking read failure.
- Playwright uses isolated PostgreSQL plus loopback System One and asserts the
  complete Jobs list -> Detail -> paid Jev -> proposal -> confirmation -> Jobs
  list path. A provider-unavailable case asserts no confirm action and both Jobs
  remain visible.

### 7. Wrong vs Correct

#### Wrong

```python
if answer == "same_vacancy":
    duplicate_job.is_deleted = True
```

#### Correct

```python
if answer == "same_vacancy":
    association.status = "proposed"
# Both source-qualified Job rows remain unchanged.
```

## Scenario: production crawl-content quality advisory

### 1. Scope / Trigger

Use this contract when an operator asks Jev to review structurally successful
`crawl_job_listings` for semantic capture problems. The result is advisory and
must never become crawl lifecycle control or rewrite a Source Job.

### 2. Signatures

```text
GET  /api/crawl-jobs/tasks/{crawl_job_id}/quality
POST /api/crawl-jobs/tasks/{crawl_job_id}/quality/preview
     {"limit": 1..100}
POST /api/crawl-jobs/tasks/{crawl_job_id}/quality/evaluations
     {"limit": 1..saved crawl_quality_batch_limit}
```

Owned storage is `jev_crawl_quality_evaluations` plus
`jev_crawl_quality_observations`. Settings fields are
`crawl_quality_enabled` and `crawl_quality_batch_limit` (default 20, range
1..100). The slice reuses the frozen online Jev endpoint, model, allowance and
maximum-request reservation.

### 3. Contracts

- Preview is a database-only read. It creates no run, reservation or provider
  request and separates eligible, deterministic-excluded and insufficient rows.
- `manual_action_required`, `terminal_unavailable` and `identity_conflict` are
  deterministic exclusions. Non-completed or evidence-empty rows are
  insufficient. Only completed rows with a bounded visible title or description
  excerpt are eligible.
- The input fingerprint binds the task, ordered selected snapshots and rubric.
  Repeating an unchanged selection reuses its evaluation and receipt.
- The typed questions are `quality` and `problem_kind`; source content is
  untrusted evidence, never instructions. Receipts expose only secret-safe model,
  request ID, cost, status, probabilities and error code.
- Provider unavailable and budget exhaustion are terminal observations, not a
  negative quality label. Budget exhaustion sends zero provider requests and is
  persisted as `completed_with_failures / jev_allowance_exhausted`.
- The advisory service never changes `CrawlJob.status`,
  `CrawlJobListing.detail_status`, Jobs, events, or dispatch state and exposes no
  retry, repair, resume, cancel or reset action.
- New persistence tests and authoritative browser E2E use an isolated
  PostgreSQL database ending in `_test`; do not add a SQLite substitute.
- The UI clamps its requested limit to the saved maximum before preview or
  evaluation, including when the saved maximum is below the local default.

### 4. Validation & Error Matrix

| Condition | Required behavior |
|---|---|
| Task missing | `404`, no run or provider request |
| Preview limit outside 1..100 | `422` |
| No eligible selected rows | Preview returns zero; evaluation refuses without a provider call |
| Advisory disabled | Evaluation `409`; preview remains free/read-only |
| Requested limit exceeds saved maximum | `422`; UI clamps before sending |
| Exact fingerprint already exists | Return/reuse the existing evaluation |
| Jev answers | Persist observation and secret-safe receipt |
| Provider unavailable/invalid | Persist failed observation; preserve crawl/listing state |
| Allowance cannot cover reservation | Persist budget failure; zero provider requests; preserve state |
| Test database lacks `_test` suffix | Refuse before engine open, DDL or cleanup |

### 5. Good / Base / Bad Cases

- **Good:** preview one eligible listing for free, explicitly evaluate it, show
  `quality_problem / listing_or_template` with receipt and leave crawl state
  completed.
- **Base:** no eligible rows, provider unavailable or allowance exhausted. Show
  a bounded unresolved/failed advisory while the Task Details page remains
  usable and source state stays unchanged.
- **Bad:** infer WAF/IP facts through Jev, automatically retry or repair a crawl,
  write a Job quality flag as truth, hide technical failures, or test persistence
  only on SQLite.

### 6. Tests Required

- PostgreSQL service tests cover free deterministic preview, successful receipt,
  provider unavailable, zero-call budget exhaustion and unchanged Crawl Job and
  listing statuses.
- Settings tests cover defaults, validation and secret-safe serialization.
- Component tests cover the exact quality endpoint distinction, saved-limit
  clamping, preview copy, evaluation receipt and absence of lifecycle controls
  within the advisory section.
- Playwright starts the disposable PostgreSQL backend, deep-links through Crawl
  Tasks UI, proves preview request count is unchanged, proves evaluation adds
  exactly one `quality/problem_kind` provider request, displays the receipt and
  verifies persisted crawl/listing states. A separate unavailable browser case
  proves the same preservation boundary.

### 7. Wrong vs Correct

#### Wrong

```python
if observation.problem_kind == "listing_or_template":
    crawl_job.status = "failed"
    retry_detail(crawl_job.id)
```

#### Correct

```python
observation.problem_kind = "listing_or_template"
# Advisory only: crawl and listing lifecycle state remain source-owned.
```

## Scenario: production lexical-search relevance reranking

### 1. Scope / Trigger

Use this contract only when an operator explicitly previews and evaluates the
current lexical Job search. Ordinary search, paging, facets and preview are
database-only. Semantic and hybrid search do not accept a Jev rerank receipt.

### 2. Signatures

```text
POST /api/jobs/search/rerank/preview
     {"scope": <JobSearchScope>, "retrieval_mode": "lexical"}
POST /api/jobs/search/rerank/evaluations/{evaluation_id}
POST /api/jobs/search
POST /api/jobs/search/export
     { ..., "jev_rerank_evaluation_id": <completed evaluation id> }
```

Owned storage is `jev_search_rerank_evaluations`. Settings fields are
`search_rerank_enabled` and `search_rerank_candidate_limit` (1..50). The shared
`question_batch_limit` is an additional upper bound. A snapshot may contain at
most 10,000 complete result identities.

### 3. Contracts

- Lexical ordering is one total order: posted/created time, source site, source
  job ID and UUID. Preview freezes every matching Job identity in that order,
  while only the bounded prefix receives typed Jev score questions.
- The scope fingerprint binds the complete structured search scope, retrieval
  mode and rubric. Applying a receipt to another scope or mode is rejected.
- Jev may reorder only the selected frozen prefix. It cannot add/remove Jobs,
  change totals or facets, or score a page independently. Unselected frozen
  members retain baseline order after the prefix.
- Paging and CSV export reuse the same persisted total order and filter to the
  frozen membership. New matching Jobs are excluded. A missing/deleted frozen
  Job fails closed and requires a new preview.
- Preview and ordinary search send no provider requests. Only explicit Evaluate
  creates a run and reservation. Provider/answer/budget failure persists a
  terminal failure and applies the exact deterministic baseline order.
- Receipts expose only status, model/provider/request ID, cost, candidate scores
  and error code. Search text and Job text are untrusted evidence, never
  instructions.
- Authoritative persistence tests and browser E2E use isolated PostgreSQL
  databases ending in `_test`; no new SQLite path is permitted.

### 4. Validation & Error Matrix

| Condition | Required behavior |
|---|---|
| Semantic/hybrid preview or receipt use | `422`; no provider request |
| More than 10,000 matching Jobs | Preview `422`; ask operator to narrow scope |
| Reranking disabled | Preview remains free; evaluation `409` |
| Scope or mode differs from receipt | `422`; no order applied |
| Frozen member disappears | `422` requiring a fresh preview |
| New matching Job appears | Exclude it from the saved membership |
| Provider unavailable/invalid | Persist failure; retain exact baseline |
| Allowance cannot cover reservation | Zero provider calls; persist allowance failure; retain baseline |

### 5. Good / Base / Bad Cases

- **Good:** preview five lexical candidates for free, evaluate once, then use the
  same frozen order for pages and CSV while membership and totals remain fixed.
- **Base:** no results, disabled feature, unavailable provider or exhausted
  allowance. Ordinary search stays usable in deterministic baseline order.
- **Bad:** rerank only the visible page, silently accept a changed filter,
  include newly matching Jobs in a saved order, change facets, or make ordinary
  search call Jev.

### 6. Tests Required

- PostgreSQL service tests cover total baseline order, bounded prefix reorder,
  complete membership freeze, new/missing-member behavior, scope drift,
  provider fallback and zero-call allowance exhaustion.
- Component tests prove ordinary search is free, Preview then Evaluate is
  explicit, and the evaluation ID is reused in later search/export requests.
- Playwright proves zero calls for ordinary search and preview, exactly one typed
  call for evaluation, unchanged membership, changed successful order and CSV
  parity. A separate unavailable case proves exact baseline fallback.

### 7. Wrong vs Correct

#### Wrong

```python
rerank(current_page_rows)  # each page can overlap, drift or omit Jobs
```

#### Correct

```python
frozen_ids = deterministic_query(scope).all_ids()
ordered_ids = rerank_bounded_prefix(frozen_ids)
# Every page and export applies this same frozen membership and order.
```

## Scenario: production repeated-incident triage advisory

### 1. Scope / Trigger

Use this contract when an operator explicitly asks Jev to prioritize repeated,
secret-safe crawl incident clusters. This is a limited-review aid, not an
authoritative severity classifier and never an operational action system.

### 2. Signatures

```text
GET  /api/crawl-jobs/incident-triage
POST /api/crawl-jobs/incident-triage/preview
     {"event_limit": 1..saved incident_triage_event_limit}
POST /api/crawl-jobs/incident-triage/evaluations/{evaluation_id}
```

Owned storage is `jev_incident_triage_evaluations` plus
`jev_incident_triage_clusters`. Settings fields are `incident_triage_enabled`
and `incident_triage_event_limit` (default 200, range 1..1000). The shared
question batch limit bounds clusters sent in one request.

### 3. Contracts

- Preview reads the newest allowlisted failure/manual-action/WAF/IP/detail
  recovery events, derives deterministic issue metadata, removes URLs,
  credentials and variable numeric IDs, and clusters by source/phase/class/
  code/stage/normalized symptom before any model call.
- Every selected cluster persists all event references, sequence numbers,
  timestamps and raw-evidence hashes. Jev sees only the safe cluster fields and
  count, never raw payloads, URLs, credentials or individual event histories.
- Typed dispositions are `known_manual_recovery`,
  `transient_or_infrastructure`,
  `likely_source_content_or_parser_regression`, `investigate_now`, and
  `insufficient`. They are advisory and are not measured ground truth.
- Neither preview nor evaluation may modify Crawl Jobs, Crawl Job Events,
  severity, issue class, logs, dispatch plans or task actions. No retry, resume,
  cancel, reset, dismiss, browser or event-write dependency belongs in the
  product service or advisory UI.
- Preview/read are free. Explicit Evaluate creates one bounded run over the
  frozen cluster snapshot. Unavailable, invalid and over-budget outcomes retain
  the deterministic clusters with no disposition; budget exhaustion sends zero
  provider requests.
- The feature defaults off because repeated-event compression alone does not
  demonstrate prioritization quality or operator time savings. Production use
  should collect ordinary operational outcomes without claiming accuracy.
- New persistence tests and authoritative browser E2E use isolated PostgreSQL
  databases ending in `_test`; SQLite is not an accepted substitute.

### 4. Validation & Error Matrix

| Condition | Required behavior |
|---|---|
| Event limit outside 1..1000 or above saved maximum | `422`; no run |
| No eligible events/clusters | Free empty preview; evaluate control disabled |
| Incident triage disabled | Preview remains free; evaluation `409` |
| Exact frozen fingerprint repeats | Reuse evaluation and receipt |
| Provider answers every cluster | Persist typed advice and one safe receipt |
| Provider unavailable/invalid | Persist terminal failure; clusters remain unprioritized |
| Allowance cannot cover reservation | Zero provider calls; persist allowance failure |
| Crawl/event rows after either path | Status, count and content remain unchanged |

### 5. Good / Base / Bad Cases

- **Good:** three equivalent failures become one traceable secret-safe cluster;
  one explicit paid request marks it `investigate_now` without lifecycle writes.
- **Base:** no events, disabled feature, unavailable provider or exhausted
  allowance. Deterministic clusters remain visible and actionable systems are
  untouched.
- **Bad:** expose raw payloads/URLs/tokens, call retry from a recommendation,
  rewrite issue class/severity, delete event logs, or present disposition as a
  validated incident truth label.

### 6. Tests Required

- PostgreSQL tests cover safe normalization, full event-reference retention,
  deterministic compression, successful receipt, unavailable fallback,
  zero-call budget exhaustion and unchanged Crawl Job/Event rows.
- Component tests cover explicit Preview then Evaluate, free-preview copy,
  receipt/fallback and the absence of operational action controls.
- Playwright verifies UI/API/PostgreSQL/provider request accounting for success,
  unavailable and over-budget cases, and confirms Crawl Job status/event count
  remain unchanged.

### 7. Wrong vs Correct

#### Wrong

```python
if disposition == "known_manual_recovery":
    retry_crawl_job(cluster.crawl_job_id)
```

#### Correct

```python
cluster.disposition = "known_manual_recovery"
# Advice only; the crawl control plane remains authoritative and unchanged.
```
