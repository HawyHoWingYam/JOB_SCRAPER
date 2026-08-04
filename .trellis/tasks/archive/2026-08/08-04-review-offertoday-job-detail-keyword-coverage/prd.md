# Review OfferToday job detail keyword coverage

## Goal

Determine whether the current OfferToday Source Classification Keyword Packs
provide sufficient practical coverage. If coverage is sufficient, recommend no
change. If it is insufficient, use retained Job Detail evidence to propose more
useful keywords and identify old terms that can be retired with adequate
evidence, without changing crawl scope or pack contents prematurely.

## Background

- OfferToday Keyword Packs supplement classification-scoped collection; they
  do not replace the operator's selected Source Classification.
- The requested review must use persisted OfferToday Job Detail evidence,
  rather than intuition or keyword popularity alone.
- The current PostgreSQL snapshot contains 1,139 non-deleted published
  OfferToday Jobs. All 1,139 have nonblank title, description, and Company;
  their posted dates span 2026-05-05 through 2026-07-30.
- The corpus is temporally skewed: 994 Jobs (87.3%) carry one of two May posted
  dates, while 145 Jobs cover 2026-07-06 through 2026-07-30. Titles are 727
  Latin-only, 210 Chinese-only, and 202 mixed Chinese/Latin under a simple
  Unicode-script heuristic.
- OfferToday staging contains 5,361 rows for 4,341 distinct source Job
  identities: 1,964 completed, 3,393 pending, and 4 terminal-unavailable.
- All 1,139 published Jobs have a null direct `jobs.source_classification_id`.
  Their source taxonomy evidence is instead preserved in 1,142 non-primary
  Source Classification Paths with 2,284 nodes.
- The ordinary current `offertoday:118000` Information Technology pack has 127
  enabled entries. None currently has `last_run_at`, `last_new_job_ids`, or
  `last_duplicate_rate` evidence populated.
- Current `crawl_job_listings.listing_payload` rows preserve listing facts and
  Source Classification Paths but not `search_family`, the triggering keyword,
  or Query Target identity. The present database therefore cannot directly
  reconstruct native-versus-keyword contribution for the retained cohort.
- The adaptive catalog/workload implementation exists as uncommitted work, but
  its general dispatched-run path does not currently write keyword contribution
  evidence; the standalone crawl is the only discovered writer.

## Requirements

- Identify the authoritative database, Job Detail fields, OfferToday Source
  Classification identities, and current Keyword Pack storage/configuration.
- Profile the usable OfferToday detail corpus, including row counts, detail
  completeness, language mix, date range, and classification coverage.
- Compare current pack terms with vocabulary and job-role themes observed in
  the corresponding classification-scoped Job Details.
- Define and report a practical sufficiency decision using explicit semantic
  coverage, classification-stratum coverage, uncovered-theme, and redundancy
  evidence rather than raw pack size.
- Treat corpus-text findings as discovery evidence, not direct proof of keyword
  query recall or precision, because the current rows lack triggering-query
  provenance and may be conditioned on earlier collection routes.
- Account explicitly for additions, removals, replacements/variants, terms that
  require more evidence, and no-change outcomes even when a category has no
  supported recommendations.
- For every proposed change, report supporting counts and representative Job
  examples, plus likely recall benefit and noise/cross-classification risk.
- Preserve Source-owned classification boundaries and do not infer that a
  shared display label gives two classifications the same identity.
- Do not modify the database, Keyword Packs, or crawl configuration during the
  review phase.
- Optimize for recall with precision guardrails: an addition candidate must be
  supported by at least three distinct relevant Job Details and at least two
  representative examples, rather than a single occurrence or raw token
  frequency.
- Do not recommend disabling or removing an enabled term solely because it is
  absent from the retained corpus. Without triggering-query and contribution
  provenance, such absence is not evidence that the term is unproductive.
- Screen broad, redundant, or apparently low-value current terms from corpus
  evidence, but classify them as `retire_candidate` only after independent
  Query Target contribution evidence supports retirement; otherwise mark them
  as needing execution evidence.
- When corpus analysis finds a coverage gap or retirement shortlist, run a
  bounded, paced, no-database-write OfferToday probe to compare native routes,
  current shortlisted terms, and proposed additions. Stop immediately on an
  authentication, WAF, IP-block, cursor-contract, or identity-integrity signal.
- Cap live source work at 250 listing API requests. Probe no more than 30
  addition candidates and 30 retirement candidates, using at most two pages per
  target in the first pass. A zero-contribution retirement candidate requires a
  second independent pass of at most one page before it can be recommended for
  retirement; both passes share the 250-request cap.
- Treat bounded live results as decision evidence with an explicit timestamp,
  session/probe identity, target list, page count, and limitations. Do not claim
  full-source precision or recall from the probe.

## Acceptance Criteria

- [x] The analysis identifies the exact database snapshot and query population.
- [x] Corpus quality and representativeness limitations are reported before
      drawing Keyword Pack conclusions.
- [x] Every current OfferToday pack is accounted for, including packs for which
      the evidence supports no change.
- [x] Each recommended term change is traceable to counts and representative
      persisted Job Detail records within the owning Source Classification.
- [x] Recommendations distinguish likely recall gains from noise and overlap
      risks; unsupported changes are explicitly rejected or deferred.
- [x] The report gives one explicit verdict: current coverage is sufficient and
      no change is recommended, or current coverage is insufficient and an
      evidence-backed add/retain/retire proposal is provided.
- [x] A retirement recommendation is supported by Query Target contribution
      evidence and redundancy/noise review, not corpus absence alone.
- [x] Live probing, when required, stays within the approved target/page/listing-request
      limits, records partial/stopped outcomes, and performs no database write.
- [x] A reproducible, read-only analysis command or script can regenerate the
      review from the same database snapshot.
- [x] The final report clearly states whether each pack needs an update and why.
- [x] The review performs no database or Keyword Pack mutation; any accepted
      future change is left to a separate decision and the existing CSV
      preview/confirm workflow.

## Out of Scope

- Automatically applying Keyword Pack changes before the review is accepted.
- Treating Keyword Packs as global, categoryless search terms.
- Reclassifying jobs, changing Source Classification identities, or altering
  unrelated crawler limits and scheduling behavior.
