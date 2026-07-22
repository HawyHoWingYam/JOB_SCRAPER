# Clarify scoped Job Intelligence Governance review selection

## Goal

Make the scoped Job Intelligence Governance review queue understandable and
actionable for an operator repairing provenance exclusions from the OfferToday
IT scope. The operator should identify a Job using human-facing information,
understand why any row may be selected, and distinguish per-item evidence
viewing from batch-level provenance inspection/repair.

## Background and constraints

- The AI Enrichment handoff already preserves source, classification IDs,
  exclusion reason, pending limit, and page context; the governance route then
  loads the bounded queue (`frontend/src/components/ai/AIEnrichmentPage.jsx:1037`,
  `frontend/src/components/jobIntelligence/JobIntelligenceGovernancePage.jsx:421-468`).
- The queue already renders ten items per page and shows `Showing N of M
  matching items`, but the canonical adapter labels each row only as `Job
  <UUID>` (`frontend/src/components/jobIntelligence/governanceAreas.js:54-90`,
  `frontend/src/components/jobIntelligence/GovernanceQueue.jsx:107-135`).
- The scoped page already has a source/category/reason banner, while the detail
  idle state remains generic: `Select an item to review its evidence and audit
  history.` (`frontend/src/components/jobIntelligence/JobIntelligenceGovernancePage.jsx:407-420,548-557`).
- The canonical review API currently exposes `job_id` but no title or company
  label (`backend/app/schemas/job_intelligence.py:335-356`; the read model maps
  the review row directly at
  `backend/app/job_intelligence/canonical_taxonomy/read_model.py:264-309,799-816`).
- Existing Jobs have a non-null title, required Company relationship, and
  Company name convenience data (`backend/app/models/job.py:35-75,180-191`).
  The review read contract can therefore add operator-facing labels from
  existing data without creating a new identity authority.
- The AI exclusion detail already has a human-readable source classification
  name, but the governance handoff currently serializes only source-qualified
  IDs and reason (`frontend/src/components/ai/AIEnrichmentPage.jsx:46-60,1021-1037`).
- The previous scoped governance task established that provenance repair is
  restricted to the current bounded AI Enrichment batch and that the selected
  row is an entry point into that batch, not a single-job repair authority
  (`.trellis/tasks/archive/2026-07/07-22-cross-source-it-ai-enrichment/prd.md`,
  resolved product decisions).

The fix must not alter pending selection ordering, page size, scope resolution,
fail-closed provenance checks, provenance inspect/apply fences, audit/version
behavior, or any persisted data. No first row is special and the page must not
auto-select it.

## Requirements

### R1. Operator-facing Job identity

- All Job Taxonomy Review queue rows expose the Job title and Company name as
  the primary identity, with a readable fallback if either display field is
  unavailable.
- The technical Job UUID is not the primary queue selection cue.
- The selected-item technical evidence/audit area continues to expose the exact
  UUID for support and audit tracing.

### R2. Scoped context and count

- The scoped governance surface keeps the current source, human-readable IT
  category label, source-qualified category ID, exclusion reason, and the
  existing total/matching-item count visible.
- The category label is display-only metadata carried by the AI-to-governance
  handoff. Source-qualified IDs remain the sole authority for queue filtering,
  scope resolution, and provenance repair.

### R3. Selection and batch guidance

- The existing scope banner gains concise, prominent guidance that any row is a
  valid evidence entry point and that provenance inspection/repair applies to
  the current bounded batch, not only the selected Job.
- The empty detail panel repeats a shorter version of that guidance before a
  row is selected.
- Selecting a row still loads that Job's evidence and audit history; it does not
  change the batch scope or imply that the first row is preferred.

### R4. Safety and compatibility

- Existing source filtering, page/cursor navigation, queue focus, narrow-layout
  Back behavior, canonical decisions, provenance repair, and fail-closed
  preflight behavior remain unchanged.
- Skill Candidates and Company Industries governance surfaces remain unchanged
  except for shared layout behavior they already consume.
- Missing display labels do not make a valid review item unreadable and never
  broaden or narrow the authoritative review query.

## Acceptance criteria

- [x] Every canonical Job Taxonomy queue row displays a useful title/company
      identity instead of requiring UUID selection.
- [x] Selected Job detail exposes the exact Job UUID under technical evidence or
      audit details.
- [x] A scoped queue visibly retains source, human category label, technical
      category ID, exclusion reason, and `Showing N of M matching items` context.
- [x] The scope banner and empty detail state explain that any row can be used
      to view evidence and that provenance inspection/repair is batch-scoped.
- [x] The first row is not auto-selected and no UI copy implies that it is
      special or recommended.
- [x] The display-only category label is round-tripped through the deep link but
      is absent from backend scope/filter authority.
- [x] Existing scoped filtering and fail-closed provenance checks remain
      unchanged.
- [x] Backend, frontend route/API, AI Enrichment, queue, and Governance Page
      tests cover the new fields, guidance, fallback behavior, and no-first-row
      selection behavior.

## Out of scope

- Changing AI/LLM models, prompts, workers, retries, concurrency, or pending
  batch semantics.
- Changing provenance inspection/apply contracts or adding per-row repair.
- Adding a Job/Company endpoint, source catalog lookup, database migration, or
  bulk selection control.
- Redesigning unrelated governance areas.

## Resolved product decisions

- Use separate Job title and Company name fields as the queue identity; keep
  UUID in selected technical detail rather than the primary row label.
- Apply title/company fields to all Job Taxonomy Review rows; show batch-entry
  guidance only when an AI Enrichment scope is active.
- Carry the human-readable source classification label as display-only route
  metadata instead of fetching Source Catalog again on the governance page.
- Do not auto-select the first row. Use the existing scope banner for prominent
  guidance and the empty detail state for a concise repeat.

## Open questions

None currently block the planning draft.

## Approved scope extension: automatic taxonomy recovery

The operator review experience exposed a larger operational problem: a
Job Taxonomy queue with thousands of items is not an acceptable manual
classification workflow. The approved follow-up scope is:

- Keep AI Enrichment responsible for automatic selection from the existing
  governed Canonical Job Taxonomy.
- Repair incomplete classifier provenance, including a stable model version,
  without weakening the fail-closed evaluator.
- Keep transient AI upstream failures distinct from valid-but-invalid
  classifier output and from missing Source evidence.
- Add a bounded, preview/confirm, asynchronous Canonical-only re-evaluation
  for historical Jobs in the current scope. It processes
  `classifier_output_invalid` and `classifier_provenance_missing` reviews,
  accepts only valid existing governed targets, and leaves unresolved items
  active in Review.
- Preserve the existing report-first Source Catalog provenance repair for
  `source_catalog_provenance_missing`.
- Keep `source_classification_paths_missing` read-only in Governance; source
  recollection or Source Attribute rebuilding remains an external workflow.
- Do not add a blanket batch `insufficient evidence` action or direct crawling
  from Governance.
