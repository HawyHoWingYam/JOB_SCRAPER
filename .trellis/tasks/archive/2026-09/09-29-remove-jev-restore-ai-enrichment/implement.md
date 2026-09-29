# Implementation Plan: Remove Jev and unify Job AI Enrichment

## Delivery strategy

This is one coordinated full-stack cutover, not a collection of independently
deployable child tasks. The backend contract, persistence model, read path,
frontend, retired products, and authoritative database must move together
because old clients and old workers are intentionally unsupported after the
cutover.

Implementation remains test-first at each behavior boundary. Keep the
authoritative database untouched until the replacement code passes targeted
tests, the temporary preflight has classified every removable or preserved
record, all legacy writers are stopped, and the normal database backup has
been acknowledged.

## Phase 0 — Establish the safety baseline

- [ ] Re-read `prd.md`, `design.md`, the current backend/frontend Trellis specs,
      and the repository workflow before editing product code.
- [ ] Capture `git status`, preserve unrelated user changes, and confirm the
      superseded Jev repair task remains archived and issue #83 remains closed.
- [ ] Inventory every tracked, live case-insensitive `jev` reference and every
      Classification/Skill-review entry point. Save the deletion/edit manifest
      in task-local notes so the final zero-reference scan has a fixed baseline.
- [ ] Record the current authoritative schema inventory and counts for all
      fifteen `jev_*` tables and the two `classification_batch_*` tables using
      read-only queries only.
- [ ] Confirm no Jev operation or stopped Jev batch will be resumed during this
      task. Do not send any Jev provider request.
- [ ] Run the existing focused AI Enrichment, taxonomy, recommendation, and Job
      Detail tests to distinguish pre-existing failures from task regressions.

Rollback point: no database or product mutation has occurred; discard only
task-owned edits if planning assumptions prove wrong.

## Phase 1 — Define the unified enrichment contract with failing tests

- [ ] Add extractor/service tests proving one ordinary provider call receives:
      Job evidence, active governed Skill choices, and a frozen set of at most
      ten deterministic Related Jobs candidates.
- [ ] Add strict response-contract tests for the four required sections:
      `summary`, `experience`, `skills`, and `related_jobs`.
- [ ] Cover every Skill disposition: `match_existing`, `unresolved`, `generic`,
      and `rejected`. Reject unknown/inactive governed Skill codes and any shape
      that could implicitly create a taxonomy node.
- [ ] Cover Related Jobs validation: zero candidates, zero selections, one to
      five valid selections, duplicate IDs, invented IDs, more than five IDs,
      and malformed/missing reasons.
- [ ] Prove malformed or missing required sections fail before ORM mutation and
      preserve the prior summary, experience, Skill projection, Related Jobs
      snapshot, and manual evidence freshness state.
- [ ] Prove a successful response persists every output with one final commit,
      and any validator/projection/persistence exception reaches the existing
      rollback path.
- [ ] Prove protected operator-authored Skill decisions survive a later unified
      enrichment.

Review gate: the tests must encode the provider-neutral contract and contain no
new Jev compatibility behavior.

## Phase 2 — Add provider-neutral Related Jobs snapshot persistence

- [ ] Add ORM models and schemas for `job_related_jobs_snapshots` and
      `job_related_jobs_snapshot_items` with the keys, ordering uniqueness,
      foreign-key deletion behavior, timestamps, and provenance described in
      `design.md`.
- [ ] Register the new tables in model exports and empty-schema bootstrap.
- [ ] Add model/database tests for one snapshot per source Job, at most five
      ordered items at the service boundary, cascade behavior, and safe
      replacement of child rows.
- [ ] Implement snapshot replacement in the same SQLAlchemy session used by
      `AIEnrichmentService.enrich_job()`; do not commit inside the snapshot
      helper.
- [ ] Store only stable target IDs, position, concise reason, evidence hash,
      and internal provenance. Do not copy mutable Job display fields or expose
      provider receipts through product schemas.

Rollback point: new tables are additive in code and bootstrap; the
authoritative database has not yet been cut over.

## Phase 3 — Implement the single ordinary AI request

- [ ] Freeze candidates with
      `JobRecommendationService.recommend_for_job(job.id, limit=10)` before the
      provider call and pass that exact candidate evidence into
      `JobInsightExtractor`.
- [ ] Extend the prompt/response normalizer to return the four-section unified
      payload in one `generate_json()` call. Do not add a second provider call
      or a feature-specific provider profile.
- [ ] Introduce strict domain validation before mutation; replace permissive
      defaults that would turn a malformed required section into a successful
      empty value.
- [ ] Replace the projection input's legacy `jev_route` vocabulary with the
      provider-neutral Skill disposition contract.
- [ ] Keep unresolved terms as internal, non-searchable candidate-backed
      evidence; never create a governed Skill node automatically.
- [ ] Atomically write Job insights, Skill mentions/assignments, Related Jobs
      snapshot, and manual evidence freshness before the existing single
      commit.
- [ ] Preserve ordinary run preview, Start, Stop, Retry failed, item status,
      monitoring, and History. Remove selectors or correction modes that exist
      only for the retired candidate-review/backfill workflow.
- [ ] Run the Phase 1 tests and focused enrichment-run tests until green.

## Phase 4 — Replace the Related Jobs read contract and Job Detail UI

- [ ] Replace the recommendation API's Jev evaluation read service with a
      provider-neutral snapshot-first service.
- [ ] Return a usable persisted snapshot as `result_source="ai_ranked"`, ordered
      by the saved position and omitting deleted/unavailable targets.
- [ ] When the snapshot is missing, empty, or has no live target, call the
      deterministic recommendation service and return
      `result_source="similarity"` without an AI reason.
- [ ] Prove recommendation reads never instantiate an LLM client or send a
      provider request.
- [ ] Remove evaluation IDs/status, Jev-prefixed scores/reasons, model, request,
      receipt, and cost fields from internal and public schemas.
- [ ] Update Job Detail to render exactly one Related Jobs section with one of:
      `AI-ranked from the latest enrichment`, `Suggested by job similarity`, or
      `No related jobs available`.
- [ ] Remove the actionable Skill Candidate Evidence panel and its public
      compatibility payload while retaining the underlying internal evidence.
- [ ] Update backend API and frontend component tests for snapshot, fallback,
      deleted targets, empty results, and the three exact labels.

## Phase 5 — Remove the Jev and Classification products

- [ ] Delete all Jev-only backend APIs, models, services, workers/runtime
      orchestration, schemas, scripts, tests, and E2E harnesses.
- [ ] Delete Jev Operations, Jev Settings/test action, navigation, pages,
      clients, styles, fixtures, and frontend tests.
- [ ] Remove Possible same vacancy, search reranking, incident triage, crawl
      content-quality advisory, Skill maintenance/backfill, smoke/general runs,
      and every caller/configuration surface unique to them.
- [ ] Delete the Skill-only Classification models, APIs, runtime, adapters,
      frontend page/client/tests, navigation, Dashboard backlog action, review
      Settings, and startup reconciliation owned by that product.
- [ ] Keep canonical taxonomy seeding, ordinary Skill projection, internal
      unresolved evidence, ordinary recommendation generation, and ordinary
      AI Enrichment run controls.
- [ ] Remove all old route registrations, response properties, environment
      variables, runtime settings, container wiring, and compatibility code in
      the same change. Add no redirect or tombstone.
- [ ] Update or remove affected tests as behavior disappears; replacement
      behavior must already be covered before deleting legacy tests.

Review gate: route inventories and generated OpenAPI must contain no retired
Jev or Classification/Skill-review endpoint or payload field.

## Phase 6 — Build and exercise the temporary cutover tool

- [ ] Create a task-owned temporary, manually invoked cutover tool and dedicated
      tests. It must not be imported by application startup, bootstrap, an API,
      scheduler, or worker.
- [ ] Implement a read-only `preflight` that reports table counts, affected Job
      counts, proven automatic decisions, proven operator-approved decisions,
      ambiguous decisions, automatically created aliases proven by exact
      evidence, and preservation invariants without exposing secrets or Job
      content.
- [ ] Use Jev maintenance `applied_changes` plus explicit approval state to
      distinguish automatic maintenance from approved new Skills.
- [ ] Use completed terminal Classification Batch items plus current-record
      provenance/origin links to identify proven automatic outcomes. Treat
      batch completion alone as insufficient proof of the exact current value.
- [ ] Preserve every ambiguous record and every proven human decision. Do not
      infer human/automatic ownership from `operator-decision` alone.
- [ ] Implement `apply --confirm-remove-jev` so it reruns preflight, reverses
      only proven automatic outcomes, restores available unresolved evidence,
      recomputes affected candidate/assignment state, and drops exactly the
      fifteen Jev tables plus two Classification Batch tables.
- [ ] Prove the tool never changes `jobs.ai_enriched_at`, creates an enrichment
      run, resets a Job, or requeues historical work.
- [ ] Test transaction rollback on a forced mid-apply failure and test a second
      apply as a no-op that reports the schema is already removed.
- [ ] Run the tool against an isolated disposable database populated with
      automatic, approved, ambiguous, alias, missing-origin, and already-removed
      cases.

Rollback point: before authoritative apply, delete/rebuild the disposable
database only. Do not use the authoritative backup as a test fixture.

## Phase 7 — Authoritative database cutover

- [ ] Stop and verify stopped every backend, enrichment, scheduler,
      recommendation, and legacy process capable of writing the affected data.
- [ ] Resolve the exact authoritative database target without a broad or
      implicit environment variable and record its non-secret identity.
- [ ] Verify and acknowledge the normal full database backup. Do not proceed
      from preflight to apply without a recoverable backup.
- [ ] Run temporary `preflight`, review all automatic/approved/ambiguous counts,
      and abort if an invariant or expected-table check fails.
- [ ] Run the explicitly confirmed apply exactly once, then run post-cutover
      schema, projection, preservation, and no-requeue checks.
- [ ] Run the apply command a second time to record idempotence/no-op evidence.
- [ ] Save only the secret-safe counts, backup acknowledgement, commands' result
      summaries, and pass/fail invariants in a verification report inside this
      task directory. Do not export Jev rows, prompts, receipts, descriptions,
      or credentials.

Rollback point: after apply, rollback means stopping new code and restoring the
full database backup together with the old application images/commit. Never
run old code against the cut-over schema.

## Phase 8 — Remove the temporary mechanism and update current documentation

- [ ] Delete the temporary cutover tool and every dedicated tool test before
      the final work commit. Confirm no reusable destructive command remains.
- [ ] Remove retired Jev/Classification documentation and update README,
      `CONTEXT.md`, active backend/frontend specs, API descriptions, settings
      documentation, and operational instructions to the unified enrichment
      model.
- [ ] Describe unknown terms as internal `Unresolved Skill Evidence`, not a
      queue or operator workflow.
- [ ] Do not add a permanent ADR containing Jev terminology: the current
      removal task and its verification report are the allowed decision record,
      and an ADR would violate the live zero-reference requirement.
- [ ] Confirm archived tasks/journals and Git history remain untouched as
      historical evidence.

## Phase 9 — Full verification and commit

- [ ] Run targeted backend tests while implementing, then collect and run the
      entire backend suite.
- [ ] Run the entire frontend unit suite, lint, and production build.
- [ ] Run focused browser/E2E coverage for AI Enrichment, Settings, Job Detail,
      navigation, and Related Jobs; confirm no retired page can be reached.
- [ ] Bootstrap an empty disposable schema and verify the two new snapshot
      tables exist and all seventeen retired tables do not.
- [ ] Build/start the relevant containers and smoke-check backend,
      enrichment-worker, recommendation-api, scheduler, and frontend capability
      boundaries without any Jev configuration.
- [ ] Inspect OpenAPI/routes/settings payloads and verify removed endpoints and
      fields are absent rather than deprecated.
- [ ] Run the final tracked-source zero-reference scan, excluding only Git
      history, archived Trellis tasks/journals, this removal task, and its
      secret-safe verification report.
- [ ] Confirm no historical Job was requeued and ordinary future pending/retry
      work uses exactly one provider request per attempted Job.
- [ ] Run `git diff --check`, inspect `git diff --stat` and the complete diff,
      and separate unrelated pre-existing worktree changes from task changes.
- [ ] Update the developer journal, perform the Trellis quality gate/spec
      update, commit the coordinated cutover, and push only if explicitly
      requested by the user.

## Validation commands

Commands may be narrowed during red/green work, but the final gate includes:

```bash
# Backend
python3 -m pytest --collect-only -q backend/tests
python3 -m pytest -q backend/tests

# Frontend
cd frontend && npm test
cd frontend && npm run lint
cd frontend && npm run build

# Repository hygiene
git diff --check
git status --short
```

Fresh-schema bootstrap and container smoke checks follow the repository README
using an explicitly disposable database/volume. Never run the documented
destructive sandbox-reset command against an unresolved or authoritative
database target.

The final zero-reference scan must inspect tracked live source and configuration
case-insensitively while explicitly excluding only:

```text
.git/**
.trellis/tasks/archive/**
.trellis/workspace/**
.trellis/tasks/09-29-remove-jev-restore-ai-enrichment/**
```

The final report records any unrelated baseline failure with its exact command
and output summary; it does not weaken task-specific acceptance criteria.

## Start-review checklist

- [ ] `prd.md`, `design.md`, and this plan agree that only Skills and Related
      Jobs survive under one ordinary AI Enrichment request.
- [ ] There is no unresolved product question or compatibility period.
- [ ] The user understands that the authoritative cutover is destructive,
      requires a verified backup, and has full-backup restoration as the only
      post-apply rollback.
- [ ] The user approves moving the Trellis task from `planning` to
      `in_progress`; task creation and design approval alone do not activate it.
