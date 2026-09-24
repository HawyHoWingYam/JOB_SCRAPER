# Jev System One Settings and Manually Started Runs

## Scenario: native System One decisions with provider-managed monetary limits

### 1. Scope / Trigger

Use this contract whenever code configures Jev, sends a native System One
request, exposes a bounded run, or renders Jev operations. Jev is not an LLM
chat-provider profile and must not be routed through the existing
chat/completions clients. Monetary limits belong exclusively to the Jev API
Console; this application must not keep a parallel allowance or spending gate.

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
POST /api/jev/operations/preview
POST /api/jev/operations/batches
GET  /api/jev/operations/batches
POST /api/jev/operations/batches/{batch_id}/stop
POST /api/jev/operations/batches/{batch_id}/resume
POST /api/jev/operations/batches/{batch_id}/retry-failed
```

Owned database tables:

```text
jev_runtime_settings
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

- Settings store `enabled`, full endpoint, model, masked secret state, sample
  and question limits, concurrency, retry limit, timeout, and fixed-millis
  evidence and recommendation thresholds. They contain no allowance, local
  price, reservation, or cost-ceiling fields.
- Blank `jev.api_key` preserves the saved secret. GET responses expose only
  `has_api_key` and `api_key_preview`; run snapshots store only a SHA-256 key
  fingerprint, never the credential.
- A run freezes endpoint, model, work membership/order, rubric,
  retry/concurrency limits, thresholds, and key fingerprint. Later Settings
  edits affect only later runs.
- Provider `usage.cost`, when present and validated, may be rounded to integer
  microdollars and retained strictly as audit telemetry. Missing provider cost
  stays unknown: never estimate it from tokens, reserve it, compare it with a
  local ceiling, or block dispatch. The Jev API Console is the sole monetary
  authority.
- Native request JSON is `{state, model, questions}`. Named questions use
  `noul`, `choice`, or `score`. Responses must return the exact question names
  and matching answer types, a model, bounded probabilities, non-negative token
  usage, and measured `latency_ms` in the persisted receipt. OpenRouter's
  documented `id`, `provider`, and `usage.cost` receipt fields are accepted and
  persisted when present; unrecognized fields remain schema errors.
- Reading Settings/run state, saving defaults and previewing work never calls
  System One. Provider work starts only after an explicit operator action from
  the unified Jev Operations page. The smoke action first creates one bounded
  run, then explicitly executes its only item.
- The Settings page owns credentials, model and operational defaults. Preview,
  Start, Stop, Resume, Retry, smoke and all other Jev execution controls live on
  the unified Jev Operations page.
- Online Skill classification and historical backfill use the same dispatch
  builder for the input fingerprint. Backfill preview recomputes that exact
  fingerprint from frozen original candidate/evidence plus the current Job,
  taxonomy and runtime identity; a parallel approximation is forbidden.
- Ordinary AI enrichment never creates or executes Online Skill classification.
  It first publishes a usable AI Skill baseline. Jev Skill classification is a
  separately and explicitly started correction pass; unavailable Jev preserves
  the current usable projection.
- Job Detail and Candidate reads whitelist audit fields (`status`, model,
  request ID, reported cost and error code). They never expose credentials,
  endpoint configuration, full answers or evidence snapshots and never call the
  provider.
- Stronger-model Skill maintenance has a separate model. It has no scheduler or
  automatic start path: an operator starts it from Jev Operations. It persists
  recoverable work before dispatch and allows at most one pending/running batch. SQLite
  timestamps read without `tzinfo` are interpreted as UTC before comparison.
- New Skill proposals remain a visible aggregate diff containing the frozen
  batch/taxonomy identity, candidate, parent Technology and both confidences.
  Approval is explicit; unresolved/conflicting proposals remain held.

### 4. Validation & Error Matrix

| Condition | Required behavior |
|---|---|
| Public non-HTTPS endpoint | Settings `422`; loopback HTTP is test/local only |
| Blank model or invalid operational limit/threshold | Settings `422` with field location |
| Monetary field sent by an obsolete client | Settings `422`; no parallel local limit is accepted |
| Disabled Jev or missing key | Run create `409`; no provider call |
| Duplicate active purpose or invalid work | Run create `422`; no provider call |
| Key changed after run creation | Execute `409`; frozen run is not silently rebound |
| Timeout/network/non-2xx | Item fails with a secret-safe unavailable receipt; no implicit retry |
| Malformed JSON/schema or answer mismatch | Item fails as invalid; no local cost is invented |
| Stop before dispatch | Pending items become cancelled; no provider call |
| Resume non-cancelled run or retry beyond frozen limit | `409`; existing receipts remain unchanged |

### 5. Good / Base / Bad Cases

- **Good:** an operator saves masked settings, previews work for free, explicitly
  starts a bounded run, receives typed answers plus usage/latency, and sees the
  frozen model and optional provider-reported cost in the UI.
- **Base:** Jev is disabled or unavailable. Existing deterministic Job/Skill
  behavior remains unchanged and read surfaces remain usable.
- **Bad:** page render, Settings save, scheduler startup or process restart
  starts Jev work.
- **Bad:** recreate provider monetary limits locally, estimate money from token
  usage, block on a local ceiling, return upstream bodies, or persist the bearer
  credential in run JSON/logs/test artifacts.

### 6. Tests Required

- Adapter unit tests assert exact endpoint/auth/body, all three answer types,
  usage, deterministic latency, bounded values, non-2xx, transport failure,
  malformed response, answer mismatch, and secret-safe diagnostics.
- Settings tests assert defaults, partial update, mask/blank-secret behavior,
  HTTPS/public-HTTP validation, rejection of obsolete monetary fields, and zero
  provider calls.
- Run tests assert optional provider-cost audit, missing-cost non-estimation,
  idempotency, frozen configuration, stable order, stop/resume/retry and retry
  limit.
- Route tests assert create/read/list/stop/resume/execute without allowance
  projections. The real HTTP integration test uses only a loopback fake server.
- Browser E2E uses an isolated backend database and loopback fake System One;
  assert save/reload, masked secret, exactly one provider request, typed receipt,
  usage, optional provider cost, explicit manual start, and old-run frozen model
  after a Settings edit.
- Disposable PostgreSQL cutover rehearsal asserts all four core Jev run tables are
  excluded from retained artifacts and empty after rebuild/import/verification.

### 7. Wrong vs Correct

#### Wrong

```python
# Recreate provider billing rules locally and block on an estimate.
if estimated_cost(request) > local_allowance:
    raise LocalAllowanceExhausted()
```

#### Correct

```python
result = await client.evaluate(request)
attempt.actual_microdollars = provider_reported_cost(result.usage)
```

If the provider omits cost, persist `None`. Operational safety still comes from
explicit manual start, finite work membership, timeout, concurrency and retry
bounds—not a second monetary policy engine.

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
- Each pair asks one bounded choice question. Unavailable, invalid, and
  `insufficient` outcomes never become negative evidence.
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
  do not call the provider to rediscover source/runtime facts.
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
- One ambiguous provider failure stops the sequence and makes the quality
  result inconclusive; it is never retried implicitly or
  converted into a quality label.

## Scenario: offline bounded search relevance evaluation

- Freeze candidate membership and source-qualified identities before any Jev
  judgment. Candidate recall and reranking quality are separate metrics.
- A reranker may reorder only the bounded candidate set. It may not alter scope,
  structured filters, facets, totals, pagination/export membership, or applied
  scope.
- Search pages and exports must slice the same complete deterministic ordering;
  source identity is the final tie key in evaluation artifacts.
- Provider unavailable/invalid failure returns the baseline order and
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
manifest hash, rubric/model identity, provider receipt, typed outcome,
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
  strata, p50/p95 latency, tokens, and optional provider-reported cost.
- Frozen held-out gates are: evidence answered correctness `>= 0.90`, Candidate
  top-1 correctness `>= 0.85`, technical failure `<= 0.05`, actionable coverage
  `>= 0.60`, and option-reordering stability `>= 0.95`.
- `run` requires an explicit paid confirmation and a persistent state database.
  A technical or uncertain result stops the sequence. Monetary enforcement is
  delegated to the Jev API Console.

### 4. Validation & Error Matrix

| Condition | Required behavior |
|---|---|
| Fixture hash drift, duplicate ID, or group leakage | Reject before any provider request |
| Non-PostgreSQL real export | Reject; do not simulate read-only guarantees |
| Artifact file/hash/schema drift | Fail closed; do not score |
| Missing paid confirmation | Reject with zero requests |
| HTTP/transport/schema failure | Persist safe unavailable/invalid receipt and stop |
| Missing controlled denominator or bilingual independent reference | Report `inconclusive`, never pass |
| Frozen controlled gate missed | Report `defer` |
| Every gate/reference requirement met | Report `proceed_limited_review` only |

### 5. Good / Base / Bad Cases

- **Good:** validate frozen artifacts, preview the selected cases without
  dispatch, pass one development smoke, run the bounded set, and emit a
  reproducible report without product-data writes.
- **Base:** credentials are invalid or independent references are absent. Keep
  current deterministic behavior and report `inconclusive`.
- **Bad:** call model agreement accuracy, omit abstentions/errors from a
  denominator, split duplicate/company-connected rows, or rerun after an
  ambiguous failure without an explicit operator retry.

### 6. Tests Required

- Fixture tests cover schema/hash drift, group leakage, bilingual/scenario
  coverage, and reordered options.
- Corpus tests cover PostgreSQL enforcement, minimization, connected grouping,
  temporal split integrity, manifest hashes, and forbidden raw fields.
- Runner tests cover explicit bounded dispatch, observation bindings, optional
  provider cost, stop-on-failure, idempotent resume, and secret safety.
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
model and provider-managed monetary policy.

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
  invalid and unavailable outcomes never become an association.
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
| Provider unavailable/invalid | Preserve both Jobs; no confirm control |
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
1..100). The slice reuses the frozen online Jev endpoint and model.

### 3. Contracts

- Preview is a database-only read. It creates no run or provider
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
- Provider unavailable is a terminal observation, not a negative quality
  label. Local monetary admission failures do not exist.
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
| Test database lacks `_test` suffix | Refuse before engine open, DDL or cleanup |

### 5. Good / Base / Bad Cases

- **Good:** preview one eligible listing for free, explicitly evaluate it, show
  `quality_problem / listing_or_template` with receipt and leave crawl state
  completed.
- **Base:** no eligible rows or provider unavailable. Show
  a bounded unresolved/failed advisory while the Task Details page remains
  usable and source state stays unchanged.
- **Bad:** infer WAF/IP facts through Jev, automatically retry or repair a crawl,
  write a Job quality flag as truth, hide technical failures, or test persistence
  only on SQLite.

### 6. Tests Required

- PostgreSQL service tests cover free deterministic preview, successful receipt,
  provider unavailable and unchanged Crawl Job and
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
  creates a run. Provider/answer failure persists a
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

### 5. Good / Base / Bad Cases

- **Good:** preview five lexical candidates for free, evaluate once, then use the
  same frozen order for pages and CSV while membership and totals remain fixed.
- **Base:** no results, disabled feature or unavailable provider. Ordinary
  search stays usable in deterministic baseline order.
- **Bad:** rerank only the visible page, silently accept a changed filter,
  include newly matching Jobs in a saved order, change facets, or make ordinary
  search call Jev.

### 6. Tests Required

- PostgreSQL service tests cover total baseline order, bounded prefix reorder,
  complete membership freeze, new/missing-member behavior, scope drift,
  and provider fallback.
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
  frozen cluster snapshot. Unavailable and invalid outcomes retain the
  deterministic clusters with no disposition.
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
| Crawl/event rows after either path | Status, count and content remain unchanged |

### 5. Good / Base / Bad Cases

- **Good:** three equivalent failures become one traceable secret-safe cluster;
  one explicit paid request marks it `investigate_now` without lifecycle writes.
- **Base:** no events, disabled feature or unavailable provider. Deterministic
  clusters remain visible and actionable systems are
  untouched.
- **Bad:** expose raw payloads/URLs/tokens, call retry from a recommendation,
  rewrite issue class/severity, delete event logs, or present disposition as a
  validated incident truth label.

### 6. Tests Required

- PostgreSQL tests cover safe normalization, full event-reference retention,
  deterministic compression, successful receipt, unavailable fallback,
  and unchanged Crawl Job/Event rows.
- Component tests cover explicit Preview then Evaluate, free-preview copy,
  receipt/fallback and the absence of operational action controls.
- Playwright verifies UI/API/PostgreSQL/provider request accounting for success
  and unavailable cases, and confirms Crawl Job status/event count
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
