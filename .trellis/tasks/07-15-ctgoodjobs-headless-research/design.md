# CTGoodJobs Headless Viability Research Design

## Purpose and boundary

This task produces reproducible evidence and a Markdown recommendation about
whether CTGoodJobs can crawl routinely without a visible browser. It does not
change the production crawl-mode contract, production scraper behavior, proxy
policy, challenge handling, or persistence path.

The implementation boundary consists of a research-only probe, ignored runtime
evidence, deterministic tests for the probe contract, and a committed report:

- `backend/scripts/ctgoodjobs_headless_probe.py` — bounded experiment CLI;
- `backend/runtime/ctgoodjobs-headless-research/<run-id>/` — ignored, sanitized
  evidence (`manifest.json` and `observations.jsonl`);
- `backend/tests/test_ctgoodjobs_headless_probe.py` — offline contract tests;
- `docs/research/2026-07-ctgoodjobs-headless-viability.md` — final report.

If implementation reveals that a smaller existing script can provide the same
reproducibility and safety contract, it may be reused instead of adding the new
CLI. The report and evidence schema remain required.

## Existing seams and constraints

- Product mode normalization currently supports only headed CTGoodJobs and
  upgrades a requested legacy headless mode to headed
  (`backend/app/crawl_modes.py:6-19`). The probe must therefore control the
  actual transport directly; passing `--crawl-mode headless` to the production
  CLI is not an experiment.
- `CTGoodJobsBrowserPageScraper` launches a persistent context with
  `headless=False` (`backend/app/scraper/ctgoodjobs_browser_page_scraper.py:247-304`).
  The research probe must not change this production adapter merely to create a
  comparison.
- Plain HTTP listing acquisition already exists through
  `fetch_category_page_html()` (`backend/app/scraper/ctgoodjobs/list_scraper.py:28-59`).
- Existing category and detail parsers are the content-validity oracle. A
  successful navigation or HTTP 200 is not a successful observation.
- `classify_ctgoodjobs_detail_page()` deliberately recognizes only explicit
  terminal evidence (`backend/app/scraper/ctgoodjobs/page_state.py:115-150`). A
  WAF/interstitial response is an access block, never `terminal_unavailable`.
- Runtime evidence is written below the already ignored `backend/runtime/`
  tree. Raw response bodies and browser state never enter git.

## Candidate transports

The CLI treats these as separate experimental arms:

1. `plain-http`: a fresh bounded HTTP client using the existing document-fetch
   behavior and no browser state.
2. `fresh-headless`: a newly created Playwright headless browser/context for
   every observation, with no state reused between requests.
3. `stateful-headless`: a headless persistent context reused only within an
   explicitly identified experiment session. No cookie or profile content is
   exported.
4. `headed-baseline`: the same Chromium engine and comparable profile/session
   lifecycle with visibility enabled.

The browser arms use the same engine/channel, navigation timeout, URL sample,
ordering, parser, and pacing wherever possible. Visibility and session reuse are
changed independently so the report does not attribute a session effect to
headless mode.

Undocumented first-party data endpoints may be an additional research lead, but
they are recorded separately from these four arms. They are not promoted to the
recommended architecture unless they meet PRD R1's repeatability, no-secret,
failure-detection, and fallback criteria.

## Experiment sequence and request budget

The live sequence is fail-closed and intentionally bounded:

1. Run offline tests and print the exact proposed budget without network access.
2. Select three public category URLs and derive ten currently valid detail URLs
   from parser-valid baseline listing results; do not hard-code private data.
3. For each candidate arm, test listing discovery three times for each of the
   three categories (maximum 9 listing observations per arm).
4. Test ten valid detail URLs twice (maximum 20 detail observations per arm).
5. Browser-state arms use at least two independently created sessions/profiles.
6. Stop the entire run immediately on a positive verification/manual-action
   state. The arms share one network, so continuing another arm would add traffic
   after a confirmed block and weaken the causal evidence. Do not automate a
   challenge. Partial evidence remains valid conditional evidence.

The theoretical maximum is 29 page observations per arm and 116 across four
arms, excluding a small explicitly reported setup/warm-up allowance. The CLI
must expose lower per-run limits so execution can be split safely. Cooldown,
timeouts, and the actual count are recorded in the manifest.

## Observation contract

Each JSONL observation has a version and records only what is needed to replay
the conclusion:

- run ID, observation ordinal, timestamp, candidate arm, phase (`listing` or
  `detail`), session label, repetition, and category/job sample label;
- sanitized URL origin/path (query values removed or allow-listed), final origin
  and path, HTTP/navigation status, attempt count, elapsed time, and response
  body SHA-256;
- access classification (`valid_content`, `verification_block`,
  `terminal_unavailable`, `transport_failure`, or `structural_invalid`);
- listing job-ID count and parser errors, or detail identity/coverage presence and
  parser errors;
- bounded, enumerated failure reason with no raw exception message.

`manifest.json` records schema version, command options, selected arms (which
encode headless/stateful behavior), browser engine/channel, budget, cooldown,
artifact file hash, completion state, and sanitized limitations. Unknown schema
versions or hash mismatches fail verification. A hard stop preserves the
verified observation prefix and records why later observations are absent.

Never export raw HTML, response JSON, cookies, local/session storage, headers
containing secrets, storage-state paths, profile paths, CDP endpoints, proxy
credentials, query tokens, or unrestricted exception text. The report may cite
artifact run IDs and aggregate counts, not sensitive values.

## Classification and metrics

For each arm and phase the report calculates separately:

- transport/classification success;
- valid listing-ID or valid-detail yield;
- verification-block rate;
- explicit terminal-unavailable count/rate for details; and
- true transport/parser failure rate.

An arm is operationally viable only if it meets the full PRD R2 threshold and has
zero silent bad-data observations. Otherwise the verdict is `technical only`,
`conditional`, or `not viable` with the limiting evidence stated explicitly.

## Report structure

The report contains: executive verdicts (routine operation, recovery, listing,
detail), tested environment and timestamp, code/history findings, experiment
matrix, first-party endpoint findings, metrics, causal claims and unknowns,
recommended operating model, fallback/stop behavior, smallest follow-up
implementation, risks, and artifact/source citations.

## Compatibility, rollback, and operations

- Production behavior remains unchanged, so rollback is removal/reversion of the
  research CLI/tests/report only.
- Live probing requires explicit operator confirmation at execution time and may
  pause for manual challenge completion. Planning approval is not live-probe
  approval.
- If the current network is blocked before controlled comparison begins, preserve
  the sanitized prefix, report the result as conditional, and do not increase
  traffic to force a conclusion.
- Any future production change is a separate Trellis task driven by this report.
