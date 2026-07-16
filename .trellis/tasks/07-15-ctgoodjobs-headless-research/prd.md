# Research CTGoodJobs headless crawl viability

## Goal

Determine from first principles whether CTGoodJobs job-ID discovery and job-detail
collection can run without a routinely visible (`headed`) browser, identify the
actual dependency behind the current headed-only product behavior, and deliver an
evidence-backed recommendation rather than treating `headless=False` as the root
cause.

The deliverable is a Markdown research report for this repository. This task does
not authorize a production crawler rewrite.

Tracking issue: GitHub #12, "Research CTGoodJobs headless crawl viability".

## Background and Confirmed Facts

- The product contract currently exposes CTGoodJobs as headed-only and upgrades a
  legacy `headless` request to `headed`
  (`backend/app/crawl_modes.py:6-19`).
- The standalone CLI still accepts `--crawl-mode headless`, propagates that label
  through payloads and logs, and constructs one shared browser scraper for both
  phases (`backend/scripts/ctgoodjobs_standalone_crawl.py:56-70,98-105,945-990`).
  The label therefore does not prove the runtime is headless.
- The runtime launches a persistent Playwright Chromium context with
  `headless=False` regardless of the request payload
  (`backend/app/scraper/ctgoodjobs_browser_page_scraper.py:247-304`). Both listing
  pages and detail pages use this adapter
  (`backend/scripts/ctgoodjobs_standalone_crawl.py:257-293,688-718`).
- CTGoodJobs data is parsed from server-rendered/Next.js HTML rather than from
  pixel output: listing IDs come from category-page payloads, while detail fields
  come from `jobContent` and JSON-LD `JobPosting`
  (`backend/app/sources/ctgoodjobs/parsers.py:180-253,256-285,513-520`). This makes
  a non-headed transport technically plausible if it receives the same valid
  page state.
- HTTPX listing/detail fetch helpers already exist
  (`backend/app/scraper/ctgoodjobs/list_scraper.py:28-49`,
  `backend/app/scraper/ctgoodjobs/detail_scraper.py:19-40`), but the current
  production standalone path does not use them for live page acquisition.
- Current source and repository history contain no confirmed CTGoodJobs job-search
  JSON API, GraphQL endpoint, or `_next/data` contract. The implemented discovery
  path uses category HTML and extracts JSON-LD `ItemList` entries plus `/job/<id>`
  links; the detail path reads Next.js Flight `jobContent` and JSON-LD
  `JobPosting` from page HTML (`backend/app/sources/ctgoodjobs/parsers.py:100-159,
  238-285,479-520`).
- A bounded official-homepage inspection found first-party references to
  `https://api01.ctgoodjobs.hk/general/api/story` and
  `/datacache/snapshot/snapshot-searchJobsData.js`. Neither reference is yet
  evidence of a job-listing or job-detail API contract; their schemas and runtime
  use remain to be tested.
- A bounded 2026-07-15 probe from the current network received an AWS
  CloudFront/WAF CAPTCHA response (`HTTP 405`, `x-amzn-waf-action: captcha`) for
  an ordinary GET, including one Chrome-user-agent request. This disproves
  "plain HTTP works here now" but does not by itself disprove browser-headless,
  session reuse, or a different network/session strategy.
- Historical configuration briefly defaulted CTGoodJobs to headless
  (`796ea6d3`), but no current live-success artifact has yet been found. Existing
  deterministic tests prove parsing and classification with fixtures/mocks, not
  live headless listing/detail viability.
- Recent headed production evidence proves the current path can collect thousands
  of IDs and hundreds of details, while verification/content-anomaly bursts still
  require explicit manual recovery. Visibility alone therefore has not eliminated
  blocking or invalid page states.
- The operator confirmed that the supplied CTGoodJobs expired-page screenshot was
  observed during a headed job-detail crawl. This is direct evidence that a
  visible browser does not prevent legitimate terminal-unavailable outcomes and
  those outcomes must not be conflated with access verification.
- Closed issue #8, "Fix CTGoodJobs verification failure storms and unify
  detail-task metrics", defines three distinct detail outcomes: positive
  verification/access evidence becomes resumable manual action, explicit
  expired/removed/not-found evidence becomes `terminal_unavailable`, and an
  otherwise invalid detail remains a failure unless the structural-anomaly
  circuit breaker pauses the run. The corresponding implementation landed in
  commits `ad950cc0`, `38af8cec`, and `6c49b6b9`.
- The current terminal-page classifier recognizes HTTP 404/410 and the phrase
  `this job has expired`, but for an HTTP 200 page it deliberately searches only
  the document title or an explicitly labelled page-state/alert container
  (`backend/app/scraper/ctgoodjobs/page_state.py:8-17,31-76,115-150`). This
  protects against false positives from ordinary job-description text, but the
  exact live DOM behind the supplied "Sorry, this job has expired" screenshot
  has not yet been captured, so that concrete page is not yet proven to hit the
  classifier.

## Requirements

### R1. Separate the candidate meanings of "without headed"

- Evaluate plain HTTP, a fresh Playwright headless browser, and a stateful
  Playwright headless browser as distinct transports.
- Actively investigate first-party JSON/data endpoints used by the CTGoodJobs
  web application. A direct API/data call is preferred when it has a stable,
  reproducible contract and returns the fields needed by the existing parsers or
  an equivalently explicit schema.
- Undocumented first-party web-application endpoints may be researched and
  prototyped. They qualify for a production recommendation only when they do not
  depend on login credentials or challenge-solving tokens, their response schema
  repeats reliably, failure states are positively detectable, and a supported
  fallback remains available. Otherwise the report must label them as brittle
  research leads rather than production contracts.
- Keep a headed baseline so differences can be attributed to transport rather
  than parser, page, category, job availability, IP, or time drift.
- Do not equate a CLI mode label with the browser's actual launch mode.
- Routine job-ID discovery and detail collection should not require a visible
  browser. A visible browser is acceptable as an exceptional, operator-driven
  recovery step when CTGoodJobs presents a verification challenge.

### R2. Test job-ID and job-detail phases independently

- Job-ID discovery and detail collection must each receive their own result.
- A transport is viable only when it returns valid CTGoodJobs content markers and
  the existing parser produces usable identities/details; navigation success or
  HTTP 200 alone is insufficient.
- Record access state separately from parse quality and persistence/ingest quality.
- Record explicit `terminal_unavailable` separately from verification/manual
  action and from transport/parser/ingest failure when comparing candidate
  transports.
- Score explicit `terminal_unavailable` as a correctly reached and classified
  transport outcome, but exclude it from valid-detail yield. Report transport /
  classification success, valid-detail yield, verification-block rate, and true
  failure rate separately rather than collapsing them into one success rate.
- A candidate transport qualifies as operationally viable only when all of the
  following bounded checks pass:
  - job-ID discovery succeeds for three public categories on three repetitions
    per category;
  - detail collection succeeds for ten currently valid jobs on two repetitions
    per job;
  - the comparison covers at least two independently created browser sessions or
    profiles where the transport uses browser state;
  - no run silently accepts challenge, verification, or structurally invalid
    content as valid data; and
  - every verification block is positively classified and stopped rather than
    ingested.
- A smaller or partially blocked sample may prove technical possibility, but the
  report must keep the routine-operation verdict conditional and must not call
  the transport operationally viable.

### R3. Identify the real dependency

- Distinguish browser visibility from browser engine, JavaScript execution,
  cookies/storage, persistent profile, IP/proxy reputation, request headers,
  timing/behavior, and manual challenge completion.
- State what the evidence proves, contradicts, or leaves unknown. Do not infer
  causation from one headed/headless outcome.
- Prefer the smallest controlled experiment that changes one relevant variable at
  a time.

### R4. Safe and reproducible research

- Use low request volumes, existing public pages, bounded timeouts, and no
  automated CAPTCHA solving, login, evasion, or deliberate block triggering.
- When a challenge requires manual action, pause and ask the operator to complete
  it; do not automate the challenge. Research may then continue with the resulting
  authorized session without persisting its secrets in artifacts.
- Do not persist response bodies, cookies, storage state, profile data, or other
  sensitive challenge material in the report or repository.
- Preserve the existing dirty worktree and do not modify production behavior as
  part of this research task.
- Cite repository source with file/line anchors and external claims with official
  CTGoodJobs responses/pages or other first-party material.

### R5. Actionable report

- Give separate verdicts for routine operation, challenge recovery, job-ID
  discovery, and job-detail collection.
- Recommend an operating model and a minimal follow-up implementation/prototype
  plan, including fallback/stop behavior and observability needed to avoid silent
  bad data.
- Clearly label any conclusion that remains conditional because a controlled live
  comparison could not be completed.

## Acceptance Criteria

- [x] AC1: The report distinguishes at least plain HTTP, fresh browser-headless,
  stateful browser-headless, and headed baseline paths.
- [x] AC2: Current code and historical behavior are documented with verifiable
  source/commit anchors; the false CLI/runtime equivalence is explicit.
- [x] AC3: Listing/job-ID and detail results are reported independently using
  positive content and parser-validity checks.
- [x] AC4: Every live probe has a bounded request budget and records timestamp,
  URL class, transport, status/final state, content classification, parser result,
  and limitations without storing sensitive bodies.
- [x] AC5: The evidence matrix isolates visibility from session/profile and other
  major variables closely enough to support the stated causal claims.
- [x] AC6: The report gives a direct yes/no/conditional verdict, recommended
  architecture, fallback policy, risks, and the smallest next implementation
  experiment.
- [x] AC7: An independent review pass checks the report against the cited source
  lines, probe artifacts, and stated uncertainty before delivery. In Codex
  inline mode, the main session performs this as a separate pass because check
  sub-agents are disabled.
- [x] AC8: Any operationally viable verdict satisfies the approved 3 categories
  x 3 listing repetitions, 10 valid jobs x 2 detail repetitions, two-session
  browser-state comparison, and zero-silent-bad-data threshold; otherwise the
  verdict remains technical or conditional.
