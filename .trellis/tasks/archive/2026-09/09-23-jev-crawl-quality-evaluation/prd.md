# Jev phase 3B: crawl-content quality evaluation

## Goal

Determine whether bounded Jev decisions can identify unusable or suspicious
crawl content that passes transport/parsing boundaries, while leaving every
Job, CrawlJob, listing row, retry state, and manual-action state unchanged.
The deliverable is a reproducible offline evaluation and a
proceed/defer/inconclusive recommendation, not an automatic repair workflow.

Parent: `09-23-research-jev-use-cases` / GitHub #62. The user authorized
automatic crawl-quality flags, does not want to label an evaluation batch, and
requested small-step tests plus final end-to-end verification.

## Confirmed facts

- Shared deterministic access evidence already identifies `ip_blocked` and
  `waf_challenge`; OfferToday additionally has typed response-policy outcomes,
  CTGoodJobs has strict terminal-unavailable page-state evidence, and JobsDB
  repair currently treats a missing or `<250` character description as
  degraded.
- `CrawlJobListing` stores source identity plus listing/detail payload/status,
  but there is no existing semantic crawl-quality flag model or UI contract.
- Existing repair, resume, reset, dispatch, and manual-browser services have
  production side effects and are forbidden from this evaluation path.
- Existing controlled fixtures do not cover login walls, truncation, or
  listing-template-as-detail. Phase 3B must construct and hash explicit
  bilingual examples for those gaps.
- OpenRouter Jev is operational. The shared USD 10 ledger currently records
  402 spent microdollars, 350,000 uncertain reserved, and 9,649,598 remaining.

## Requirements

- R1: Add versioned explicit-answer fixtures across JobsDB, CTGoodJobs, and
  OfferToday; English, Traditional Chinese, and mixed language; valid detail,
  empty/too-short, login wall, WAF/challenge, terminal unavailable, listing
  template, truncated content, irrelevant/template-heavy content, and missing
  evidence. Connected variants may not leak across development/held-out.
- R2: Compare existing deterministic source checks with a bounded candidate
  seam. Known access blocks and terminal unavailable states remain
  deterministic and must not require Jev. Jev evaluates only structurally
  successful but semantically uncertain content.
- R3: Ask one bounded decision with outcomes
  `usable_job_detail|quality_problem|insufficient`. Separately ask a bounded
  problem kind only when needed: `empty_or_short|access_wall|terminal_page|`
  `listing_or_template|truncated|irrelevant|other|insufficient`.
- R4: Preserve source identity, evidence hash, source/deterministic
  classifications, model/rubric, full probabilities, latency, usage, cost, and
  safe technical status. Non-answers remain undecided.
- R5: Freeze gates before held-out execution. Report deterministic baseline
  recall, candidate recall, quality-problem precision/recall, usable-detail
  false-flag rate, actionable coverage, problem-kind accuracy, option-order
  stability, technical failure, source/language strata, latency, tokens, and
  cost.
- R6: Use the persistent allowance and pre-dispatch reservations. Stop on
  ambiguous failure. Offline validation, baseline, export, and report are free.
- R7: Do not write CrawlJob, CrawlJobEvent, CrawlJobListing, Job, repair state,
  manual-action state, outbox, browser state, or product quality flags. Do not
  call repair/resume/reset/dispatch/manual-browser services.
- R8: Do not store credentials, cookies, auth state, raw headers, response
  bodies, contact data, or challenge content. Artifacts use minimized evidence
  excerpts plus hashes.

## Frozen evaluation gates

- Controlled candidate recall >= 0.95.
- Answered quality-problem precision >= 0.95.
- Quality-problem recall over every eligible problem case >= 0.90.
- False-flag rate over valid usable details <= 0.02.
- Actionable coverage over all eligible held-out cases >= 0.70.
- Answered problem-kind accuracy >= 0.90.
- Technical failure rate <= 0.05.
- Option-order stability >= 0.95.
- Real release evidence requires independently reviewed English and
  Traditional-Chinese slices; otherwise the result is `inconclusive`.

## Acceptance criteria

- [x] AC1: Strict, hashed, leakage-safe controlled fixtures cover all required
  sources, languages, content classes, and positive/negative cases.
- [x] AC2: Deterministic classifications are kept out of paid Jev work, and the
  candidate policy retains uncertain quality cases with bounded ordering.
- [x] AC3: Typed Jev receipts and full-denominator metrics pass focused tests,
  including false-flag, non-answer, low-coverage, and stability cases.
- [x] AC4: A minimized read-only real snapshot can be exported and replayed
  without product writes or sensitive content.
- [x] AC5: Bounded development then held-out runs respect the persistent budget
  and produce a proceed/defer/inconclusive report.
- [ ] AC6: Focused tests, complete Jev regression, lint/format/compile, secret
  scan, artifact replay, PostgreSQL read-only integration, and scoped diff check
  pass. Broad project/browser E2E remains required at final roadmap integration.

## Out of scope

- Persisted product quality flags or a new review UI.
- Automatic repair, retry, resume, reset, crawl dispatch, Job mutation, or
  manual browser actions.
- Replacing source-specific access/terminal-page classifiers with Jev.
- Treating current repair heuristics, existing statuses, or another model as
  independently validated semantic truth.
