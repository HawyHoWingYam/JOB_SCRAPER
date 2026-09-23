# Jev phase 3A: source-preserving suspected duplicate evaluation

## Goal

Determine whether bounded Jev decisions can improve detection of Jobs that may
describe the same vacancy while every source Job remains independently retained.
The immediate deliverable is an offline, reproducible evaluation and a
proceed/defer/inconclusive decision—not a production merge, hide, delete, or
canonicalization workflow.

Parent: `09-23-research-jev-use-cases` / GitHub #62. The parent defines a
Suspected Duplicate Association as reviewable evidence between separate Jobs,
not proof of shared identity. The user requested all roadmap phases, automatic
association generation, no user labeling exercise, small-step tests, and a
final end-to-end verification.

## Confirmed facts

- The live corpus currently contains 15,537 non-deleted Jobs with complete
  384-dimensional embeddings: 7,209 JobsDB, 6,548 CTGoodJobs, and 1,780
  OfferToday Jobs. There are 414 normalized company names represented in more
  than one source.
- `(source_site, source_job_id)` is the durable source-qualified Job identity
  (`backend/app/models/job.py:41-64`). It may not be replaced by a duplicate
  group identity.
- Related Jobs already provides a bounded vector candidate seam and wider
  initial candidate set, but its 80/15/5 relevance score and title
  deduplication are product recommendation behavior, not duplicate truth
  (`backend/app/services/job_recommendation_service.py:76-151`).
- Upstream `jlink` evidence supports cheap symmetric candidate generation,
  explicit unjudged outcomes, conservative pair review, and warns that
  connected components can chain records through one false match. The pinned
  evidence is in the parent task's `research/scout-linkage.md`.
- The current local example uses OpenRouter's Decisions endpoint and
  `typesafe/jev-1.13`. The adapter now accepts the documented response receipt
  fields (`id`, `provider`, and `usage.cost`) while retaining strict answer
  validation. A real contract smoke succeeded against dated model snapshot
  `typesafe/jev-1.13-20260917`.
- Seven earlier ambiguous/failed probes retain USD 0.35 as uncertain. The
  successful contract smoke and 16-case controlled duplicate evaluation spent
  402 microdollars in total. The persistent USD 10 ledger therefore has
  9,649,598 microdollars remaining after both uncertain reservations and
  confirmed spend.

## Requirements

- R1: Create explicit-answer controlled duplicate-pair fixtures covering
  English, Traditional Chinese, and mixed text; exact reposts, paraphrases,
  translated reposts, same title/different company, same company/different
  role, materially changed vacancy, missing evidence, option reordering, and
  transitive-chain traps. Group-related variants so development and held-out
  splits cannot leak.
- R2: Export a bounded real-corpus snapshot in a PostgreSQL read-only
  transaction. Preserve Job UUID plus source site/source Job ID, company/title/
  location/date evidence, normalized-text and raw-description hashes,
  embedding document/model provenance, language/source strata, candidate rank,
  and label provenance. Exclude raw payloads and minimize contact data.
- R3: Generate bounded candidates before any Jev call. Compare at least a
  deterministic lexical/company/date baseline and the existing embedding
  candidate seam. Candidate generation must be symmetric, deterministically
  ordered, capped per Job, and measured separately from pair judging.
- R4: Ask Jev one bounded pair question with outcomes
  `same_vacancy|different_vacancy|insufficient`. Preserve raw probability
  distributions, model/rubric identity, evidence hashes, latency, usage,
  reservation, and safe technical status. Unavailable/invalid/budget-skipped
  pairs remain undecided, never negative.
- R5: Freeze gates before held-out Jev scoring. Report candidate recall@K,
  judged-pair precision/recall, false-association rate, actionable coverage,
  option-order stability, technical failures, source/language strata, p50/p95
  latency, tokens, and microdollar spend. Controlled correctness and real-case
  agreement remain separate; weak/model-derived references are not accuracy.
- R6: Use the existing cumulative allowance and persistent ledger. Offline
  `validate`, `plan`, `export`, baseline, and report operations are free. A live
  request requires explicit confirmation, a valid credential, and a reservation
  that fits the remaining allowance. Stop after ambiguous failure.
- R7: Perform no production writes to Jobs, Companies, embeddings, source
  attributes, recommendations, taxonomy, or duplicate associations. Do not
  introduce a product UI or database table in this evaluation task.
- R8: Keep every source record visible and independently addressable. Do not
  derive canonical Job identity, mutate Related Jobs behavior, hide search
  results, or form production clusters from transitive connectivity.

## Frozen evaluation gates

These gates are declared before any held-out Jev result:

- Controlled candidate recall@10 >= 0.95.
- Controlled answered pair precision >= 0.95.
- Controlled answered pair recall over positive eligible pairs >= 0.80.
- Controlled false-association rate over negative eligible pairs <= 0.02.
- Actionable coverage over every eligible held-out pair >= 0.60.
- Technical failure rate <= 0.05.
- Option-reordering stability >= 0.95.
- Real-corpus release evidence includes independently reviewed English and
  Traditional-Chinese reference slices; otherwise the outcome is inconclusive.

Missing denominators are `not_evaluable`. Abstained, unavailable, invalid,
unjudged, and budget-skipped cases remain in their applicable denominators.

## Acceptance criteria

- [x] AC1: Versioned controlled and real manifests pass exact-schema, hash,
  boundedness, provenance, minimization, group-leakage, and deterministic
  replay validation.
- [x] AC2: Candidate generation is read-only, symmetric, deterministic, capped,
  and reports recall@K independently of Jev judging.
- [x] AC3: Pair scoring retains all eligible cases and emits separate controlled
  correctness and uncertain real-reference results with frozen gates.
- [x] AC4: The live path refuses known rejected credentials without an
  HTTP request, shares the persistent USD 10 ledger, and stops safely on budget
  or ambiguous failure.
- [x] AC5: Produce a proceed/defer/inconclusive report. Only `proceed` may create
  a later product-review task; it still cannot authorize automatic merging.
- [ ] AC6: Focused tests, complete Jev regression, artifact replay, lint/format/
  compile, PostgreSQL read-only integration, and `git diff --check` pass. The
  final roadmap integration phase must additionally run browser E2E and the
  broad project suites.

## Out of scope

- Persisted Suspected Duplicate Associations or a review UI.
- Automatic Job merge/delete/hide, company identity mutation, or canonical Job
  construction.
- Changing Related Jobs/search ranking, pagination, facets, or exports.
- Asking the user to label evaluation examples.
- Retrying the currently invalid Jev credential.
