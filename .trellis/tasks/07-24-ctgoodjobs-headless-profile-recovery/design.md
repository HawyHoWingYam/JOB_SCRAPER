# Technical design

## Boundary

The change has two source-facing policies and one shared mechanism:

- CTGoodJobs decides whether a run is routine headless automation or an
  explicit headed/manual recovery attempt.
- JobsDB retains its existing headless-first and manual-fallback policy.
- A source-neutral profile manager owns profile identity, liveness, reset, and
  lifecycle rules for both sources.

The profile manager does not classify WAF responses, choose crawl modes, or
resume tasks. Those decisions remain in source and crawl-control layers.

## Shared profile manager

Move the generic behavior currently housed in
`jobsdb_profile_recovery.py` behind a source-neutral module and vocabulary.
Keep a compatibility import or update all callers atomically so no JobsDB
behavior changes during extraction.

The interface distinguishes three ownership classes:

- `task`: `<configured-root>/tasks/<crawl-job-id>` for crawl execution;
- `operation`: `<configured-root>/operations/<operation-id>` for catalog
  validation and similar non-task browser work;
- `fixed`: the configured root used only for explicit headed verification and
  CDP reuse.

Allocation returns structured metadata containing ownership, path, source,
owner identity, creation time, and cleanup eligibility. User-controlled values
must not be accepted as path segments without normalization and containment
validation.

Liveness combines matching browser-process inspection and live-browser
registry/CDP probing. A reset is allowed only for proven-dead profiles:

- owned profiles may be deleted and recreated;
- fixed profiles retain data and remove only known singleton markers plus stale
  registry state;
- live and unknown results are non-destructive and include a reason.

The allocator lazily reaps expired task/operation orphans. Active and
manual-action tasks remain retained. Terminal task hooks clean task profiles;
catalog validation uses `finally` cleanup, with TTL reaping as crash recovery.

## CTGoodJobs mode contract

Add `headless` as a supported CTGoodJobs mode without a legacy upgrade to
headed. Thread the resolved mode through request validation, dispatch plans,
query-target contracts, runtime plans, CLI, catalog validation, and
`CTGoodJobsBrowserPageScraper`.

The scraper launches persistent Chromium with
`headless=(crawl_mode == "headless")`. It never infers headed mode from the
presence of a fixed profile. `reuse_open_browser` is the only path that attaches
to the explicit headed verification session.

Catalog validation creates a unique operation identity at its orchestration
boundary and passes the allocated profile metadata to the scraper. It does not
borrow a crawl ID or the fixed profile.

## Failure and recovery flow

1. A fresh automatic run allocates its owned profile and launches headless.
2. Wrapped launch errors are classified using stable profile-lock evidence,
   including ProcessSingleton and singleton-marker creation failures.
3. On a resume, the scraper may request one safe reset when ownership is
   temporary and liveness is proven dead.
4. If relaunch fails, or liveness is live/unknown, crawl control records a
   structured `manual_action_required` event and does not retry again.
5. For WAF/IP/human verification, the operator explicitly opens the fixed
   headed profile through Host Helper and resumes with `reuse_open_browser`.
6. The worker attaches to the registered CDP session only for that recovery
   attempt and preserves the run checkpoint.

Profile-lock recognition should be a shared helper with table-driven tests
against raw and `browser_launch.py`-wrapped Playwright messages. Display-server
errors remain distinct from profile locks.

## API and UI

Extend the existing normalized manual-action capability projection rather than
adding CTGoodJobs-only response shapes. Reset responses expose ownership,
liveness, availability, reason, removed markers, and whether the directory was
recreated.

Task Details renders actions only when the projection advertises them. Open and
Reuse require Host Helper/session evidence. Reset requires proven-dead
liveness. Fresh remains an explicit isolated retry. No action silently falls
back to another strategy.

## Compatibility

- Preserve existing resume strategy literals and optional response fields.
- Preserve JobsDB semantics and tests during the module move.
- Do not normalize or mutate historical CTGoodJobs failures.
- Persist profile metadata only in existing request/resume/event JSON fields;
  avoid a schema migration unless implementation proves those fields
  insufficient.

## Rollout and rollback

Land headless support and profile isolation while retaining the headed default.
Run targeted automated coverage, then live canaries for catalog validation,
listing, and detail. Only after all three return parser-valid content without
unexpected verification or structural signals should the default change to
headless.

If a canary fails, keep or restore headed as the default without reverting the
safe shared profile manager or explicit headless support. Capture the failure
classification and environment evidence for a later rerun. A visible browser
is not considered proof that WAF behavior will improve.

## Important trade-offs

- Persistent task profiles cost more disk than ephemeral contexts but preserve
  state across a paused recovery attempt and make ownership explicit.
- A single automatic stale-lock retry improves crash recovery without creating
  an unbounded anti-bot retry loop.
- Keeping manual headed fallback explicit adds operator steps but prevents
  hidden strategy changes and false reports of browser reuse.
- Deferring plain HTTP keeps this task focused on changing visibility and
  profile safety rather than introducing a second transport state machine.
