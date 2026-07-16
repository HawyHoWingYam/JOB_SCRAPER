# Add source-specific detail pacing runtime

## Goal

Persist and apply stable, source-specific pacing to manually triggered Job
Detail network attempts for JobsDB, CTGoodJobs, and OfferToday.

## Requirements

- Add a dedicated `scraper_pacing_settings` table with one row per source; do
  not reuse AI runtime settings.
- Seed JobsDB, CTGoodJobs, and OfferToday with 1-3 second random interval, burst
  size 20, and burst pause 30 seconds.
- Validate interval values at 0.1-60 seconds with min <= max and not both zero;
  burst size at integer 1-1000; burst pause at 0-3600 seconds.
- Provide typed settings GET/PUT/reset contracts with backend-authoritative
  validation.
- Resolve settings server-side and snapshot `detail_pacing` into manual detail
  CrawlJob request payloads at dispatch.
- Preserve the snapshot and cumulative attempt position across manual-action
  Resume. Historical tasks without a snapshot remain unrecorded.
- Keep detail execution serial. Reject a second active detail task for the same
  source while queued, dispatching, running, manual-action-required, or
  cancelling; allow other sources concurrently.
- Pace every actual outbound detail attempt, including every OfferToday retry.
  Exclude listing, warmup/session checks, and manual verification navigation.
- First attempt is immediate. Later attempts use the random interval, except a
  completed burst uses the burst pause instead. Do not pause after final work.
- Sleeps must be cancellation-aware and check at least once per second.
- Scheduled crawls and listing pacing are excluded.

## Acceptance Criteria

- [ ] Migration upgrade seeds exactly the three valid source rows; downgrade is
      verified.
- [ ] Invalid settings are rejected and independent source updates do not alter
      other rows.
- [ ] Manual detail dispatch snapshots backend-resolved effective settings and
      rejects a same-source active detail conflict atomically.
- [ ] Global edits never alter an existing task snapshot; Resume retains the
      snapshot and cumulative attempt position.
- [ ] Deterministic tests prove exact attempt counting, interval/burst
      replacement, first/final behavior, retry integration, and cancellation
      checks.
- [ ] All three source workers call one shared pacing contract immediately before
      each outbound detail request without changing their outcome semantics.
- [ ] Listing and scheduled dispatch paths remain unchanged.

## Dependencies

- Reliable cancellation must be implemented and pass its release gate before
  pacing is enabled in production.
- Settings UI and Crawl Tasks UI depend on these typed API/snapshot contracts.
