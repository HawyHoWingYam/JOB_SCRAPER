# Implementation plan: Cross-source OfferToday keyword evidence

## 1. Lock inputs and safety boundaries

- [x] Re-read the PRD/design, archived OfferToday review, database contract,
      source-classification contract, and keyword-review contract.
- [x] Record database counts/date/language/path baselines for JobsDB and
      CTGoodJobs and fingerprint the OfferToday catalog before analysis.
- [x] Confirm the six JobsDB rows without `jobsdb:6281` root evidence are
      excluded and all included rows satisfy the detail-completeness predicate.

## 2. Extend the deterministic analyzer

- [x] Generalize the Job loader/profile seam to accept exact source-site and
      source-qualified root identities without weakening OfferToday behavior.
- [x] Add cross-source snapshot/comparison output while reusing normalization,
      matching, snippets, path reconstruction, and deterministic sorting.
- [x] Keep OfferToday Keyword Entry loading, normalization, recommendation, and
      probe logic source-specific.
- [x] Enforce PostgreSQL read-only transaction, timeout, rollback, and close for
      all cross-source corpus reads.

## 3. Discover and curate candidates

- [x] Produce a bounded deterministic vocabulary inventory from all 3,559
      JobsDB and 3,178 CTGoodJobs in-scope Job Details.
- [x] Curate `research/cross-source-candidates.csv` with rationale and explicit
      rejection of generic/noisy vocabulary.
- [x] Measure every candidate against JobsDB, CTGoodJobs, the archived
      OfferToday corpus, the current pack, and the prior candidate list.
- [x] Inspect representative Job evidence and assign recall/noise/overlap risk.
- [x] Re-evaluate the prior 15 additions, `pentest`, and `angular` using the
      added cross-source evidence without treating it as OfferToday causality.

## 4. Confirm OfferToday contribution and report

- [x] If new candidates qualify, run a fresh paced no-write OfferToday probe
      with at most 30 candidates, two pages each, and 60 listing API requests.
- [x] Hard-stop on auth/WAF/IP/cursor/session/identity/transport failure and
      persist only sanitized evidence.
- [x] Compare with archived OfferToday native/current-pack samples while
      stating timestamp and sampling limitations.
- [x] Generate the cross-source report with per-source counts/examples,
      dispositions, recall benefit, risk, prior-recommendation re-evaluation,
      and an explicit revised or unchanged verdict.
- [x] Route any accepted future mutation through a separate CSV
      preview/confirm operation.

## 5. Verify

- [x] Add regression tests for exact source-root inclusion, multi-path distinct
      counting, exclusion without root evidence, source-specific support,
      dispositions, deterministic output, and the fresh probe hard cap.
- [x] Run focused review and OfferToday listing-runtime tests.
- [x] Run Ruff and `compileall` on touched Python.
- [x] Generate JSON twice and compare byte-for-byte.
- [x] Scan generated artifacts for secret-bearing keys/raw response data.
- [x] Compare Job counts and the complete OfferToday catalog with their
      pre-analysis snapshots to prove no database mutation.
- [x] Run `git diff --check` and review the task-only diff.

## Risk and rollback points

- Stop if exact source-root membership cannot be enforced without label
  inference.
- Stop if the PostgreSQL transaction is not read-only.
- Stop live probing before request 61 or immediately on a hard-stop signal.
- Downgrade rather than promote terms when OfferToday evidence is missing,
  partial, temporally incomparable, or noisy.
- Rollback is file-only; database rollback should never be necessary.
