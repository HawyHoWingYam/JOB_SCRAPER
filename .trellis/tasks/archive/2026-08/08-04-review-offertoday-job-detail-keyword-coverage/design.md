# Design: Review OfferToday Job Detail keyword coverage

## Design shape

Build one deterministic, read-only corpus-review tool and use it to produce a
task-local Markdown report. Keep catalog mutation outside this task. The tool
separates database extraction from pure text analysis and rendering so tests can
use fixtures without a PostgreSQL dependency.

The review answers a deliberately limited question: which terms deserve
operator consideration based on retained Job Detail vocabulary? It does not
claim query recall, precision, or causal contribution because current staging
rows do not retain the triggering keyword or Query Target identity.

## Artifacts

- `backend/scripts/review_offertoday_job_detail_keywords.py`: read-only CLI,
  deterministic corpus extraction, matching, bounded live probing,
  recommendation classification, and Markdown/JSON rendering.
- `backend/tests/test_review_offertoday_job_detail_keywords.py`: pure analysis,
  renderer, and PostgreSQL read-only transaction guard coverage.
- `.trellis/tasks/08-04-review-offertoday-job-detail-keyword-coverage/research/candidate-terms.csv`:
  reviewed candidate phrases to measure. Each row records the candidate,
  language/variant family, and why it entered the review.
- `.trellis/tasks/08-04-review-offertoday-job-detail-keyword-coverage/research/corpus-snapshot.json`:
  sanitized immutable analysis input with counts and bounded representative
  evidence, not full descriptions or raw payloads.
- `.trellis/tasks/08-04-review-offertoday-job-detail-keyword-coverage/review-report.md`:
  generated snapshot, limitations, pack accounting, candidates, representative
  Jobs, and recommendations.
- `.trellis/tasks/08-04-review-offertoday-job-detail-keyword-coverage/research/live-probe.json`:
  sanitized, reproducible probe inputs and evidence; no cookies, credentials,
  raw URLs, or unrelated response payloads.

The candidate file makes analyst judgement explicit and reproducible. The CLI
may expose recurring title tokens/phrases as discovery output, but it must not
promote arbitrary n-grams directly into recommendations.

## Database boundary

Use the configured SQLAlchemy engine and open one explicit transaction. On
PostgreSQL, execute `SET TRANSACTION READ ONLY` before corpus queries and set a
bounded local statement timeout. The code must never call `add`, `flush`, or
`commit`; it rolls back and closes in `finally`, including successful runs.

Extract a compact immutable snapshot containing:

- database identity without credentials, extraction time, row counts, and
  posted-date bounds;
- all non-deleted OfferToday Jobs with nonblank title and description;
- exact Source Classification memberships from
  `job_source_classification_paths` and their ordered nodes;
- every OfferToday Keyword Entry, enabled or disabled, joined to its
  source-qualified owning classification;
- existing `last_new_job_ids`, `last_duplicate_rate`, and `last_run_at` fields,
  preserving nulls as missing evidence rather than zeros.

Do not use the legacy scalar `jobs.source_classification_id` as authority. A Job
may have multiple non-primary Source Classification Paths; retain every path and
do not infer a primary path.

## Normalization and matching

Catalog identity continues to use the production normalization contract:
trim, collapse internal whitespace, and case-fold within the owning Source
Classification.

Corpus matching uses Unicode normalization plus case-folding:

- Latin tokens and phrases require alphanumeric boundaries so `C` does not
  match every word containing that character.
- CJK phrases use normalized contiguous matching and are reported separately
  because the project has no governed Chinese segmenter.
- Title and cleaned description are the primary evidence fields. Source tags,
  skills, and keywords are optional sensitivity evidence and cannot independently
  justify a recommendation.
- Counts always use distinct published Job identity. A Job matching several
  variants in one family counts once for that family.

Representative evidence includes stable `source_job_id`, title, Source
Classification paths, posted date, and a bounded matched snippet. Reports do
not emit full descriptions or unrelated raw payloads.

## Recommendation policy

Use recall-first discovery with precision guardrails:

- `candidate_add`: absent from the owning pack, supported by at least three
  distinct relevant Job Details, represented by at least two Jobs, and manually
  judged specific enough for the Information Technology root.
- `variant_or_replacement`: evidence suggests an uncovered spelling/language
  family but it may overlap an existing normalized or semantic term; operator
  review is required before choosing an additional term versus replacement.
- `needs_execution_evidence`: broad/ambiguous candidate, or an existing term
  with low/zero corpus support but no query-level contribution evidence.
- `no_change`: current term or pack has no evidence-backed change.

The report must not classify an enabled term as `remove` solely from corpus
absence. Actual removal/disable decisions require future frozen Query Target
evidence such as newly contributed IDs, duplicate ratio, completed status, and
run time.

Initial candidate families include the exploratory findings Microsoft, Oracle,
AIGC, UAT, CRM, Helpdesk, Power BI, SharePoint, ServiceNow, Salesforce, plus
recurring Chinese IT-title variants. The checked-in candidate CSV, not this
prose list, is the executable review input.

## Bounded live probe

The CLI exposes separate `corpus`, `probe`, and `report` phases. `corpus` uses
the read-only database boundary. `probe` has no database session and writes only
the explicitly selected local artifact. `report` combines the two immutable
inputs.

Run `probe` only if corpus results show an uncovered theme or identify existing
terms needing contribution evidence. Build a target set consisting of the
Information Technology root and current active children as a native baseline,
at most 30 proposed additions, and at most 30 retirement candidates. Candidate
keyword requests remain paired with the top-level classification and use the
production search request contract.

Enforce all of the following in code:

- at most two result pages per target in the first pass, at most one additional
  page for second-pass retirement candidates, and 250 listing API requests
  over the complete review;
- project source pacing and bounded retry policy, with no concurrency increase;
- a fresh probe/session identity and target-local cursor state;
- immediate hard stop for auth, WAF, IP block, cursor/page/session contract,
  identity conflict, or unresolved transport gap;
- no staging sink, ORM session, published Job write, Keyword Entry update, or
  execution-evidence update;
- sanitized local evidence containing target identity, page/result counts,
  distinct canonical Job IDs, overlap/new-ID counts, duplicate ratio, stop
  reason, and timestamps.

Compute each keyword's bounded contribution against the native baseline and
the union of other probed keyword targets. A term with zero leave-one-out
contribution is not automatically useless: it enters a second independent
bounded pass. `retire_candidate` requires zero or negligible distinct
contribution across both passes, high redundancy with retained routes, and a
manual noise/semantic review. Source instability, a partial probe, or any hard
stop downgrades the result to `needs_execution_evidence`.

The probe is comparative sampling, not Evidence-Bounded Coverage. Its page
limit must never be presented as natural exhaustion or an absolute OfferToday
inventory statement.

## Report contract

The Markdown report is ordered and deterministic apart from an explicit
snapshot timestamp. It contains:

1. database snapshot and query population;
2. corpus quality and representativeness limitations;
3. Source Classification and language distribution;
4. all current packs and every current term, including evidence-null status;
5. candidate support counts and representative Jobs;
6. recommendation tables grouped by add, variant/replacement, future evidence,
   and no change;
7. bounded live-probe contribution and stop evidence when probing was needed;
8. a per-pack sufficiency verdict and, only when justified, an add/retain/retire
   proposal;
9. exact regeneration commands and analysis/probe configuration.

JSON output exposes the same data contract for tests and later comparison.
Sorting uses source classification identity, normalized keyword/candidate, and
stable Job identity.

## Compatibility and safety

- No schema, API, crawler, Keyword Pack, or database row changes.
- No claim of absolute OfferToday inventory coverage.
- No classification is inferred from a display label; identities remain
  source-qualified.
- The current 127-term Information Technology pack remains unchanged.
- A future mutation task may consume accepted recommendations through the
  existing CSV preview/confirm workflow, but must not bypass it.

## Verification strategy

Unit fixtures cover Unicode/case/whitespace normalization, Latin boundaries,
CJK contiguous matching, distinct-Job counts, multi-path Jobs, candidate
thresholds, missing execution evidence, deterministic ordering, and safe
snippet rendering. Scripted transport fixtures cover request/page/target caps,
pacing calls, target-local cursor reset, overlap arithmetic, second-pass
retirement fencing, hard stops, sanitization, and absence of persistence sinks.
A PostgreSQL integration seam verifies that a write attempt inside the analysis
transaction is rejected. Run the corpus/report phases twice against the same
inputs and compare normalized JSON or Markdown with timestamps excluded.
