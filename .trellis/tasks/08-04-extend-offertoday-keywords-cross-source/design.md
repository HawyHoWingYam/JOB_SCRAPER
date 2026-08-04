# Design: Cross-source evidence for OfferToday keywords

## Design shape

Extend the existing read-only keyword review tool with a source-neutral corpus
profile and cross-source comparison layer. Keep the OfferToday catalog,
normalization, archived corpus, and live-probe decision boundary intact. The
new layer discovers vocabulary from JobsDB and CTGoodJobs; only the OfferToday
layer may turn a discovery into an OfferToday recommendation.

The archived review remains immutable. New task-local artifacts reference its
snapshot and recommendations as inputs and record only incremental evidence.

## Data boundaries

Open one PostgreSQL transaction, execute `SET TRANSACTION READ ONLY`, set a
bounded local statement timeout, and roll back/close in `finally`. Load Jobs
with these exact predicates:

- `source_site` equals `jobsdb` or `ctgoodjobs`;
- `is_deleted = false`;
- title and description are nonblank; and
- an authoritative path node at `source_position=0` has the exact source-owned
  IT identity (`jobsdb:6281` or `ctgoodjobs:021`).

Do not use display labels, the blank legacy scalar Job classification fields,
or title inference. Count a Job once per source even when it has multiple
paths. Preserve bounded examples with source site, source Job ID, title, posted
date, classification paths, matched field, and truncated snippet.

## Discovery and candidate curation

Produce a deterministic source profile and discovery inventory from normalized
titles/descriptions. Reuse the existing Unicode normalization, Latin-boundary,
CJK contiguous-match, snippet, and distinct-Job counting functions.

Discovery may rank recurring title phrases and technology/product vocabulary,
but arbitrary n-grams do not become recommendations automatically. Curate a
task-local candidate CSV recording the term, family, kind, source of discovery,
and rationale. Reject generic recruitment language, seniority, benefits,
locations, employer names, and terms whose apparent support is irrelevant to
IT search intent.

For each curated term report:

- JobsDB title/detail support;
- CTGoodJobs title/detail support;
- archived OfferToday title/detail support;
- presence/semantic overlap in the current OfferToday pack and prior candidate
  list;
- representative Jobs per supporting source; and
- expected recall benefit plus precision, cross-classification, and duplicate
  risk.

## Recommendation policy

Cross-source support is discovery evidence only. A new term can become a
`probe_candidate` when it has at least three distinct relevant Jobs in each of
two sources, or strong support in one external source plus at least three
OfferToday details, with at least two relevant title examples overall.

Final dispositions are:

- `supported_addition`: passes the corpus guardrail and contributes relevant
  OfferToday IDs in the fresh bounded probe;
- `variant_or_replacement`: useful vocabulary but semantically overlaps an
  existing term/variant and needs operator choice;
- `needs_offertoday_evidence`: strong cross-source discovery without adequate
  OfferToday contribution evidence;
- `rejected_noise`: generic, misleading, employer/location/benefit noise, or
  cross-classification risk exceeding likely recall value; and
- `retain` / `retire_candidate` for re-evaluated current terms, still requiring
  OfferToday-owned contribution evidence.

Re-evaluate all 15 prior additions, `pentest`, and `angular`. Cross-source
absence cannot retire an OfferToday term, and cross-source frequency cannot
override a negative/noisy OfferToday result.

## Fresh OfferToday probe

Probe only newly qualified terms that lack adequate archived OfferToday query
evidence. Use the production listing request, response, cursor, identity, and
pacing contracts with an in-memory no-op staging sink. No ORM/database session
exists during the probe.

The complete follow-up probe has a hard cap of 60 listing API requests. Use at
most two pages per candidate and stop before exceeding the cap. Stop the whole
probe immediately for auth, WAF, IP block, cursor/session contract,
identity-integrity, or unresolved transport errors. Store only sanitized IDs,
titles, Job Function codes, counts, timestamps, target settings, and stop
evidence.

Compare fresh candidate IDs with archived native/current-pack samples, clearly
labeling the timestamp mismatch and bounded nature. Do not claim full-source
precision, recall, or natural exhaustion.

## Artifacts

- Extend `backend/scripts/review_offertoday_job_detail_keywords.py` rather than
  create a competing matching/probe implementation.
- Extend `backend/tests/test_review_offertoday_job_detail_keywords.py` with
  source-scoped profile, cross-source support/disposition, and 60-request cap
  coverage.
- Add task-local `research/cross-source-candidates.csv`,
  `research/cross-source-snapshot.json`, and, only if needed,
  `research/cross-source-live-probe.json`.
- Generate `review-report.md` as the additive cross-source conclusion while
  linking the archived OfferToday-only baseline.

## Compatibility and rollback

No schema, API, production crawler, database row, Keyword Pack, or archived
artifact changes. Existing OfferToday-only CLI modes and deterministic outputs
remain compatible. Rollback is file-only: revert the analyzer/test extension
and remove the new task-local evidence artifacts.

