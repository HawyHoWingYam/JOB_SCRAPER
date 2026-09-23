# QA execution plan

## 1. Readiness gate

- [x] Confirm the browser target is the local sandbox and record frontend,
      backend, database, and branch identity.
- [x] Confirm no active classification run exists and capture candidate counts,
      Skill threshold, and non-secret LLM readiness.
- [x] Confirm Chrome DevTools, Playwright, PostgreSQL, and GitHub connections.
- [x] Create `qa-report.md` in this task directory with a contract matrix and an
      evidence log; do not edit product code.

## 2. Automated regression baseline

- [x] Run the focused UI component test:
      `cd frontend && npm test -- --run src/components/classification/ClassificationBatchesPage.test.jsx`
- [x] Run the core backend batch contract suite:
      `cd backend && pytest -q tests/test_classification_batch_runtime.py`
- [x] Run the broader taxonomy contract suite:
      `cd backend && pytest -q tests/test_current_taxonomies.py`
- [x] Record commands, exit results, and relevant failures in `qa-report.md`.

## 3. UI-driven read-only matrix

- [x] Open the Automated Classification console with Chrome DevTools and record
      initial console/network state.
- [x] For Company Industry, preview all Sources and each individual Source with
      small limits; verify request normalization, counts, and start gating.
- [x] For Skills, verify no Source filter is sent and candidate count follows the
      effective threshold.
- [x] Exercise limit boundaries/invalid input and loading/error presentation
      without creating an oversized run.
- [x] Cross-check preview counts against read-only selection queries where
      practical and record any unreachable empty state as a limitation.

## 4. Real domain processing

- [x] Company Industry: repeat with one to three items and prove any success is
      supported by mapped Source evidence; inspect failures for correct isolation.
- [x] Skills: repeat with one to three items and prove threshold eligibility plus
      alias reuse, generic rejection, or atomic confirmed-path creation according
      to the naturally selected candidates.
- [x] Reload or reopen the page after terminal runs and verify history and
      counts remain consistent.

## 5. Concurrency and cooperative Stop

- [x] Prepare two isolated browser contexts for the same domain before starting
      so the second start can race an active run through the UI.
- [x] Start a run with a requested limit no greater than 20.
- [x] Attempt a second same-domain start and verify the active-run conflict does
      not create a duplicate run.
- [x] While the first run is active, start a one-item run in a different domain
      and verify independent progress.
- [x] Immediately request Stop on the large run and verify stopping, in-flight
      completion, untouched-item cancellation, terminal status, and count sums.
- [x] Record the Stop timing outcome; pending-run Stop remains covered by the
      focused backend test because UI execution starts immediately.

## 6. Failure and Retry

- [x] Inspect every natural failed item and classify it as product, data/model,
      LLM configuration, or provider/network behavior.
- [x] Trigger failed-only Retry from the displayed run and verify lineage,
      candidate set, active-run exclusion, and terminal counts.
- [x] Record the naturally reached Retry paths and avoid manufacturing failures.

## 7. Defect confirmation and reporting

- [x] Reproduce or independently corroborate every suspected product defect.
- [x] File each independent confirmed defect as a concise issue linked to #32,
      including severity, expected/actual behavior, and exact reproduction steps.
- [x] Keep transient or non-reproducible observations in `qa-report.md` only.
- [x] Update #32 with the final matrix summary and links to child defect issues.

## 8. Completion gate

- [x] Ensure `qa-report.md` lists run IDs, contract results, defects, blocked
      scenarios, coverage limitations, and residual risks.
- [x] Verify no product files were modified by the QA pass.
- [x] Run the Trellis quality check appropriate to documentation/QA artifacts.
- [x] Present the final report to the user; fixes remain a separately authorized
      phase.
