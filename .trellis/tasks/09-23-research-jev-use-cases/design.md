# Jev production-adoption design

## Scope

This document records the completed experiment design and the authorized
production adoption. The user selected trustworthy structured Job information
plus reduced repetitive cleanup (A+C), with Jev owning routine Skill
classification and a stronger model maintaining accumulated exceptions.

## Recommended boundary

The confirmed first production delivery combines source-grounded Skill extraction,
classification into existing taxonomy nodes, exception routing and periodic
taxonomy maintenance. Duplicate and crawl-quality product flows follow later.
Skill evidence and taxonomy selection remain separate typed decisions even when
they share source passages and receipts. Experience requirements remain deferred.

Use the native bounded-decision interface at the Skill classification seam. Its
inputs are immutable source evidence, governed candidate identities and a
versioned rubric. Its output records the raw answer distribution, resolved model,
latency/usage, and an explicit `answered`, `abstained`, `unavailable` or `invalid`
status. Transport failure never becomes a negative classification.

Keep deterministic exact/alias/curation resolution before semantic decisions. A
Jev-selected existing path must exist and remain active/assignable in the frozen
taxonomy snapshot and at application time. New governed Skill creation remains
an aggregate operator-confirmed batch action. Evidence retains enough original
context to distinguish requirement, preference, negation and incidental company
description. Numeric experience verification is a later extension.

## Confirmed rollout authority

The user authorized automatic high-confidence existing-Skill projection for daily
Jev classification. The stronger model may automatically apply high-confidence
existing mappings, aliases, generic and reject dispositions. New Skills and
hierarchy changes are shown as one auditable batch diff and require one aggregate
confirmation. Suspected duplicates retain each source record and never
automatically merge, hide, delete or overwrite it.

## Historical offline evaluation data flow

The user selected reliability first. Calibrate evidence-finding and candidate-recommendation policies separately, permit abstention, and report correctness alongside actionable coverage, unresolved/error counts and operator handling time when observed during ordinary use; do not claim measured time savings from automated evaluation alone. A raw model confidence is not an established probability of a correct business decision. Do not select a threshold solely to maximize accuracy by suppressing most suggestions.

1. Select a bounded corpus snapshot and preserve Job/source identities and evidence hashes.
2. Prepare controlled fixtures with explicit expected answers and a separate real-corpus manifest with language/source/ambiguity strata and duplicate-aware splits. Record the origin of every reference label; no user annotation batch is required.
3. Run existing baselines and the proposed bounded Jev questions against the same evidence.
4. Store immutable decisions and errors without writing product assignments or facts.
5. Select provisional policies on development data; score once on held-out fixtures and real-corpus slices, reporting reference-label provenance and limitations separately.
6. Review coverage/error/cost trade-offs and either reject the idea or define a separate production integration scope.

## Automated evaluation without user labeling

- Validate evidence spans, governed candidate identities and output contracts deterministically. These checks establish structural validity, not semantic truth.
- Use controlled cases with explicit expected answers for requirements, preferences, negation, incidental mentions and missing evidence. Arbitrarily model-generated cases have provisional labels unless their answers follow from a checked construction.
- Obtain real-case reference judgments independently of Jev answers, using separately configured reviewers where available and within budget. Freeze reference judgments before comparison; do not let reviewers adopt the tested answer. Record reviewer model/rubric identities and correlated-error limitations.
- Check disagreement and stability under option reordering and carefully constrained context changes. Retain unresolved cases and report them in the full denominator. Do not use majority agreement as ground truth.
- Report fixture correctness, real-case model agreement, candidate coverage, unresolved cases and technical failures separately. Production semantic accuracy remains unverified without independent trusted labels. Existing operator decisions may supply references only when provenance and applicability are verified.
- These checks remain regression evidence and do not claim human-validated
  accuracy. The later explicit production authorization, conservative routing,
  receipts and rollback boundary govern automatic existing-Skill projection.

## Questions to test

- Skill disposition and existing-path recommendation should be separate decisions when their candidate sets differ. Include an explicit insufficient-evidence path; a low-confidence winner is not a new Skill.
- Source support should distinguish supported, contradicted, absent and insufficient-context outcomes. Distinguish a Skill required for the Job from a preferred Skill, explicit negation or incidental company context.
- Compare one-record state against bounded batching. Test translated/mixed language, option ordering, missing candidate, unrelated context and negation. No upstream default threshold is a project acceptance threshold.

## Alternatives and trade-offs

- Existing rules/LLM only is the baseline and valid outcome if Jev adds no useful value.
- Official async Python SDK is the preferred first client candidate. A narrow adapter avoids introducing a new orchestration framework; SDK availability does not establish accuracy.
- Search reranking requires an additional bounded candidate set, rank-fusion comparison and stable tie-breaking. Evaluate it separately because recall, facets, paging and exports have different acceptance criteria.
- Duplicate grouping requires separate candidate-recall and cluster false-merge tests. Preserve source IDs and model unresolved pairs explicitly.
- Evidence pruning can save tokens but harm recall; complete raw descriptions and negation context remain available.

## Compatibility and recovery

Non-Skill summary/experience enrichment remains on its existing path. Jev Skill
classification is independently disableable; disabled/unavailable/over-budget
states retain Candidate/unresolved work without fabricating assignments. Save
request/rubric/model identities for replay, cap concurrency/retries/spend, and
record partial failures. Rollback disables new Jev dispatch while preserving
receipts and current source/Skill records.

## UI configuration and budget contract

Extend existing Settings rather than introduce a separate configuration app. `frontend/src/components/settings/AISettingsPage.jsx:238` and `:298` are form/request seams; `backend/app/api/settings.py:96` and `backend/app/services/ai_runtime_settings_service.py:249` are API/persistence seams. Add a Jev section with ordinary controls and an advanced section for concurrency/retries and separate decision thresholds. The existing distinct-Job threshold is queue eligibility, not model confidence; existing recommendation/evidence counts are display limits, not evaluation batch sizes.

Expose initial USD 10 total allowance, spent/reserved/remaining amounts, model/reviewer selection, sample/batch limits, concurrency/retries and enablement. Preserve credential masking. Display thresholds are decision scores, not advertised accuracy. Save defaults for future runs and show the resolved settings before starting a run. Configuration changes do not silently mutate a running evaluation. Repeated/resumed runs share the initial evaluation allowance; increasing/resetting it is an explicit operator action, not a side effect of saving unrelated settings. API tests and retries consume this allowance too.

The backend requires new accounting: reserve a conservative upper bound before dispatch, reconcile usage after completion, and retain uncertain reservations after ambiguous failures. Include concurrent in-flight calls and retries. Stop paid calls if price/usage bounds cannot be established. Verify current provider pricing before paid execution; USD 10 is a cap, not an obligation to spend it. This cap covers this feature's calls, not unrelated activity on the same provider account.

## Review surface and recovery

Extend `frontend/src/components/classification/ClassificationBatchesPage.jsx:176` with source passages, Skill evidence findings, Jev recommendation status and operator actions. Existing recommendations in `backend/app/api/skill_candidates.py:88` use local name/alias similarity; label them distinctly from Jev scores. Current evidence at `:137` has only Job identity/title/source, so source passages need a new read contract. Browsing candidates must not trigger paid calls.

Run Jev analysis explicitly in bounded background work. Disabled, unavailable, over-budget and unresolved states preserve existing review and deterministic recommendations. Validate evidence/taxonomy freshness before applying a suggestion; a changed record requires fresh analysis or ordinary manual review. Reuse the explicit decision endpoint for confirmed actions and do not invoke mutations merely to display a recommendation.

## Production Skill enrichment continuation

Keep the existing durable enrichment lifecycle as orchestration authority:
`job.ingested` → enrichment run/item → worker claim → enrichment service. Jev
replaces the Skill-classification portion, not the run scheduler or the unrelated
summary/experience fields. This avoids a second daily queue and preserves current
recovery semantics.

For each Job, freeze a minimized Skill evidence state, an input fingerprint, the
active taxonomy identity, rubric and Jev settings. Use the native System One
adapter and budget ledger, then translate the typed decision into the existing
`CurrentSkillEnrichment.replace_job_skills()` contract. That service remains the
only writer for active mentions, Candidate aggregation and canonical Job Skill
assignments.

Routing has three product outcomes:

1. A stable high-confidence selection of an existing active assignable Skill,
   supported by direct Job evidence, becomes an automatic canonical assignment.
2. A novel name, close choice, weak/indirect evidence or other semantic
   uncertainty remains an active Candidate mention for later maintenance.
3. Provider, budget, schema, stale-snapshot or missing-evidence failures remain
   unresolved technical work and never become a negative or fabricated Skill.

The Candidate page becomes an exception queue. Reads are free and show evidence,
the Jev receipt/status and deterministic hints. It is not a per-Job labelling
requirement.

The stronger-model maintenance flow is a separate bounded run over the aggregated
exception pool. It reuses Candidate identities and the current taxonomy tree,
freezes its own provider/model/budget/settings, and emits auditable proposals for
existing mappings, aliases, generic/reject decisions and new leaves. Stable,
high-confidence mappings to existing active Skills, aliases, generic dispositions
and rejections may apply automatically through the existing decision services.
New Skill leaves and hierarchy changes stay in a proposed batch and require one
aggregate operator confirmation. The confirmation view shows the complete diff,
conflicts and rollback identity; it is not a per-Candidate labelling queue.

The maintenance scheduler performs a free database eligibility check every 30
days by default. It dispatches only with at least 50 eligible exceptions by
default. Period, minimum eligible count, batch size, model, budget, concurrency,
retry and thresholds are Settings-controlled and frozen per run. “Run maintenance
now” performs the same eligibility/budget checks; neither viewing the page nor an
empty scheduled check calls a provider.

## Browser end-to-end authority

The release gate includes a browser-driven UI journey, not only service and API
tests. A loopback fake System One returns fixed typed answers and exposes a request
audit so Playwright can prove exactly one budgeted dispatch, the resulting Skill
assignment/Candidate projection, visible model/receipt/cost, maintenance diff and
aggregate approval. Additional cases force provider unavailable and exhausted
allowance states and assert the UI keeps work unresolved without false writes.

When the local environment has a real Jev credential and explicit remaining
allowance, run one bounded real-provider browser smoke and retain only secret-safe
receipt fields. This smoke is supplemental because external availability is not a
deterministic release gate. If real Jev is unavailable, the same user-visible
workflow remains covered through the fake provider and focused adapter tests.
Jev may classify the test Job inside the flow, but Playwright (or an equivalent
browser runner) remains responsible for navigation, interaction and assertions.

`browser-use/jev-ultrafast` was inspected at
`1231850a0bf1a0c0341fe408ef1668dbbfdfac46` and imports under Python 3.12. Do not
use its current Agent directly as the release path: its System One endpoint is
hard-coded to TypeSafe and would bypass this project's OpenRouter-capable endpoint,
cumulative budget ledger and receipts. An optional Jev-guided Playwright layer may
reuse its safe interaction shape: an atomic indexed catalogue of visible supported
actions, code-owned locators, freshness and actionability validation, bounded steps
and spend, and independent final postconditions. Model output never becomes a
selector, coordinate, script or shell command; `DONE` is not test success. See
`research/jev-ultrafast-browser-testing.md`.

Continuous classification and historical backfill share the same item contract.
An unchanged `(job evidence fingerprint, taxonomy snapshot, rubric version)` is
idempotent; changed evidence or taxonomy creates new work while retaining prior
receipts. The source Job and raw evidence are never overwritten by Jev.

## Completed evaluation review

Seven child tasks cover settings/budget, Skill evaluation, the gated Skill review,
duplicate evaluation, crawl-content quality, search relevance, and incident
triage. Settings/budget and all five offline evaluation slices are complete and
archived. Native OpenRouter Jev receipts were verified, including provider-reported
cost reconciliation. One later crawl-quality request ended ambiguously with HTTP
520, so its reservation remains uncertain and no later paid request was sent.

The earlier Phase 2 hold correctly prevented unapproved writes at that time. The
user has now authorized production adoption and clarified that the desired system
uses confidence-based operational routing rather than a separately labelled gold
set. Offline fixtures remain regression tests; they no longer block online Skill
classification.
