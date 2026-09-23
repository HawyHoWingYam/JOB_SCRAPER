# Research and adopt Jev in JOB_SCRAPER

## Goal

Research where TypeSafe Jev can improve JOB_SCRAPER, then implement the selected
uses as safe, observable production workflows.

The task now continues through production adoption. Jev should own routine,
high-volume Job Skill extraction and classification. A stronger, more expensive
model should run infrequently over accumulated ambiguous/new Skill Candidates to
maintain the taxonomy. The user does not have, and does not want to create, a
separate human-labelled English/Traditional-Chinese answer set; confidence and
operational feedback are routing signals rather than claims of ground-truth
accuracy.

Confirmed product priority: the user selected A+C — more trustworthy structured Job information and less repetitive data cleanup. Search relevance is a later roadmap opportunity. This choice establishes outcomes, not approval of every proposed cleanup feature or automatic write behavior.

The user explicitly authorized the original research/experiment task and later
authorized production adoption under this same parent task and goal on
2026-09-23. Production work still follows frozen budgets and explicit mutation
boundaries below.

## Background

- Catalog: https://github.com/heyjunpenn/awesome-jev at commit `24279e3fb0a949ae87abd0d772530c1227cf86a7` contains 640 unique entries across 11 categories. Its separate repository-reference table is not part of that count.
- Root README retrieval succeeded for 630 entries on the first pass; 10 were unavailable through the attempted paths. Retrieval, excerpt screening, full README review, source inspection, and running an experiment are different evidence levels.
- Jev supplies bounded decisions, not unrestricted generated prose. Candidate selection, semantic validation, and ranking require task-specific evaluation.
- Current governed Skill creation requires operator confirmation. Source-qualified identities and operator-authored Job facts remain authoritative. Company Industry has been removed from the current product; older CONTEXT.md wording is stale in that respect.

## Requirements

- R1: Maintain a reproducible 640-entry screening ledger with repository URL, transferable idea, project fit, evidence depth, and unresolved evidence limitations.
- R2: Trace high-priority proposals to first-party README or source evidence, recording source revisions where cloned. Clearly separate author-reported metrics from locally reproduced results.
- R3: Map applicable ideas to actual project boundaries: governed Skill recommendations, enrichment evidence checks, source-preserving duplicate grouping, semantic/hybrid search, crawl quality, and operations triage.
- R4: Rank proposals by user value, scope, and evaluation cost. Explain rejected/deferred ideas and distinguish Jev-compatible local models from TypeSafe Jev.
- R5: Define an offline/shadow evaluation plan covering bilingual data, abstention, false positives/negatives, candidate recall, latency/cost, calibration, and failure behavior without prematurely fixing thresholds.
- R6: Preserve deterministic identity, crawl scope/limits, eligibility, cancellation, numeric calculations, source provenance, and human Skill-governance contracts.
- R7: Create and bind a GitHub issue to this task, leaving the task in planning until an implementation scope is chosen.
- R8: Develop a phased adoption roadmap with user-visible outcomes, independent acceptance gates and explicit dependencies. The user requested phased planning with `grill-with-docs` and `ask-matt`; proposed phase ordering remains open during the interview.
- R9: Confirmed production automation boundary: routine Jev Skill classification
  may automatically project stable high-confidence matches to existing Skills.
  Ambiguous/new results remain exceptions. The periodic stronger model may
  automatically apply high-confidence existing mappings, aliases, generic and
  reject dispositions; new Skill nodes and hierarchy changes require one
  aggregate batch confirmation. Preserve source records and auditable rollback.
- R10: Confirmed first production scope: Jev-owned Job Skill extraction and
  classification, its exception queue, and periodic stronger-model taxonomy
  maintenance. Experience requirements, duplicate associations, crawl quality,
  search reranking and incident triage follow as later production slices.
- R11: Confirmed quality policy: reliability first for Skill evidence findings and candidate recommendations. Insufficient evidence remains unresolved. Evaluate actionable suggestion correctness, coverage over the full eligible population, and operator handling time together; abstention alone must not make a system appear successful.
- R12: The user does not want to adjudicate evaluation samples. Do not require a user-labeled batch to proceed. Use automated evaluation with explicit label provenance and uncertainty; agreement between models is not human-validated accuracy. Retain the separately agreed operator confirmation boundary for actual product changes. Operator time savings remain unmeasured until observed in ordinary use.

- R13: The initial USD 10 evaluation allowance remains cumulative historical
  ledger state across calls, retries and paid probes. Production classification
  and stronger-model maintenance must each have explicit Settings-controlled
  budgets; no run, retry, restart or schedule silently refills or raises them.
  Enforce conservative pre-dispatch reservations and stop when remaining
  allowance cannot cover a request.
- R14: Expose recurring operational choices in the existing Settings UI: enablement, model/reviewer configuration, budget, evaluation sample/batch limits, concurrency, retry limits and separate evidence/recommendation display thresholds. Provide defaults, validation and explanations; retain existing candidate count/display controls. Changes affect future runs through frozen configuration snapshots. Budget increases require an explicit saved operator change; no automatic refill.
- R15: Integrate Jev into the durable Job enrichment lifecycle as the ordinary
  Skill classifier. Reuse existing enrichment runs/outbox and current Skill
  mention/candidate/assignment projection instead of adding a parallel source of
  truth. Existing non-Skill enrichment may continue through its current provider.
- R16: Route Jev outcomes by configurable operational confidence and evidence
  quality. Stable high-confidence matches to an existing active assignable Skill
  may update Job Skill enrichment automatically. Ambiguous, novel, conflicting,
  low-confidence, unavailable, invalid, stale or over-budget outcomes must remain
  Candidate/unresolved work and must not be forced into a Skill.
- R17: Preserve evidence text/hash, Job input fingerprint, taxonomy snapshot,
  rubric/model, full answer probabilities, run/attempt identity, usage, cost and
  technical status for every online classification. Reprocessing must be
  idempotent for unchanged Job evidence and must reclassify changed evidence.
- R18: Repurpose the Skill Candidate surface as an exception and taxonomy-
  maintenance queue, not a requirement for the user to label every ordinary Job.
  Browsing the queue must not make paid calls.
- R19: Add an infrequent stronger-model maintenance flow over accumulated
  Candidates/unresolved cases. It may propose existing-Skill mappings, aliases,
  generic/reject dispositions, new Skill leaves and parent placement. Its model,
  cadence/manual trigger, batch size, budget and thresholds belong in Settings;
  its mutation authority is explicit: high-confidence existing-Skill mappings,
  aliases, generic dispositions and rejections may apply automatically; new Skill
  nodes and parent/child changes remain a proposed batch requiring one aggregate
  operator confirmation rather than per-item review. By default it checks every
  30 days and dispatches only when at least 50 eligible exceptions exist; both
  values are Settings-controlled. A free-read “Run maintenance now” action may
  trigger an early bounded run. A scheduled check with insufficient work makes
  zero provider requests and incurs zero model cost.
- R20: Support bounded backfill for existing Jobs plus continuous processing for
  new/changed Jobs, with durable recovery, frozen settings, cumulative budget,
  stop/resume/retry, provider fallback states and no loss of source records.
- R21: Continue the same parent task/goal through the later Jev production slices
  (duplicate associations, crawl-quality flags, bounded search reranking and
  incident triage) after online Skill enrichment is verified. Offline evaluation
  artifacts remain regression tools and historical evidence.
- R22: Every production slice requires a browser-level end-to-end path through
  the real web UI. The mandatory deterministic suite uses a local fake System One
  provider and verifies the complete UI/API/worker/database projection plus
  unavailable and over-budget recovery. When a real Jev credential and bounded
  allowance are available, also run a minimal real-provider browser smoke. Real
  provider availability never replaces or waives deterministic browser E2E;
  Playwright or an equivalent browser runner owns UI automation because Jev is
  the decision engine under test, not a browser automation framework.
- R23: Evaluate direct reuse of `browser-use/jev-ultrafast` at a pinned revision.
  Direct reuse must not bypass the Settings-selected provider endpoint, frozen
  budget ledger, persisted receipts or Playwright's independent assertions. If
  upstream cannot satisfy those boundaries, adopt its bounded indexed-action and
  stale-target validation pattern on existing Playwright/System One infrastructure
  instead of adding a second paid provider path.

## Acceptance Criteria

- [x] AC1: Ledger has exactly 640 unique catalog entries and explicit evidence coverage/failure counts (R1).
- [x] AC2: Recommended opportunities each include upstream references, a concrete JOB_SCRAPER use, limitations, and a success metric (R2–R5).
- [x] AC3: Research distinguishes directory claims, README evidence, inspected source, and unperformed live tests (R2).
- [x] AC4: Recommendations honor current project contracts and correct obsolete Company Industry assumptions (R3, R6).
- [x] AC5: Evaluation design and ordered follow-up plan are saved without introducing runtime dependencies, changing application code, or calling paid model APIs (R5–R6).
- [x] AC6: GitHub issue number/URL are persisted in task metadata and reported to the user (R7).
- [x] AC7: Agree the first user-visible outcome and phased roadmap; capture remaining product decisions and identify independently verifiable follow-up tasks with blocking edges (R8).
- [x] AC8: First-delivery child specifications include separate Skill evidence and recommendation metrics, explicit unresolved/error denominators, and a plan to observe operator effort in ordinary use under the agreed confirmation boundary (R9–R12).
- [x] AC9: A newly ingested or materially changed Job is durably classified by
  Jev for Skills exactly once per input/taxonomy/rubric snapshot, and the receipt
  is auditable (R15, R17, R20).
- [x] AC10: High-confidence existing-Skill results automatically project through
  the current mention/assignment path; every unsafe outcome remains visible as a
  Candidate/unresolved item without corrupting prior/source data (R16–R18).
- [x] AC11: Settings controls both online Jev classification and the stronger-
  model maintenance flow, including independent model/budget/batch/threshold and
  future-run snapshot semantics, default 30-day/50-item scheduling and manual
  run-now action (R14, R19).
- [x] AC12: The stronger-model flow consumes only the exception pool, produces an
  auditable maintenance batch, automatically applies only high-confidence
  existing mappings/aliases/generic/reject outcomes, and holds new Skill or
  hierarchy changes for one aggregate confirmation (R18–R19).
- [x] AC13: Bounded backfill, failure recovery, cumulative cost accounting,
  disabled/unavailable/over-budget fallback and no-paid-call read surfaces pass
  backend, frontend and browser end-to-end tests (R17–R20).
- [x] AC14: Duplicate, crawl-quality, search and incident production slices are
  implemented and independently verified, or remain explicitly open within this
  still-active parent goal; completing offline evaluation alone is insufficient
  (R21).
- [x] AC15: Playwright passes an end-to-end web-UI journey from Job ingestion or
  bounded backfill through Jev Skill classification, automatic existing-Skill or
  Candidate routing, visible receipt/cost/status, maintenance batching and
  aggregate approval. Separate browser cases prove disabled, provider-unavailable
  and over-budget fallback. A real-provider UI smoke is recorded when safely
  available; otherwise its absence is reported without weakening the deterministic
  E2E gate (R22).
- [x] AC16: Direct `jev-ultrafast` packaging compatibility and integration
  boundaries are recorded at a pinned revision. It imports successfully, but its
  hard-coded TypeSafe transport would bypass the OpenRouter-capable endpoint and
  budget ledger, so authoritative E2E remains Playwright and any Jev-guided layer
  must reuse the bounded System One adapter (R23).

## Out of Scope

- Installing all community packages, executing upstream demos, independently reproducing all public benchmarks, or claiming a full audit of all 640 codebases.
- Replacing the entire LLM enrichment pipeline, automatically creating governed Skills, or replacing source Job identities.
- Autonomous browser rewrites, applicant hiring decisions, trading/game products, and self-hosted model training.

## Current roadmap decision

The research roadmap and independently verifiable evaluation slices are
complete. Settings and bounded-run infrastructure are available in the existing
Settings UI. Phase 1B, Phase 3A, Phase 3B, Phase 4, and Phase 5 produced explicit
offline evidence. They are now inputs to production adoption, not the endpoint of
this task.

The former independent-reference release gate is superseded by the user's
production policy: no human gold-label project is required. Jev will take over
routine Skill classification using conservative routing and observable receipts.
Confidence does not mean measured accuracy. Ambiguous work is accumulated for an
infrequent stronger-model maintenance flow rather than returned to the user as a
mandatory labelling exercise.
