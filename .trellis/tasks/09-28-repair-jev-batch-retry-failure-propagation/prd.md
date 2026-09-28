# Repair Jev batch retry and failure propagation

## Goal

Make manually started Jev operation batches report the real provider outcome,
retry only genuinely failed work, and safely continue the stopped production
batch `8dfa61d9-f055-4dc9-88d3-a27fd5d5171f` without repeating successful or
intentionally skipped work.

## Background

- The affected batch was cooperatively stopped on 2026-09-28 with no running
  provider work. Its durable snapshot was 42,676 completed, 3,387 failed,
  8,964 skipped, and 10,091 stopped operation items.
- Skills retry currently resets only the outer operation item. The underlying
  `jev_online_skill_classifications` record remains terminal
  `unavailable/http_403`, so execution reuses the old failure without sending a
  new provider request (`backend/app/services/jev_online_skill_store.py:39-41`,
  `backend/app/services/jev_online_skill_runner.py:51-53`, and
  `backend/app/services/jev_skill_backfill.py:179-186`).
- Possible same vacancy currently marks the outer operation item completed
  after executing a bounded run without checking whether that run finished as
  `completed_with_failures` (`backend/app/services/jev_operation_batch.py:571-590`).
  The affected batch contains 11,797 such false-completed duplicate items.
- Related Jobs already creates new work after a failed evaluation and checks
  the terminal evaluation status. It demonstrated that the provider recovered:
  the current retry produced thousands of new answered responses after an
  initial small group of 403 responses.
- Jev provider work is manual-only. Deploying code, reconciling persisted state,
  or restarting services must not start or resume provider work.

## Requirements

### R1. Genuine Skills failed-item retry

- Retrying a failed outer Skills operation must create or prepare an executable
  underlying Skills attempt instead of reusing a terminal unavailable/invalid
  classification as though it were a fresh result.
- A successful, unchanged Skills classification remains reusable and must not
  be sent to the provider again.
- The new attempt must retain durable lineage/history and continue to use the
  shared Skills dispatch builder, frozen request fingerprint semantics, current
  runtime credential validation, and secret-safe receipts.
- One explicit outer retry action authorizes only the selected failed work. It
  must not turn into force reevaluation of unrelated completed or skipped work.

### R2. Truthful Possible same vacancy outcome

- The outer duplicate operation may be completed only when its bounded Jev run
  reaches a successful terminal state, or when there was no provider work to
  perform because every candidate was already current or no candidate existed.
- A duplicate run with failed items must propagate a stable, secret-safe error
  to the outer operation item; it must not be counted as completed.
- Candidate-level successful receipts and persisted duplicate associations must
  remain intact when sibling candidates fail.

### R3. Reconcile and continue the stopped batch safely

- Provide an idempotent reconciliation path for legacy duplicate outer items
  that are marked completed while their referenced bounded runs contain failed
  items. Reconciliation must not call the provider.
- Apply reconciliation to batch
  `8dfa61d9-f055-4dc9-88d3-a27fd5d5171f`, then retry the genuinely failed
  Skills and duplicate work and resume the 10,091 stopped items only after the
  code and tests pass.
- Preserve completed Related Jobs, successful Skills classifications,
  successful duplicate candidate receipts, and all intentional skipped items.
- Recovery must be operator-initiated and observable. It must not be triggered
  by application startup, page load, polling, Settings save, or deployment.
- Before dispatch, report the reconciled counts. After dispatch begins, verify
  that new Skills provider attempts are being created and that outer duplicate
  status agrees with the underlying run.

### R4. Regression coverage and operational clarity

- Backend tests must cover terminal Skills provider failure followed by a real
  manual retry and success, without re-dispatching unchanged success.
- Backend tests must cover successful, empty/no-work, partially failed, and
  wholly failed duplicate runs and their outer batch status.
- Tests must cover idempotent legacy reconciliation and preservation of stopped,
  skipped, and unrelated completed work.
- Existing Stop/Resume/manual-start contracts and the absence of automatic Jev
  execution must remain intact.

## Acceptance Criteria

- [ ] Retrying an outer Skills item whose saved classification is
      `unavailable/http_403` produces a new provider attempt and can transition
      the item to completed after an answered response.
- [ ] Retrying failed work does not send unchanged successful Skills items or
      intentional `missing_skill_evidence`/`successful_unchanged` skips again.
- [ ] A Possible same vacancy bounded run with one or more failed items no
      longer produces an outer completed item.
- [ ] A successful or no-work Possible same vacancy operation still completes
      normally and preserves existing associations/receipts.
- [ ] Legacy false-completed duplicate items are reconciled idempotently without
      provider calls, including the affected batch's 11,797 known items.
- [ ] The affected batch remains stopped throughout implementation and testing;
      after verification, an explicit recovery action resumes only genuine
      failed and stopped work.
- [ ] New Skills provider-attempt timestamps prove retry dispatch occurred after
      recovery, while previously successful operation items retain their prior
      receipts and attempt counts.
- [ ] Batch counters and Job Detail Jev operation states agree with underlying
      terminal outcomes after recovery begins.
- [ ] Targeted backend tests, the relevant broader backend test set, formatting,
      type/lint checks used by this package, and `git diff --check` pass.

## Out of Scope

- Changing OpenRouter/Jev API Console monetary limits or recreating those limits
  locally.
- Automatically retrying provider failures without an explicit operator action.
- Reprocessing successful unchanged work solely to obtain a newer receipt.
- Redesigning the Jev Operations page beyond any status/error wording required
  to expose truthful outcomes.
