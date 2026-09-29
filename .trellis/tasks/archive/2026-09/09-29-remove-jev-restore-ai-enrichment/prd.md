# Remove Jev and restore AI Enrichment ownership

## Goal

Remove Jev as a provider, product surface, runtime, and domain concept. Restore
the business outcomes that still matter to the ordinary AI Enrichment workflow
instead of retaining a parallel Jev system.

## Background

- The operator has decided that all Jev functionality should be removed and
  that retained enrichment responsibilities should work through ordinary AI
  Enrichment as they did before the Jev expansion.
- Jev is not isolated to one screen. It currently owns or participates in Job
  Skill classification, possible-same-vacancy judgments, Related Jobs ranking,
  search reranking, crawl incident triage, crawl content quality, Skill
  taxonomy maintenance, provider configuration, manual operations, Job Detail
  status, and persisted audit/history records.
- Ordinary AI Enrichment already has filtered candidate selection, preview,
  explicit run creation, stop, retry, monitoring, history, and a per-Job
  enrichment boundary. It currently extracts raw Skills but delegates final
  non-empty Skill classification/projection to Jev.
- Possible same vacancy and Jev-ranked Related Jobs are not currently ordinary
  AI Enrichment capabilities. Search reranking and crawl advisories operate on
  different lifecycles from Job enrichment.
- Persistence includes one Jev runtime-settings table plus fourteen Jev run,
  item, receipt, evaluation, classification, association, and batch tables.
  Generic API contracts also expose Jev fields on Job Detail, search, and
  Related Jobs responses.

## Requirements

- No implementation begins until the retained capability boundary, treatment
  of existing Jev-derived product data/history, and migration/rollback policy
  are explicitly settled.
- Retain only two Job-level business outcomes:
  1. Skill extraction, correction, and final governed Skill projection.
  2. Related Jobs.
- Move both retained outcomes under ordinary AI Enrichment ownership. They
  must not depend on Jev settings, Jev Operations, Jev run records, or a Jev
  provider request.
- One ordinary AI Enrichment execution per Job produces every retained AI
  outcome together. Skill extraction, evidence disposition, governed Skill
  mapping/candidate routing, Related Jobs filtering/ranking/reasons, and the
  existing summary/experience outputs must not create a second correction
  request, a separate backfill run type, or a second processing state.
- The existing current taxonomy projection boundary remains responsible for
  validating and persisting governed Skill assignments, candidates, generic
  tags, and rejected/insufficient evidence. Operator-authored Skill decisions
  remain authoritative and later AI Enrichment must not silently overwrite
  them.
- Remove the manual Skill Candidate review workflow. Ordinary AI Enrichment
  may map existing governed Skills or classify evidence as generic,
  rejected/insufficient, or unresolved. It must not create new governed Skill
  taxonomy nodes. Unknown terms remain non-searchable unresolved evidence and
  do not block the Job enrichment item. A future taxonomy-curation workflow is
  out of scope.
- Remove the entire Skill-only Classification product and batch subsystem:
  navigation/route/page, candidate and classification-batch APIs, batch
  runtime/history, related Settings, Dashboard backlog affordances, tests and
  active specs. Drop `classification_batch_runs` and
  `classification_batch_run_items` in the same explicit cutover. Retain
  unresolved evidence only as non-actionable internal data, not as a queue.
- Clear historical automatic Skill outcomes produced by the retired ordinary
  Classification Batch pipeline as well as Jev outcomes. Preserve genuinely
  operator-authored decisions. Use terminal batch-item evidence to identify
  proven automatic subjects before dropping classification history; report
  and preserve records whose provenance remains ambiguous rather than risking
  deletion of human decisions. This cleanup does not requeue affected Jobs.
- Related Jobs retain the existing deterministic recommendation service as a
  bounded candidate generator. Ordinary AI Enrichment filters and ranks that
  candidate set and supplies concise reasons. If the AI pass is unavailable or
  fails, Job Detail falls back to the algorithmic candidate order rather than
  losing Related Jobs entirely.
- The deterministic service supplies at most ten real candidate Job IDs to the
  unified AI request. The AI may select zero to five and may not invent or
  reference an ID outside that frozen candidate set. The persisted snapshot
  contains at most five results. These are fixed product bounds, not Settings.
- A successful AI-ranked Related Jobs result is a frozen part of that Job's
  latest successful AI Enrichment snapshot. It is persisted and atomically
  replaced only by a later successful enrichment; Job Detail reads never send
  an AI request. Deleted/unavailable target Jobs are omitted at read time, and
  a missing usable snapshot falls back to the live deterministic algorithm.
- A Job with no deterministic Related Jobs candidates may still complete AI
  Enrichment successfully and persists an empty Related Jobs snapshot. If the
  provider's unified structured response is invalid for any required section,
  the entire Job item fails: no new summary, experience, Skill projection, or
  AI-ranked Related Jobs snapshot is committed. The previous successful
  non-Jev snapshot remains intact and the ordinary `Retry failed jobs` action
  is the recovery path.
- Both retained capabilities use only the existing Job AI provider profile and
  the same structured Job-enrichment request. Do not add separate Skill or
  Related Jobs endpoints, models, API keys, timeouts, thresholds, concurrency,
  retry, cost, or allowance settings.
- Skills and Related Jobs are mandatory parts of the unified Job enrichment;
  the product must not add per-capability toggles. Existing preview, Start,
  Stop, Retry failed, monitoring, and History remain run-level controls, and
  the UI describes all outputs as one enrichment result.
- Remove the entire Jev System One Settings surface and test action. Retain the
  ordinary Job AI profile, its existing test action, and its provider-neutral
  run controls.
- Remove Jev-specific Related Jobs response language and fields, including
  Jev evaluation status, score, reason, and evaluation identifiers. Retained
  fields use provider-neutral AI Enrichment terminology.
- Job Detail keeps a single `Related Jobs` section. A usable persisted snapshot
  shows `AI-ranked from the latest enrichment` and a concise reason per result.
  A live deterministic fallback shows `Suggested by job similarity` and no AI
  reason. Neither path exposes model, request, cost, evaluation, or a separate
  processing status. An empty result shows `No related jobs available`.
- Existing Jev-generated current results are not relabeled as ordinary AI
  output. At cutover:
  - preserve operator-authored Skill decisions;
  - completely remove Jev-automated Skill projections while preserving only
    evidence needed to distinguish and protect operator decisions;
  - remove Jev Related Jobs ordering, scores, reasons, and status;
  - hide old Jev-derived output immediately rather than showing it until the
    replacement run completes.
- Some Jev Skill-maintenance auto-actions passed through the ordinary
  `operator-decision` write seam. Before dropping batch history, use its
  `applied_changes` evidence to undo proven automatic match/generic/reject
  outcomes and their proven automatic aliases, then reopen/recount the affected
  Skill Candidates. Preserve explicitly operator-approved proposed Skills and
  their taxonomy state. Preserve ambiguous decisions that cannot be proven
  automatic; report proven automatic, proven approved, and ambiguous counts
  separately in preflight.
- The cutover must not automatically requeue historical Jobs for AI
  Enrichment, create a migration backfill run, or reset their ordinary
  enrichment status to pending. The new single-pass behavior applies to future
  pending Jobs and the existing ordinary retry of failed run items only.
- Do not add a historical-Job re-enrichment action, all-history refresh,
  date-scoped rerun, or equivalent migration control in this task.
- It is acceptable for historical Jobs to have no governed Skills after
  cutover. They remain empty until a future ordinary, explicitly initiated AI
  Enrichment execution naturally replaces them.
- The same controlled cutover drops all fifteen `jev_*` tables after preflight
  verification. Do not retain a Jev-specific data export. Retain only the
  normal database backup and a secret-safe migration report containing table
  counts, affected-Job counts, preservation checks, and post-cutover absence
  checks.
- During implementation, the destructive database transition uses a temporary,
  manually invoked two-step tool: a read-only `preflight`, followed by an
  `apply` action that requires an explicit removal confirmation argument and
  reruns all preflight checks. Application startup, database bootstrap, and
  ordinary deployment must never trigger the drop. The temporary apply is
  tested as idempotent and reports that removal is already complete without
  touching unrelated data.
- After the one authoritative database is cut over and post-cutover verification
  is recorded, delete the temporary cutover tool and its dedicated tests before
  the final work commit. Do not retain a reusable migration command, deprecated
  table names, or a live-source exception solely for hypothetical future
  environments.
- During the transition, Related Jobs may use the existing deterministic
  algorithmic fallback. Governed Skills may be temporarily absent until that
  Job later completes an explicitly initiated replacement AI Enrichment.
- Remove Possible same vacancy / duplicate association, Job Browser search
  reranking, repeated crawl-incident triage, crawl content-quality advisory,
  Jev Skill taxonomy maintenance/backfill, configuration smoke runs, and all
  other Jev-specific product capabilities.
- Removed Jev routes, route fragments, request/response fields, and capability
  endpoints disappear in the same release. Do not keep redirects, tombstone
  pages, deprecated payload fields, compatibility handlers, or an old-client
  transition period.
- Historical archived Trellis task artifacts and Git history remain historical
  records; removing the live product must not rewrite repository history.
- Retire the active `09-28-repair-jev-batch-retry-failure-propagation` Trellis
  task as superseded by this removal decision. Update and close its linked
  GitHub issue rather than continuing to repair a product that will be removed;
  preserve the archived task documents as historical evidence.
- Current runtime/product surfaces must contain no Jev naming or dependency:
  backend and frontend source, active API/schema contracts, runtime/container
  configuration, current tests and E2E harnesses, README and active product
  documentation/specs, the domain glossary, and the current database schema.
  Jev may remain only in Git history, archived Trellis tasks and historical
  journal entries, this removal task, and the secret-safe cutover report.

## Acceptance Criteria

- [ ] One ordinary Job AI request returns the existing Job insights, a complete
      Skill disposition for every extracted term, and a ranking over at most
      ten frozen Related Jobs candidates; no second provider request occurs.
- [ ] The unified response is strictly validated before mutation. Unknown Skill
      codes, invented/duplicate Related Job IDs, more than five selections, or
      a missing/invalid required section fail the Job item and roll back every
      new output. Zero Related Jobs candidates remains a valid success.
- [ ] A successful item atomically commits Job insight fields, the current
      Skill projection, and the current Related Jobs snapshot. Existing
      operator-authored Skill decisions survive later enrichment.
- [ ] Unknown Skill terms remain non-searchable unresolved evidence; enrichment
      does not create taxonomy nodes and no manual/automated candidate-review
      workflow remains.
- [ ] Related Jobs reads prefer a usable persisted AI-ranked snapshot and show
      at most five live, non-deleted target Jobs with concise reasons. Missing,
      empty, or unusable snapshots fall back to the deterministic similarity
      service without issuing an AI request.
- [ ] Job Detail presents only `AI-ranked from the latest enrichment`,
      `Suggested by job similarity`, or `No related jobs available`; it exposes
      no provider receipt, model, cost, evaluation, or secondary operation
      status.
- [ ] Possible same vacancy, search reranking, incident triage, crawl content
      quality, Skill maintenance/backfill, smoke runs, Jev Operations, Jev
      Settings, and the entire Classification/Skills-review product are absent
      from navigation, pages, APIs, workers, Settings, and runtime capability
      contracts.
- [ ] All fifteen `jev_*` tables and both `classification_batch_*` tables are
      absent from the authoritative database and fresh bootstrap schema.
- [ ] The cutover clears proven Jev and Classification Batch automatic Skill
      outcomes, preserves proven operator decisions and approved Skills,
      preserves ambiguous records, recomputes affected candidate/projection
      state, and does not requeue any historical Job.
- [ ] A secret-safe task verification record contains preflight counts,
      automatic/operator/ambiguous preservation counts, backup acknowledgement,
      apply results, idempotence evidence, and post-cutover absence checks. No
      Jev data export or permanent cutover executable remains.
- [ ] Old Jev routes and payload fields disappear immediately with no redirect,
      compatibility handler, tombstone, or deprecated response property.
- [ ] Excluding Git history, archived Trellis tasks/journals, this removal task,
      and its secret-safe verification report, tracked live source, current
      tests, runtime configuration, README, domain glossary, and active specs
      contain no Jev reference.
- [ ] Future pending Jobs and existing failed-item retries use the unified
      enrichment. Historical successful Jobs are not reset, requeued, or given
      a new bulk/date-scoped rerun control.
- [ ] Targeted and full backend/frontend tests, lint/format/type/build checks,
      fresh-schema bootstrap, container capability smoke checks, and
      `git diff --check` complete with any unrelated baseline failures recorded.

## Notes

- This is a complex cross-layer removal and migration task. It requires
  `design.md` and `implement.md` before activation.
