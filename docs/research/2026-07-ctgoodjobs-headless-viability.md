# CTGoodJobs Headless and Browserless Crawl Viability

Date: 2026-07-16

Tracking issue: [#12](https://github.com/HawyHoWingYam/JOB_SCRAPER/issues/12)

Research task: `.trellis/tasks/07-15-ctgoodjobs-headless-research`

Evidence HEAD before the research changes were committed:
`b0754fea2f255dd5195cc2d1bee2d419175e1ec2`

## Executive verdict

**Yes: CTGoodJobs listing-ID discovery and job-detail extraction can operate
without a routinely visible browser.** In the approved full comparison, plain
HTTP, a fresh Playwright headless browser, a stateful Playwright headless
browser, and the headed baseline each passed all 29 observations assigned to
that arm. All 116 observations returned parser-valid CTGoodJobs content.

The result is bounded, not universal. Before the network change, the headed
baseline itself received an AWS WAF CAPTCHA response. Browser visibility did
not prevent that block. After the network change, all four transports passed
the full comparison. The evidence therefore supports these separate verdicts:

| Decision | Verdict | Reason |
|---|---|---|
| Routine listing-ID discovery | Yes, browserless is viable in an accessible network window | Plain HTTP and both headless arms passed 9/9 listing observations each |
| Routine job-detail collection | Yes, browserless is viable in an accessible network window | Plain HTTP and both headless arms passed 20/20 detail observations each |
| Visible browser required for normal crawling | No | Every non-headed arm met the approved threshold |
| Visible browser sufficient for WAF recovery | No | The pre-change headed baseline was blocked by AWS WAF CAPTCHA |
| Challenge recovery | Keep explicit operator recovery | A positive block must stop the run; network/session recovery, not visibility alone, changed the outcome |
| Undocumented first-party JSON endpoint | Not recommended | No stable job-listing or job-detail API contract was confirmed, and SSR HTML already proved viable |

## Question and decision threshold

The question was not whether a `headless` label could be passed through the
CLI. It was whether the actual listing and detail transports could return
content that the production parsers recognize as valid without a routinely
visible browser.

The approved operational threshold was:

- three public categories, three listing repetitions per category;
- ten currently valid job details, two repetitions per job;
- at least two independently created browser sessions where browser state
  applies;
- zero silently accepted verification or structurally invalid responses; and
- every positive verification response detected and stopped.

A candidate that did not meet this complete threshold remained conditional.

## Current implementation is headed regardless of its label

The current product contract defaults CTGoodJobs to headed, supports only
headed, and upgrades a legacy requested `headless` mode to headed
(`backend/app/crawl_modes.py:6-19`). The standalone CLI still accepts
`--crawl-mode headless` and copies the requested value into its runtime payload
(`backend/scripts/ctgoodjobs_standalone_crawl.py:56-70,98-105`). That label does
not control browser visibility.

Both phases share one `CTGoodJobsBrowserPageScraper`
(`backend/scripts/ctgoodjobs_standalone_crawl.py:945-990`). Listing pages use
that adapter at `backend/scripts/ctgoodjobs_standalone_crawl.py:257-293`, and
detail pages use it at `backend/scripts/ctgoodjobs_standalone_crawl.py:688-718`.
The adapter's actual persistent-context launch passes `headless=False`
(`backend/app/scraper/ctgoodjobs_browser_page_scraper.py:247-304`).

Repository history confirms that this was a product-policy reversal rather
than proof that browser headless could not work. Commit `796ea6d3` temporarily
made CTGoodJobs headless by default. Commit `9115bb7e` restored headed-only
support and added the legacy headless-to-headed upgrade. Neither change carried
a current live comparison artifact.

## Why browserless acquisition is technically possible

The data contract is HTML, not pixels:

- Listing acquisition already has an HTTPX helper
  (`backend/app/scraper/ctgoodjobs/list_scraper.py:28-59`). The parser extracts
  JSON-LD `ItemList` data and normalized `/job/<id>` links
  (`backend/app/sources/ctgoodjobs/parsers.py:440-502`).
- Detail acquisition already has an HTTPX helper
  (`backend/app/scraper/ctgoodjobs/detail_scraper.py:19-49`). The parser reads
  Next.js Flight `jobContent`, JSON-LD `JobPosting`, identity, description, and
  field coverage (`backend/app/sources/ctgoodjobs/parsers.py:505-640`).

The transport must still preserve the existing positive-evidence boundaries.
IP/WAF evidence is classified before parsing, and generic network or parser
failures are not guessed to be IP blocks
(`backend/app/scraper/access_block.py:60-111`). Explicit job unavailability is
limited to HTTP 404/410 or top-level page-state evidence; arbitrary description
text cannot declare a job expired
(`backend/app/scraper/ctgoodjobs/page_state.py:115-150`).

## Research implementation

The research-only CLI is
`backend/scripts/ctgoodjobs_headless_probe.py`. It does not change production
crawl behavior. Its key contracts are:

- bounded plan and request-budget calculation at lines 123-218;
- positive access, terminal state, and production-parser validation at lines
  279-459;
- sanitized artifact export and hash verification at lines 575-728;
- operational-threshold replay and exit semantics at lines 730-825; and
- four-arm live execution with explicit confirmation and immediate hard stop at
  lines 1006-1354.

Offline regression coverage is in
`backend/tests/test_ctgoodjobs_headless_probe.py`. It covers AWS WAF CAPTCHA
headers, valid listing/detail parsing, explicit terminal state, structurally
invalid content, artifact tampering, unknown versions, hard-stop prefixes, the
full threshold, conditional evidence, and the live-confirmation gate.

The evidence schema stores only:

- sanitized CTGoodJobs origin/path;
- status, timing, attempts, transport arm, session label, and repetition;
- access/content classification and bounded failure reason;
- listing counts or detail presence/coverage metrics; and
- a response-body SHA-256.

It does not store HTML, cookies, headers, storage state, profile paths, CDP
endpoints, proxy credentials, tokens, or unrestricted exception messages.

## Live evidence

### Run 1: blocked headed baseline before network recovery

- Run ID: `0192b2dc-30ac-4c38-b035-bf49be5f8a71`
- Observation hash:
  `33eb8cf5db8391acdc5f99f093c8aa345d52ccdd36f7363c2ff746e7fc7f271a`
- Approved ceiling: 8 observations
- Actual: 1 observation
- Result: headed listing received HTTP 405 with
  `x-amzn-waf-action: captcha`
- Classification: `verification_block` / `aws_waf_captcha`
- Outcome: schema-and-hash-valid hard-stop artifact; the remaining seven
  requests were not sent

This disproves the claim that visibility alone prevents CTGoodJobs access
blocking.

### Run 2: bounded smoke after network recovery

- Run ID: `41e931a9-d888-4b1a-b0e5-c4b440990d6b`
- Observation hash:
  `2de7c138c0690704700695a93857010d9e2cedf7e49415dd2706de4c770ae823`
- Actual: 8/8 observations
- Valid content: 7
- Fresh-headless listing: one HTTP 503 transport failure
- Verification/structural-invalid results: 0

This established end-to-end technical viability for plain HTTP and stateful
headless, plus fresh-headless detail viability. Fresh-headless listing and the
overall result correctly remained conditional because the sample was small and
that listing returned HTTP 503.

### Run 3: approved full comparison

- Run ID: `2153efdd-754e-425d-b9a3-d90376d70cd8`
- Captured from 2026-07-16 08:16 UTC
- Observation hash:
  `9b782a029da9e5487628fbf7520f9190554b82b9a2c25db7651d907546111311`
- Artifact verification: valid, zero issues
- Budget/actual: 116/116 observations
- Listing/detail split: 36 listing, 80 detail
- Outcomes: 116 `valid_content`; zero verification blocks, transport failures,
  terminal-unavailable pages, or structurally invalid pages

| Arm | Listing | Detail | Sessions observed | Valid / total | Mean elapsed | Max elapsed | Verdict |
|---|---:|---:|---:|---:|---:|---:|---|
| Headed baseline | 9 | 20 | 2 persistent | 29/29 | 707.0 ms | 1,577 ms | Operationally viable |
| Plain HTTP | 9 | 20 | Stateless | 29/29 | 582.9 ms | 905 ms | Operationally viable |
| Fresh headless | 9 | 20 | 29 fresh contexts (20 unique labels across the phase-local numbering) | 29/29 | 1,483.8 ms | 4,407 ms | Operationally viable |
| Stateful headless | 9 | 20 | 2 persistent | 29/29 | 676.4 ms | 1,469 ms | Operationally viable |

The three listing categories were Accounting/Auditing, Banking/Finance, and
Engineering. Accounting and Engineering returned 33 IDs per observation.
Banking returned 30 or 31 IDs across time and transports. Because that small
variation occurred in every browser shape and plain HTTP, it is consistent with
a changing live listing rather than a visibility-specific parser failure.

All ten detail samples produced usable job ID, title, company identity, and
description in all eight observations per sample. Seven samples produced full
16/16 field coverage. Two produced 14/16 and one produced 15/16 consistently
across every transport. No parser errors were recorded. The identical coverage
distribution across transports indicates source-field availability, not a
headless extraction loss.

## Causal findings

The evidence proves:

1. Chromium visibility is not required to obtain parser-valid listing or detail
   HTML.
2. JavaScript execution is not required for the tested pages because plain HTTP
   passed the same listing and detail threshold.
3. Persistent browser state is not required for the tested accessible window:
   stateless HTTP and fresh headless both passed.
4. Visibility is not sufficient to overcome WAF/IP state: the headed baseline
   was blocked before the network change.
5. The operator's network change coincided with a material access-state change:
   the headed baseline moved from an immediate AWS CAPTCHA to a complete
   four-arm pass. This bounded sequence does not isolate network from time or
   other session conditions.

The evidence does not prove:

- that plain HTTP will remain unblocked across every IP, time window, category,
  or long production census;
- that headless can or should solve a verification challenge;
- that an undocumented JSON endpoint is stable or preferable; or
- that the production mode contract can be changed without a separate canary,
  observability, and rollback task.

## First-party endpoint findings

Current source and history contain no confirmed CTGoodJobs job-search JSON API,
GraphQL contract, or `_next/data` contract. Earlier bounded homepage inspection
found first-party references to `api01.ctgoodjobs.hk/general/api/story` and
`/datacache/snapshot/snapshot-searchJobsData.js`, but neither was shown to be a
job-listing or job-detail contract.

Those references should remain research leads only. The tested SSR HTML path is
already explicit, parser-backed, and reproducible. Promoting an undocumented
endpoint would add schema and failure-detection risk without solving the actual
dependency observed here, which was WAF/access state rather than visibility.

## Recommended operating model

1. **Routine transport:** prototype the existing plain-HTTP listing and detail
   helpers as the primary CTGoodJobs path. They were the fastest tested arm and
   require neither browser visibility nor browser lifecycle overhead.
2. **Validation boundary:** accept a page only after the existing access
   classifier and production parser confirm valid content. HTTP 200 alone is
   never success.
3. **Positive WAF/IP response:** stop immediately and create the existing
   operator-driven manual action. Do not automatically cascade from HTTP to
   headless/headed; that would send more requests from an already blocked
   network and blur the causal evidence.
4. **Recovery:** retain the visible/reusable browser path as an exceptional
   operator recovery tool. It is useful for manual interaction, but it is not a
   routine transport requirement and is not sufficient without an authorized
   network/session.
5. **Product contract:** do not change `crawl_modes.py` in this research task.
   Decide whether the UI should call the routine mode `headless`, `browserless`,
   or `automatic` in the follow-up implementation task; the current word
   `headless` does not distinguish HTTP from a hidden browser.

## Smallest follow-up implementation

Create a separate implementation task linked to issue #12:

1. Add a source-owned CTGoodJobs transport selector behind a reversible feature
   flag; default remains the current browser adapter.
2. Route a bounded listing-only canary through the existing HTTP helper and
   compare parser-valid IDs/counts with the browser path without double-writing
   product data.
3. Extend the canary to detail pages only after listing passes; preserve the
   current terminal-unavailable, manual-action, cancellation, pacing, and
   structured logging contracts.
4. Emit transport name, status/classification, parser result, elapsed time, and
   fallback/stop reason. Never log bodies or secrets.
5. Promote HTTP to routine only after a production-window canary passes; keep a
   one-switch rollback to the existing browser adapter.

## Rollback and safety

This research changed no production runtime behavior. Removing the research CLI,
tests, and report fully rolls it back. Runtime artifacts remain ignored and must
not be committed. Any future product switch must be independently planned,
tested, deployed, and reversible.

## Limitations

- The full run is one bounded time window after one network change. It meets the
  approved threshold but is not a multi-day availability study.
- The artifact manifest verifies schema, observation sequence, sanitized fields,
  and file hash. It does not cryptographically bind the entire git tree. The
  report records the HEAD and artifact hashes used during the run. The executed
  probe source SHA-256 was
  `4df5d97d4ef3c3f5f11ffc59381e519cbe5158a20b82fab13601da1cb6f2c715`.
  After the live run, dry-run reporting was tightened to show the separate
  request-attempt ceiling when retries are configured, and internal failure was
  separated from a valid conditional decision in CLI exit codes. Transport,
  classification, and artifact behavior used by the live evidence were not
  changed.
- Response-body hashes differed because the live pages contain dynamic content;
  conclusions rely on positive parser output and coverage, not byte equality.
- The ten details were selected from the headed baseline's first valid listing
  results. This keeps the target set common across arms but is not a random
  sample of the entire site.
