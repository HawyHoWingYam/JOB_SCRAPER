# OfferToday Broad IT Coverage and Reliability Research Design

> Date: 2026-07-10
> Status: Draft for user review

## Objective

Determine, with reproducible evidence, how JOB_SCRAPER can discover and publish OfferToday IT and technology jobs as completely and reliably as practical.

The research must separate two questions that the current metrics conflate:

1. Discovery recall: which OfferToday job IDs can the listing planner reach?
2. Pipeline completion: which discovered IDs survive staging, detail retrieval, parsing, and publication?

The accepted target is broad IT coverage. It includes the official OfferToday IT category tree and technology roles placed under other categories when their title or detail contains clear technical evidence.

## Approved Decisions

- Use a full-site listing census across all 31 OfferToday top-level categories as the reference baseline.
- Do not fetch details for every non-IT job. Fetch details only for broad-IT candidates, ambiguous candidates, and stratified quality samples.
- Run research against the existing PostgreSQL database and crawl infrastructure.
- Tag every research crawl so it can be separated from ordinary product crawls.
- Preserve all existing crawl and staging history. The research will not delete historical rows. A tagged reconciliation run may make audited status transitions, but broad untracked rewrites are prohibited.
- Use `jobId` as the canonical business identity and preserve `encryptJobId` as a separate request and public-URL identifier.
- Require a recall proxy of at least 98 percent against the reference set.
- Require the 95 percent confidence lower bound for sampled IT precision to be at least 90 percent.
- Require at least 99 percent availability-adjusted detail success against a frozen eligible-ID cohort, with only structured code-2520 terminal outcomes excluded and reported separately.
- Require three successful repeated runs with no unexplained listing gaps before recommending a production default.

## Why This Research Is Needed

The current OfferToday implementation can produce a high ID count without proving completeness, and it can produce a high detail-success count without proving that distinct new jobs were published.

The current code and database show several independent loss mechanisms:

- Default IT listing used a global unique-ID target of 3000 and stopped as soon as that count was reached. The current dirty worktree raises this target to 5000, but a target threshold is still not natural exhaustion.
- A non-success listing response is skipped without retrying the same page or failing the crawl.
- Listing discovery expands IT root category `118000` into root, leaf, keyword-only, and hybrid conditions, but category-scoped detail selection performs an exact staging-category match.
- Repeated listing crawls create duplicate pending staging rows for IDs that have not yet been published.
- Detail selection and metrics operate on rows in places where the product question requires distinct `jobId` counts.
- Audit and production paths do not use the same ID key or transport behavior.
- Standalone detail execution and repair classify the same upstream error codes differently.
- A failed detail request can still result in a listing-only Job upsert.

The research must correct or isolate these measurement blockers before interpreting a larger number as better coverage.

## Current Evidence Baseline

The following read-only snapshot was taken from the running local Docker stack on 2026-07-10. These values are a starting point, not final acceptance evidence.

| Metric | Current value |
|---|---:|
| Distinct OfferToday IDs in staging | 5573 |
| Published OfferToday jobs | 2961 |
| Distinct staged IDs without a published Job | 2612 |
| Pending staging rows | 9632 |
| Distinct IDs represented by pending rows | 4629 |
| Pending rows whose Job is already published | 4560 |
| Distinct already-published IDs with pending rows | 2017 |
| Published jobs with an empty description | 4 |

Recent run evidence also shows why raw counters are insufficient:

- Listing run `d3618206-368f-494b-8e15-0323efb96566` stopped at exactly 3000 IDs under the old target behavior.
- Listing run `a960099d-9d3d-444b-91b2-dcf2353151e1` used `max_pages=20`, discovered 4689 IDs, staged 2457, and skipped 2232 already-published IDs.
- That latest listing batch contained 1723 keyword-only pending rows and hundreds of leaf-category pending rows, while only the 160 root-category rows had completed detail work at inspection time.
- Detail run `35c1a0e7-1ed1-4688-a62d-b520e433ff16` processed 749 rows in about 40 minutes, reported 743 successes and 6 failures, and still ended with crawl status `completed`.

These observations support two immediate hypotheses:

1. The perceived shortage in the Job Browser is partly a discovery problem and partly a detail/backlog selection problem.
2. Current detail throughput is spent on duplicate or narrowly selected staging rows, so gross `jobs_saved` is not equivalent to net-new published jobs.

## Research Claims and Definitions

### Broad IT Job

A listing belongs in the broad IT reference set when at least one of these rules is satisfied:

1. Its official OfferToday job-function hierarchy places it under `118000` or an IT leaf category.
2. Its title contains unambiguous technical role or technology evidence.
3. Its title is ambiguous, but a controlled detail fetch provides unambiguous technical evidence.

Generic terms such as `project`, `support`, `manager`, `officer`, `consultant`, or `system` are not sufficient on their own.

### Discovery Recall Proxy

Absolute recall cannot be proven against a changing live site. The operational recall proxy is:

```text
|candidate planner jobIds intersect time-aligned reference broad-IT jobIds|
----------------------------------------------------------------------------
|time-aligned reference broad-IT jobIds|
```

The complete reference union consists of three full-site category census runs plus independent holdout probes. The acceptance denominator is the stable, time-aligned reference cohort: IDs observed in at least two census runs, plus holdout-only IDs confirmed active during the candidate window. IDs returning a structured terminal-unavailable response during the candidate window are reported but removed from that window's denominator.

Each candidate run is paired with a census cycle and starts within 30 minutes of that census completing. Full-union coverage remains a required diagnostic, but the 98 percent gate uses the time-aligned cohort so normal inventory churn is not mislabeled as crawler loss.

### Stability

Stability means more than process completion. A stable run has:

- no unresolved page gaps;
- no hidden auth, WAF, or IP-block response;
- no stranded `running` detail row;
- no unexplained conservation mismatch;
- bounded count variation across repeated runs;
- durable checkpoints that survive process restart; and
- structured terminal and retryable outcomes for every attempted detail.

### Canonical Identity

```text
jobId        = source_job_id, deduplication key, and Job upsert key
encryptJobId = detail request identifier and public URL identifier
```

The research must measure missing values, one-to-many mappings, mapping changes, and request/response mismatches. It must not silently substitute one identifier for the other when both should be present.

## Scope

### In Scope

- A production-equivalent listing runner shared by normal and research crawls.
- Page-attempt and condition-level research evidence in existing crawl-job storage.
- Full-site listing census across all 31 OfferToday top-level categories.
- Broad-IT reference-set construction and stratified manual validation.
- Category, keyword, and hybrid planner ablation.
- Endpoint, pagination, session, and pacing experiments.
- Distinct-ID reconciliation from listing through publication.
- Unified OfferToday response classification.
- Detail canaries, restart injection, and recovery verification.
- A final recommended production planner and operating policy.

### Out of Scope

- Fetching details for every job in all 31 categories.
- Deleting duplicate staging rows or historical crawl data. Audited status reconciliation without deletion remains in scope.
- Treating OfferToday `data.total` as an independent truth set.
- Increasing concurrency before a single session is stable.
- Expanding the keyword pack before current conditions have measured marginal yield.
- Using an LLM as the first-pass broad-IT classifier.
- Changing JobsDB or CTGoodJobs crawl behavior.

## Architecture

### 1. Shared Listing Runner

Extract listing execution from the standalone script into one testable unit used by both production listing crawls and the research census.

Inputs:

- ordered listing conditions;
- runtime transport;
- retry and pacing policy;
- stop policy;
- observation sink; and
- staging sink.

Outputs:

- condition outcomes;
- page-attempt observations;
- distinct ID observations;
- unresolved gaps; and
- a completion decision.

The runner owns pagination, same-page retries, response validation, ID extraction, condition exhaustion, and stop reasons. Consumers must not reimplement these rules.

### 2. Response Classifier

One OfferToday response classifier is shared by listing, detail, smoke, and repair paths.

| Classification | Typical signal | Required behavior |
|---|---|---|
| `success` | code 0 and valid shape | Continue |
| `auth_expired` | code 1002 | Pause for manual action; do not report healthy |
| `waf_challenge` | verification URL | Complete headed verification or pause safely |
| `ip_blocked` | code -1000035 | Stop the batch; leave unattempted rows pending |
| `terminal_unavailable` | code 2520 | Persist terminal outcome; do not auto-retry |
| `transient_transport` | timeout, 429, 5xx | Apply bounded retry with backoff |
| `invalid_payload` | code 0 with invalid data | Preserve evidence and fail the item/page |
| `id_mismatch` | response ID differs from request | Do not publish; require audit |
| `persist_failure` | transaction error | Roll back Job and listing transition together |

### 3. Research Ledger

Research runs use existing `crawl_jobs`, `crawl_job_events`, and `crawl_job_listings`.

Each research request contains:

```json
{
  "research": {
    "run_id": "uuid",
    "experiment": "full-site-census",
    "variant": "category-browse",
    "planner_version": "git-sha"
  }
}
```

Research events are:

- `research.page_attempt`
- `research.condition_completed`
- `research.condition_incomplete`
- `research.run_summary`

A page-attempt event records:

- family, category, keyword, endpoint, and request fingerprint;
- page number and attempt number;
- API code and response classification;
- reported total, `hasMore`, and row count;
- ordered `(jobId, encryptJobId)` pairs;
- latency and session mode; and
- retry and stop reasons.

Every research run exports `backend/runtime/offertoday-research/<run_id>/manifest.json` and `observations.jsonl` from these events when it completes, fails, pauses, or hits a hard stop. The export also contains a content-hash manifest and any partial observations collected before termination.

The artifact records the commit SHA, a `working-tree.patch` for the dirty worktree, and hashes of relevant OfferToday source files. A commit SHA alone is not sufficient to reproduce a research run from this repository's current state.

### 4. Broad IT Reference Builder

The reference builder consumes census artifacts without making network requests.

It applies official-category and deterministic-title rules first. Ambiguous rows are emitted as detail candidates. A human-review sample is stratified by source category, evidence rule, and query family.

To prevent circular validation, the builder also selects a fixed, stratified sample from rows rejected by title rules, including title-negative rows from every non-IT category and language cohort. Those rows receive controlled detail fetches and labels to estimate the reference builder's false-negative rate. A discovered false negative changes the rules, invalidates that validation sample for acceptance, and requires a new independent validation sample.

The reference builder returns:

- accepted broad-IT IDs with reasons;
- rejected IDs with reasons;
- unresolved candidates;
- rule-level counts; and
- precision and false-negative confidence intervals.

### 5. Planner Comparator

The comparator runs candidate planners against the same reference time windows and reports:

- recall proxy;
- sampled precision;
- IDs unique to each family;
- holdout-only IDs;
- duplicate rate;
- requests and seconds per new ID;
- family marginal-yield curves; and
- exact missed-ID cohorts.

It must compare ID sets, not API totals or summed category counts.

### 6. Pipeline Reconciler

The reconciler reports a distinct-ID funnel:

```text
census discovered
-> production planner discovered
-> staged unique
-> detail eligible
-> detail attempted
-> completed / terminal / manual action / retryable / pending / running
-> published complete / published partial
```

The reconciler also identifies duplicate staging rows, pending rows whose Job already exists, repeated detail attempts, and status/Job transaction splits.

## Data Invariants

Every research run must satisfy both listing equations:

```text
raw listing rows
= rows missing jobId
+ rows containing jobId

valid distinct discovered jobIds
= distinct already-published jobIds
+ distinct preexisting staged-unpublished jobIds
+ distinct newly-staged jobIds
+ distinct deferred identity-conflict jobIds
```

Classification uses the run-start snapshot and this priority: already published, preexisting staged-unpublished, deferred identity conflict, then newly staged. Each valid distinct ID belongs to exactly one partition.

Every detail scope must satisfy:

```text
distinct detail eligible
= completed
+ terminal unavailable
+ retryable failed
+ manual action required
+ pending
+ running
```

The categories on each right-hand side must be mutually exclusive. Detail conservation is evaluated at a quiescent checkpoint after startup recovery and transaction reconciliation. The unexplained difference for every equation must be zero, and `running` must be zero when a run reaches a terminal state.

Duplicate rows do not vote independently on an ID's outcome. The reconciler selects one authoritative attempt per canonical `jobId`; a valid complete Job is `completed`, otherwise the authoritative attempt determines terminal, manual-action, retryable-failure, pending, or running state. Persistence failure is a retryable-failure subtype until reconciliation succeeds.

Additional invariants:

- A page is either successfully observed or explicitly recorded as an unresolved gap.
- A research run with an unresolved gap cannot be `completed`.
- A reference condition is naturally exhausted only after a successful terminal signal (`hasMore=false` or an empty page) is followed by one successful empty confirmation page. If the confirmation page is non-empty, the runner records a contract anomaly and continues.
- Reaching any safety page cap before confirmed natural exhaustion marks the condition and run incomplete.
- One `jobId` appears at most once in a detail target set.
- Existing pending duplicates are reconciled before applying `detail_limit` to fetch targets.
- Selecting IT root scope includes its expanded leaf scope and keyword-only candidates from the same listing run.
- Unattempted rows never have their attempt count or failure status changed by a batch-level block.
- A successful detail response must match the requested identity before publication.
- A terminal response does not perform another network request on the next automatic repair run.
- `jobs_saved` distinguishes created, updated, reconciled, and duplicate outcomes.

## Research Phases

### Phase 0: Freeze the Baseline

Activities:

- Capture commit SHA, dirty diff summary, compose configuration, runtime/session mode, and timestamp.
- Capture the full dirty worktree patch and relevant source-file hashes.
- Capture the distinct-ID database funnel and error distribution.
- Capture the latest relevant crawl-job request payloads and metrics.
- Export the baseline as a versioned artifact.

Exit gate:

- The baseline can be regenerated with one command and produces the same counts when the database is unchanged.

### Phase 1: Calibrate Measurement and Remove Blockers

Activities:

- Restore direct tests for search-space planning and coverage analysis.
- Add fixture-driven tests around the listing and detail main loops.
- Unify production and audit identity keys.
- Implement page-level retry and gap-aware completion.
- Correct parent-scope expansion for detail selection.
- Select distinct detail IDs and reconcile existing pending duplicates before applying the network-fetch limit.
- Reconciliation logically excludes duplicate rows from target selection. A tagged reconciliation may mark an old pending row completed when a valid complete Job already exists, but it must emit before/after audit evidence and must not delete the row.
- Unify response classification across standalone, smoke, and repair.
- Route every successful production detail payload through the same OfferToday parser and quality-cleanup path.
- Verify that any fallback transport preserves the required authenticated cookie and CSRF context; otherwise classify the fallback as unavailable instead of silently changing auth context.

Exit gate:

- All conservation fixtures pass.
- Every injected error reaches the expected structured state.
- Audit and production produce the same ID set from the same saved responses.

### Phase 2: Full-Site Listing Census

Activities:

1. Run a low-risk pilot of three pages per top-level category.
2. Compare `search/list` and `list` where both are meaningful.
3. Probe only evidence-backed `rcdType` variants.
4. Select the reference endpoint and payload based on valid rows and stability.
5. Run all 31 categories to confirmed natural exhaustion with conservative pacing and no global unique-ID target.
6. Repeat the full census three times across at least two time windows.
7. Repeat selected fixed conditions three times in one short window to measure ranking instability separately from inventory churn.

Exit gate:

- Every condition is complete or the full run is failed with an explicit gap.
- The reference union and per-run set hashes can be reproduced from JSONL.
- Fixed-cohort Jaccard is at least 0.95 and unique-count coefficient of variation is at most 5 percent.

### Phase 3: Build the Broad IT Reference Set

Activities:

- Accept official IT-category rows.
- Apply deterministic technical-title evidence to the other 30 categories.
- Fetch details only for unresolved candidates and validation samples.
- Before labels are revealed, freeze separate validation samples for predicted-positive precision and predicted-negative false-negative analysis. Each sample contains at least 200 rows and uses proportional allocation across predeclared category, language, and evidence-rule strata, with a fixed maximum of 500 rows per validation cycle.
- Use the self-weighting proportional sample for the overall Wilson interval. Report exact per-stratum intervals separately. Do not extend a sample merely because an interim interval misses the gate; change the rules and run a new independent validation cycle.
- Require the predicted-positive Wilson 95 percent lower confidence bound to reach 90 percent and the predicted-negative one-sided 95 percent upper bound for broad-IT false negatives to remain at or below 2 percent.
- Preserve the rule and evidence used for every accepted ID.

Exit gate:

- Precision lower bound is at least 90 percent.
- Predicted-negative broad-IT false-negative upper bound is at most 2 percent.
- No unresolved candidate is silently counted as accepted.

### Phase 4: Planner Ablation and Miss Analysis

Candidate variants:

1. IT category only.
2. Keyword only.
3. Category plus keyword.
4. Category plus keyword plus hybrid.
5. The best measured family set with low-yield conditions removed.

Activities:

- Compare every variant to the same reference windows.
- Rank conditions by new broad-IT IDs per request.
- Hold back independent probes to detect circular planner evaluation.
- Inspect missed cohorts by category, title pattern, language, and publication time.
- Reject wide terms that increase count without preserving precision.

Exit gate:

- Recall proxy is at least 98 percent.
- Precision lower bound remains at least 90 percent.
- Adding another family yields less than 0.5 percent new reference IDs or fails the efficiency guard.

### Phase 5: Detail Canary and Fault Injection

Activities:

1. Select a 100-ID stratified canary.
2. Expand to 500 IDs after the canary passes.
3. Process the complete distinct broad-IT backlog after the 500-ID gate passes.
4. Inject restart after a detail row is marked running.
5. Inject failure between Job persistence and listing completion.
6. Exercise auth expiry, WAF, IP block, terminal unavailable, timeout, non-JSON, and ID mismatch fixtures.
7. Compare fresh headless, storage-state, and reusable-browser sessions with the same smoke cohort.

Exit gate:

- Eligible detail success is at least 99 percent.
- Terminal outcomes are classified and never auto-retried.
- No unattempted row is marked failed.
- No Job/listing transaction split remains.
- No repeated detail request occurs for the same `jobId` in one run.

### Phase 6: Production Candidate Soak

Activities:

- Run the selected planner three times with production pacing.
- Drain the resulting distinct detail backlog.
- Compare reference recall, precision, error rates, queue age, and net-new publication.
- Produce a final decision record with the accepted planner and rejected alternatives.

Exit gate:

- Every final acceptance criterion passes on all three runs.

## Experiment Matrix

| Dimension | Variants | Primary evidence |
|---|---|---|
| Endpoint | `search/list`, `list` | Valid rows, unique IDs, failures |
| Query family | category, keyword, hybrid | Recall, precision, marginal yield |
| Depth | 1, 3, 6, natural exhaustion | Saturation and page gaps |
| Session | fresh headless, storage state, reusable browser | Auth/WAF rate and longest success streak |
| Identity | `jobId`, `encryptJobId` mapping | Missing, collision, and mismatch rates |
| Detail cohort | official IT, cross-category technical, ambiguous | Success and content completeness |
| Recovery | timeout, block, restart, commit interruption | State and conservation correctness |

## Metrics and Acceptance Criteria

### Discovery

- Recall proxy: at least 98 percent.
- Unresolved listing gaps: zero.
- Invalid or missing `jobId`: explicitly accounted for; no silent drop.
- ID mapping conflicts: zero in the accepted detail queue.
- Last 100 successful requests add less than 0.5 percent of the final union before declaring planner saturation. This is an efficiency signal only; it never replaces confirmed natural exhaustion in a reference census.

### Precision

- Minimum labeled sample: 200 for each predicted-positive and predicted-negative validation cohort, stratified by evidence source.
- Wilson 95 percent lower confidence bound: at least 90 percent.
- Predicted-negative broad-IT false-negative one-sided 95 percent upper bound: at most 2 percent.
- Validation sample sizes, strata, and maximum size are frozen before labels are read; a failed gate requires a fresh validation cycle.
- Broad generic terms cannot be accepted as standalone evidence.

### Detail Quality

- Freeze the distinct eligible-ID cohort before each detail run. Gross outcomes always use this frozen denominator.
- Availability-adjusted detail success is at least 99 percent, calculated as ID-matched, persisted detail successes divided by the frozen eligible cohort after excluding only IDs that return structured terminal-unavailable code 2520 during that run. The terminal-unavailable rate is reported separately against the original frozen cohort.
- Unresolved auth, WAF, IP-block, transient, invalid-payload, and persistence outcomes remain failures and can never be removed from the denominator after the run starts.
- Non-empty title, company, and cleaned description among successful details: at least 98 percent each.
- Request/response ID mismatch: zero published rows.
- Terminal retry rate: zero.
- Published partial rows counted as complete: zero.

### Stability

- Three accepted final runs.
- Fixed-cohort Jaccard: at least 0.95.
- Unique-count coefficient of variation: at most 5 percent.
- Unclassified failures: zero.
- Orphan running detail rows: zero after recovery.
- Conservation difference: zero.

### Efficiency

- Report requests per new reference ID and seconds per new reference ID.
- Reject a candidate that doubles request cost for less than two percentage points of recall improvement.
- Do not retain a query family whose incremental recall is below 0.5 percent unless it covers a documented high-value cohort unavailable elsewhere.

## Stop and Rollback Conditions

Stop the active live experiment immediately when any of these occurs:

- auth-expired code 1002;
- a WAF verification challenge;
- IP-block code -1000035;
- three consecutive transport or API failures;
- unresolved page-failure rate above 1 percent;
- an ID mapping collision or response/request mismatch;
- a non-zero conservation difference;
- run-local staging amplification above 1.01, calculated as newly created staging rows divided by distinct IDs classified `newly staged`; when the denominator is zero, any created staging row is a violation; query provenance belongs in events rather than duplicate staging rows; or
- a twofold request-cost increase with less than two percentage points of recall gain.

Because research uses the existing database, rollback means stopping new requests and preserving the tagged run for diagnosis. It does not mean deleting rows. The production planner remains unchanged until a candidate passes every gate.

## Testing and Verification

### Deterministic Tests

Planned focused coverage:

- search-space planning and stable query ordering;
- page retry and unresolved-gap completion;
- `hasMore` and empty-page behavior;
- `jobId` and `encryptJobId` mapping;
- response-classification matrix;
- root-category detail expansion;
- distinct detail selection before limit;
- pending-existing reconciliation;
- terminal no-retry behavior;
- IP-block handling for unattempted rows;
- process-restart recovery;
- transactional Job/listing completion; and
- research-event export and replay.

Expected test command after implementation:

```bash
python -m pytest -q \
  backend/tests/test_offertoday_search_space.py \
  backend/tests/test_offertoday_coverage_audit.py \
  backend/tests/test_offertoday_standalone_crawl.py \
  backend/tests/test_offertoday_browser_runtime.py \
  backend/tests/test_offertoday_canonical_and_identity.py \
  backend/tests/test_crawl_job_runtime.py \
  backend/tests/test_startup_recovery.py
```

The implementation plan must adjust this list to the final test filenames rather than silently omitting a missing test module.

### Database Verification

For every research run, verify:

- distinct discovered, staged, pending, completed, terminal, and published IDs;
- duplicate rows per distinct ID;
- pending rows that already have a Job;
- rows whose status and published Job disagree;
- research event sequence completeness; and
- both conservation equations.

### Live Verification Order

1. One-condition runtime smoke.
2. Three-page, 31-category census pilot.
3. One full census.
4. Three full reference censuses.
5. Planner ablation runs.
6. 100-detail canary.
7. 500-detail canary.
8. Full distinct IT backlog.
9. Three-run production candidate soak.

No later live step begins when the preceding step has an unresolved stop condition.

## Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Direct research writes enlarge production staging | Medium | Tag every run, enforce growth guard, and dedupe detail targets globally |
| Live inventory changes during census | Medium | Use three runs, fixed cohorts, timestamps, and set hashes |
| Broad terms inflate apparent recall | High | Require reference matching and stratified precision bounds |
| Audit differs from production | High | Share the listing runner and response classifier |
| Long crawls trigger WAF or expiry | High | Conservative pacing, preflight, hard stops, and durable page ledger |
| Repeated batches waste detail capacity | High | Reconcile pending existing rows and select distinct IDs before limit |
| A parent category omits expanded children | High | Resolve effective scope from listing provenance, not exact parent equality |
| Terminal rows retry forever | Medium | Persist structured terminal classification and exclude it from auto-retry |
| Partial jobs hide detail failure | High | Track partial state explicitly and exclude it from complete-job metrics |

## Deliverables

- Current OfferToday funnel and duplicate-backlog baseline report.
- Three recomputable full-site listing census artifacts.
- Broad-IT reference set with evidence and review labels.
- Current-planner missed-ID report.
- Category, keyword, and hybrid ablation report.
- Identity mapping quality report.
- Detail classification, quality, and recovery report.
- Ranked query-condition keep/remove/degrade recommendations.
- Final production planner, pagination, pacing, and retry policy.
- Repeatable verification commands and a decision record.

## Production Decision Rule

The research does not switch the default OfferToday planner automatically.

The default changes only when one candidate passes all discovery, precision, detail, stability, conservation, and efficiency gates. If no candidate passes, the current planner remains in place and the final report must identify the failing gate and the exact missed or unstable cohorts.
