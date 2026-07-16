# Make manual crawl cancellation reliable

## Goal

Make Cancel permanently stop the actual manual crawler for both listing and
detail phases, while preserving completed work and truthful recovery state.

## Requirements

- Use `cancelling` / `crawl.cancel_requested` until execution stop is confirmed,
  then `cancelled` / `crawl.cancelled`.
- Cover queued, dispatching, running, and manual-action-required manual tasks.
- Disable repeated UI action while cancelling; make backend cancellation
  idempotent.
- Check cancellation before every new listing/detail request and at least once
  per second during controlled sleeps.
- Let an in-flight request finish, but prevent the next request.
- After 30 seconds without cooperative exit, terminate the entire process tree
  and confirm exit before acknowledging cancellation.
- Persist execution-generation ownership and recover supervision after an
  API/backend restart. Verify generation/process identity before signalling; PID
  reuse must be safe.
- Prevent started/completed/failed/manual-action transitions from overwriting
  cancelling/cancelled.
- Preserve committed/staged work. Mark listing incomplete/partial where
  appropriate and return orphaned detail-running rows to an eligible state.
- Cancelled tasks cannot Resume.
- Scheduled crawls are excluded.

## Acceptance Criteria

- [ ] Cancelling a queued or paused task with no live execution reaches
      `cancelled` without launching/relaunching a worker.
- [ ] Cancelling a running listing or detail task prevents all later outbound
      requests and acknowledges only after process exit.
- [ ] A non-cooperative worker is force-stopped as a process tree after 30
      seconds.
- [ ] API/backend restart during cancellation resumes supervision and cannot
      mistake an unrelated reused PID for the CrawlJob execution.
- [ ] Concurrent cancel/launch/worker-completion races cannot resurrect or
      incorrectly complete the task.
- [ ] Completed/staged output survives; partial listing truth and future detail
      eligibility are preserved.
- [ ] Cancel/Resume visibility and status filters match the lifecycle contract.
- [ ] Focused state-machine, launcher, worker, snapshot, API, and frontend tests
      pass.

## Dependencies

- This child is the release prerequisite for detail pacing.
- It does not depend on the pacing table or Settings UI.
