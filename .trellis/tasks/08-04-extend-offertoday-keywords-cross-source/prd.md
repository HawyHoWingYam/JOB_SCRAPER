# Extend OfferToday keyword review with cross-source Job Details

## Goal

Improve the evidence behind OfferToday Information Technology Keyword Pack
recommendations by mining the complete usable JobsDB and CTGoodJobs Job Detail
corpora for relevant vocabulary, then validating cross-source discoveries
against OfferToday-owned evidence before changing the prior verdict.

## Background

- The completed OfferToday-only review is archived under
  `.trellis/tasks/archive/2026-08/08-04-review-offertoday-job-detail-keyword-coverage/`
  and is bound to GitHub issue #49.
- That review analyzed all 1,139 usable published OfferToday Job Details and
  concluded that the current 127-term pack was insufficient.
- The follow-up reuses issue #49 and must preserve the previous review as an
  immutable baseline rather than rewriting its artifacts.
- JobsDB and CTGoodJobs vocabulary can reveal missing IT concepts, spelling
  variants, products, and role phrases, but cross-source frequency alone does
  not prove that an OfferToday query will improve recall or precision.
- The current snapshot contains 3,565 usable JobsDB Job Details and 3,178
  usable CTGoodJobs Job Details; every row has a nonblank title and description.
- Source-owned path evidence places 3,559 JobsDB Jobs under `jobsdb:6281`
  (Information & Communication Technology) and all 3,178 CTGoodJobs Jobs under
  `ctgoodjobs:021` (Information Technology). Six JobsDB rows lack the IT root
  path and are excluded rather than inferred into scope.
- JobsDB posted dates span 2025-05-19 through 2026-07-28; CTGoodJobs spans
  2026-06-22 through 2026-07-29. Both corpora are mostly Latin-title Jobs, so
  source/date/language skew must remain visible in conclusions.
- The legacy scalar Job classification fields are blank for all 6,743
  cross-source rows. Root membership therefore comes only from path nodes at
  `source_position=0` with the exact source-qualified identity.

## Requirements

- Profile all usable, non-deleted published JobsDB and CTGoodJobs Job Details,
  including counts, completeness, dates, language mix, and source-owned
  classification evidence.
- Restrict discovery to Jobs belonging to each source's Information Technology
  classification evidence; do not infer membership from labels shared between
  sources.
- Compare cross-source vocabulary with the current OfferToday pack and the
  prior OfferToday candidate/recommendation set.
- Separate cross-source discovery support from OfferToday corpus support and
  OfferToday query-contribution evidence.
- Promote no cross-source-only candidate directly into the OfferToday change
  recommendation. A promoted term must also pass OfferToday-specific relevance
  and bounded contribution guardrails.
- Preserve the database, Keyword Packs, prior report, and crawl configuration.
- Extend the reproducible review output with source-by-source support counts,
  representative Jobs, overlap/noise risk, and explicit disposition for every
  newly discovered candidate.
- Keep all work bound to GitHub issue #49.
- Exclude the six JobsDB rows without `jobsdb:6281` path evidence; do not infer
  them into IT scope from title text.
- If cross-source evidence produces newly qualified candidates, permit a fresh
  paced, no-write OfferToday probe capped at 60 listing API requests. The probe
  must stop immediately on auth, WAF, IP-block, cursor/session, or
  identity-integrity failure.
- Reuse the archived OfferToday corpus and contribution evidence as the
  immutable baseline, while reporting any timestamp mismatch between that
  evidence and the fresh candidate probe.

## Acceptance Criteria

- [x] Every usable JobsDB and CTGoodJobs IT Job Detail in the selected database
      snapshot participates in vocabulary discovery.
- [x] The report states exact inclusion/exclusion rules and representativeness
      limitations for all three sources.
- [x] Each cross-source candidate has per-source support counts and bounded
      representative Job examples.
- [x] Each candidate is classified as supported addition, variant/replacement,
      rejected/noisy, or needing OfferToday evidence.
- [x] The prior 15 additions, `pentest` retirement, and `angular` deferral are
      re-evaluated rather than assumed correct.
- [x] No database row, Keyword Pack, or prior archived artifact is mutated.
- [x] A deterministic report and testable read-only analysis path reproduce the
      cross-source conclusions.
- [x] Any fresh OfferToday probe stays within 60 listing API requests, records
      sanitized evidence, and performs no database write.

## Out of Scope

- Applying Keyword Pack changes.
- Treating JobsDB or CTGoodJobs search behavior as evidence of OfferToday query
  contribution.
- Reclassifying Jobs or changing source-owned classification identities.
