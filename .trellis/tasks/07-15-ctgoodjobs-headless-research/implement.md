# CTGoodJobs Headless Viability Research Implementation Plan

## Preconditions and review gates

- [x] User reviews `prd.md`, `design.md`, and this plan and explicitly approves
  `task.py start`.
- [x] Before editing, load `trellis-before-dev` for backend and documentation
  conventions.
- [x] Reconfirm git status and preserve all unrelated dirty files.
- [x] Before any live request, show the exact URLs/classes, arm, request budget,
  timeout, cooldown, output directory, and whether a visible browser may open;
  obtain explicit operator confirmation.

## 1. Establish deterministic research contracts

- [x] Add offline tests first for CLI option validation, budget calculation,
  sanitized URL/export behavior, body hashing, observation classification,
  manifest hashing/version rejection, partial hard-stop evidence, and aggregate
  viability decisions.
- [x] Ensure test fixtures contain representative valid listing/detail HTML,
  verification/interstitial HTML, terminal-unavailable HTML, and structurally
  invalid HTML without using live or sensitive responses.
- [x] Run the new focused test module and confirm the intended failures before
  implementing the probe.

Validation:

```powershell
cd backend
pytest tests/test_ctgoodjobs_headless_probe.py -q
```

## 2. Implement the bounded probe

- [x] Add the research-only CLI or prove an existing script satisfies the same
  contract without modifying production crawler behavior.
- [x] Implement `--plan`/dry-run output, explicit arm selection, listing/detail
  limits, repetitions, session count, timeout, cooldown, output directory, and
  an explicit live-confirmation flag.
- [x] Keep plain HTTP, fresh headless, stateful headless, and headed baseline as
  distinct code paths while sharing classification, parser validation, evidence
  export, and aggregation.
- [x] Reuse existing CTGoodJobs parsers and page-state classifiers. Do not copy
  parser logic or weaken terminal/verification distinctions.
- [x] Export only versioned, sanitized `manifest.json` and `observations.jsonl`;
  verify hashes and reject unknown versions.
- [x] Stop on positive verification/manual-action evidence and preserve a
  verifiable partial prefix. Never solve or bypass a challenge automatically.
- [x] Add static/offline first-party endpoint inspection only where it remains
  within PRD R1/R4; label unproven endpoints as leads.

Focused validation:

```powershell
cd backend
pytest tests/test_ctgoodjobs_headless_probe.py tests/test_ctgoodjobs_browser_page_scraper.py tests/test_cross_source_ip_recovery.py -q
python scripts/ctgoodjobs_headless_probe.py --help
python scripts/ctgoodjobs_headless_probe.py --plan
```

Rollback point: revert only the new research CLI/test files if their seam would
require production runtime changes. Revise the plan instead of widening scope.

## 3. Run the controlled comparison

- [x] Record environment, timestamp, engine/channel, network limitations, exact
  budget, and selected public samples without recording secrets.
- [x] Establish parser-valid headed/listing samples, including ten currently valid
  details; replace terminal pages in the valid-detail sample while recording them
  separately.
- [x] Execute listing arms for three categories x three repetitions.
- [x] Execute detail arms for ten valid jobs x two repetitions.
- [x] For browser-state arms, use at least two independent sessions/profiles.
- [x] If blocked, stop rather than increasing retries or traffic. Ask the operator
  for manual action only when the approved workflow permits it.
- [x] Verify the artifact manifest/hash and review aggregate counts before using
  them in the report.

Example command shape (final flags may differ after tests):

```powershell
cd backend
python scripts/ctgoodjobs_headless_probe.py --plan --arm all
python scripts/ctgoodjobs_headless_probe.py --arm all --confirm-live-research
python scripts/ctgoodjobs_headless_probe.py verify --artifact <artifact-dir>
```

Rollback/stop point: live execution is optional evidence collection, not a reason
to change production code. A WAF/manual-action stop produces a conditional result.

## 4. Write and review the report

- [x] Create `docs/research/2026-07-ctgoodjobs-headless-viability.md` using the
  structure in `design.md`.
- [x] Cite current source and commits with exact anchors; cite live findings by
  sanitized artifact run ID and observation/aggregate identifiers.
- [x] Give separate verdicts for routine operation, recovery, listing, and detail.
- [x] State which claims are proven, contradicted, or unknown; do not infer that
  visibility caused a difference when session/profile or time also changed.
- [x] Apply the approved operational threshold exactly. Partial evidence must stay
  conditional.
- [x] Perform an independent review pass against every PRD acceptance criterion,
  cited source anchor, artifact hash, aggregate calculation, sensitive-data
  boundary, and uncertainty statement.

## 5. Full quality gate and handoff

- [x] Run focused tests plus the backend suite required by current Trellis specs.
- [x] Inspect `git diff --check`, `git status --short`, and the scoped diff.
- [x] Run `trellis-check`; resolve failures without touching unrelated dirty files.
- [x] Complete the required spec-update decision. Record a new durable spec only
  if the research introduced a reusable cross-session contract; do not generalize
  an unproven live conclusion.
- [ ] Commit only task-scoped files, then run `trellis-finish-work` and archive the
  task.

Suggested verification commands (refresh through `trellis-before-dev` before
execution):

```powershell
cd backend
pytest tests/test_ctgoodjobs_headless_probe.py -q
pytest -q
cd ..
git diff --check
git status --short
```

## Acceptance mapping

- AC1, AC3, AC5, AC8: Sections 2-4 and the four-arm evidence matrix.
- AC2: Sections 2 and 4 source/history audit.
- AC4: Sections 2-3 bounded versioned artifacts.
- AC6: Section 4 report verdict and recommendation.
- AC7: Section 4 independent evidence and citation review.
