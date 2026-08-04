# Manual Listing Identity Exclusion Contract

## Scenario: Source-aware ownership across manual listing runs

### 1. Scope / Trigger

Use this contract whenever JobsDB, CTGoodJobs, or OfferToday listing payloads
are accepted for a manual Crawl Job. A later manual run must not create another
detail backlog row for a Source Job identity already published or owned by an
earlier crawl run.

Scheduled runs retain their existing Published Job exclusion; historical
listing exclusion is manual-only until a separate reviewed contract changes
that policy.

### 2. Signatures

```python
CrawlJobRuntime.stage_listing_batch(
    *,
    crawl_job_id,
    source_site: str,
    payloads: list[dict[str, Any]],
    skip_existing: bool,
) -> ListingBatchPersistResult
```

```python
CrawlJobListingRepository.list_existing_source_job_ids(
    db,
    *,
    source_site: str,
    source_job_ids: Iterable[str],
    exclude_crawl_job_id=None,
) -> set[str]
```

`ListingBatchPersistResult` exposes separate ordered tuples:

```text
published_source_job_ids
historical_source_job_ids
preexisting_staged_source_job_ids
created_source_job_ids
```

### 3. Contracts

- Resolve the current Crawl Job inside the staging transaction. Missing run
  authority fails the batch.
- Perform one fail-closed bulk Published Job lookup for every non-empty batch.
- For `trigger_type=manual`, perform one fail-closed bulk historical listing
  lookup qualified by normalized `source_site` and excluding the current
  `crawl_job_id`. Per-ID existence queries are forbidden.
- Exclude the union of non-deleted Published Jobs and historical listing
  identities before current-run staging. Historical detail status does not
  transfer ownership to a new run: pending, running, completed, failed,
  skipped, manual-action-required, identity-conflict, and terminal-unavailable
  rows remain attached to their original run.
- OfferToday still validates historical encrypted-identity evidence before
  exclusion. A historical identity-conflict remains a hard stop rather than a
  silent skip; terminal-unavailable evidence retains its classification.
- Same-run rows are not historical. Current-run replay remains idempotent
  through the `(crawl_job_id, source_site, source_job_id)` uniqueness boundary.
- The same textual ID at another Source remains eligible.
- Listing discovery never moves, deletes, updates, or dispatches old backlog.
  Operators use the existing detail/recovery workflows against the original
  rows.
- `raw_job_ids_collected` and `job_ids_collected` continue to describe Source
  observations. `listings_staged` and detail workload describe accepted new
  rows. `jobs_skipped_existing` retains the Source runner's existing aggregation
  unit while including exclusions caused by either Published Job or historical
  listing ownership.

### 4. Validation & Error Matrix

| Condition | Required result |
|---|---|
| Manual ID exists as a non-deleted Published Job | Skip; no staging or detail target |
| Manual ID exists in another Crawl Job only | Return it as historical and skip |
| Historical row is pending, failed, completed, or another settled/unsettled status | Preserve the old row and skip new ownership |
| OfferToday history proves identity conflict | Hard stop and roll back; do not silently skip |
| ID exists only in the current Crawl Job | Treat as same-run replay, not historical |
| Same text exists only at another Source | Stage the new Source-qualified identity |
| Scheduled run sees unpublished historical staging | Preserve scheduled behavior; do not apply this manual-only exclusion |
| Published or historical bulk lookup fails | Roll back the whole batch; stage nothing |
| Candidate is absent from Published Jobs and other runs | Stage once and keep detail-eligible |

### 5. Good / Base / Bad Cases

- **Good:** A manual JobsDB batch observes 100 IDs, 80 belong to an older
  listing run, 15 are Published Jobs, and 5 are new. It records the collection
  observations, stages five rows, and leaves all old rows untouched.
- **Base:** A replayed page contains only rows already staged by the same run.
  The upsert is idempotent and no row is misreported as cross-run history.
- **Bad:** A later CTGoodJobs run restages an old failed identity so both runs
  advertise retryable detail work.
- **Bad:** OfferToday skips a known identity conflict before validating encrypted
  evidence, hiding an integrity stop.

### 6. Tests Required

- `backend/tests/test_crawl_job_runtime_existing_jobs.py` parameterizes all
  three Sources and supported historical statuses, asserts Source/current-run
  qualification, preserves OfferToday conflict behavior, and proves lookup
  failure rolls back without staging.
- `backend/tests/test_crawl_job_runtime_raw_metrics.py` proves repeated Source
  observations remain separate from distinct accepted identity counts through
  both bulk lookups.
- `backend/tests/test_listing_runtime.py` proves JobsDB cumulative/final
  summaries include historical exclusions and scheduled runs retain their
  reviewed policy.
- Relevant OfferToday identity, cross-source recovery/logging, and complete
  backend regression suites must remain green.

### 7. Wrong vs Correct

#### Wrong

```python
for source_job_id in source_job_ids:
    if listing_repository.find_any(source_job_id):
        continue
```

This creates N+1 reads, ignores Source identity, may match the current run, and
can turn a lookup error into partial staging.

#### Correct

```python
historical_ids = listing_repository.list_existing_source_job_ids(
    db,
    source_site=normalized_source,
    source_job_ids=ordered_job_ids,
    exclude_crawl_job_id=crawl_job_id,
)
excluded_ids = published_ids | historical_ids
```

The repository owns the Source/current-run boundary and any query failure
escapes the single transaction so staging rolls back.
