# Implementation plan

1. Load crawl-control, scraper, source-catalog, backend error-handling, and
   frontend task-control specs. Re-run the real stale regular `SingletonLock`
   reproduction as the red feedback loop.
2. Add table-driven regression tests for raw and wrapped ProcessSingleton,
   singleton-marker, legacy closed-context, and unrelated launch errors.
3. Extract the source-neutral profile manager with task/operation/fixed
   ownership, containment-safe allocation, liveness adapters, reset rules, TTL
   orphan reaping, and terminal cleanup. Keep JobsDB green after this step.
4. Add CTGoodJobs task-owned and catalog-operation profile allocation. Verify
   concurrent owners resolve to distinct paths and fixed profiles are never
   deleted by automatic cleanup.
5. Thread CTGoodJobs `crawl_mode` through supported-mode resolution, request
   validation, query-target/runtime contracts, dispatch, CLI, catalog adapter,
   and browser scraper. Retain headed as the rollout default initially.
6. Implement CTGoodJobs launch classification and one safe resume-time
   stale-profile reset/retry. Preserve backlog snapshots, scope, completed
   targets, crawl limits, and explicit `reuse_open_browser` behavior.
7. Extend manual-action normalization, Reset API/service, helper capability
   projection, and structured diagnostics to CTGoodJobs through shared
   contracts.
8. Update Task Details and API decoders/tests for capability-gated Reset,
   Fresh, Open Browser, and Reuse actions. Remove ambiguous generic recovery
   only where the normalized projection supplies explicit choices.
9. Add lifecycle tests for terminal task cleanup, catalog `finally` cleanup,
   crash/orphan TTL cleanup, live/dead/unknown liveness, helper unavailability,
   and second-launch failure.
10. Run automated validation. At minimum:
    - targeted browser/profile and cross-source recovery pytest files;
    - source-catalog, dispatch-plan, versioned-runtime, and checkpoint tests;
    - backend compile/type/lint checks available in the project environment;
    - frontend ESLint, Vitest, and production build.
11. Run live CTGoodJobs canaries in order: catalog validation, one bounded
    listing target, then a bounded detail sample. Record mode, profile ownership,
    classification, and parser-valid outcome without storing sensitive URLs or
    session data.
12. Flip the CTGoodJobs default to headless only if every live canary passes.
    Otherwise retain headed, record the blocker, and leave rollout incomplete.
13. Run `trellis-check`, update executable specs with the source-neutral
    ownership and rollout contracts, commit, and finish the task.

## Completion record

- Shared profile-lock/profile-ownership tests passed, including configured-root
  containment, traversal rejection, symlink rejection, zombie liveness, and
  task/operation cleanup.
- Relevant backend integration gate after the containment fix: 67 passed.
- Full backend gate with the required read-only frontend fixture mount:
  479 passed, 161 skipped. A bare backend container run has two environment-only
  fixture failures because Compose does not mount `/frontend`; no source test
  failed when the declared fixture path was present.
- Frontend: complete Vitest 231 passed; complete ESLint passed; production Vite
  build passed.
- Python Ruff, compileall, and `git diff --check` passed.
- Live rollout: fresh/stateful headless listing and detail returned parser-valid
  content; published CTGoodJobs catalog smoke passed in headless mode; operation
  profile terminal cleanup was observed. The bounded research artifact exits 3
  only because its sample is below the full research viability threshold.

## Risky seams and rollback points

- Mode normalization and versioned query-target contracts can invalidate old
  plans; keep backward-compatible decoding and test legacy headed payloads.
- Moving the JobsDB module can break imports or subtly alter cleanup paths;
  make extraction a behavior-preserving checkpoint before CTGoodJobs changes.
- Catalog validation lacks a crawl job lifecycle; ensure operation cleanup is
  exception-safe before enabling it by default.
- Profile deletion is the destructive boundary. Require containment and
  ownership proof in addition to liveness before any recursive deletion.
- The default-mode flip is the final, separately reversible change. It must not
  be bundled conceptually with the safety primitives.

## Pre-start review gate

- Confirm the current JobsDB task is completed or intentionally paused before
  starting this task.
- Confirm a live CTGoodJobs canary environment and operator are available;
  otherwise do not promise the default-mode acceptance criterion can close.
- Recheck dirty-worktree overlaps before editing mode contracts, recovery
  services, README, or Task Details.
