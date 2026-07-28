# Add Company Industry source-mapping setup path

## Goal

Fix GitHub issue #38 by providing a production-supported path to establish Company Industry source mappings and preventing guaranteed-failure batches.

## Background

- Company Industry projection reads retained `Source Industry Label` evidence from a Company's Jobs and resolves a mapping keyed by taxonomy, Source, and normalized source label.
- The mapping table and provenance-bearing Company Industry Assignments already exist, but production has no mapping import path or mapping dataset.
- Company Industry candidates are unassigned Companies filtered by the selected Sources and limit.
- Batch execution already isolates items: a mapped Company may succeed while an unmapped Company fails without rolling back other items.
- Existing taxonomy synchronization imports governed JSON node data, but Source Mapping import needs its own validated current-state manifest because mappings have different identities and lifecycle semantics.
- Current canonical taxonomy synchronization is exercised directly by tests and has no production startup, CLI, or migration entry point.
- The repository intentionally has no in-place database migration/version system; database bootstrap is schema-only and refuses non-empty databases.
- Existing automatic startup synchronization applies only to Source Classification Registries and logs failures without preventing API startup.
- Current inspection found 47 distinct non-empty structured OfferToday `industry.name` labels plus 7 retained compatibility-only `company_industry` labels used when structured evidence is absent: 54 runtime Source Industry Label identities in total. The loaded Company Industry Taxonomy has 1,814 active nodes, of which 1,001 are assignable.
- Only two observed OfferToday labels exactly match taxonomy labels, and both targets are non-assignable ancestor nodes. An automatic display-name join therefore cannot produce the initial production mappings safely.
- Production currently has zero Company Industry Source Mappings; existing mapping rows cover only Job Taxonomy.

## Requirements

- Provide a repeatable import/seed mechanism for the current Company Industry Source Mapping state.
- Do not introduce product-level mapping versions, releases, revision history, or version selection.
- Treat the manifest as the complete current mapping state for each Source it contains and synchronize that Source atomically.
- Remove existing mappings for a synchronized Source when they are absent from its current manifest data.
- The initial OfferToday manifest must disposition every currently observed non-empty Source Industry Label.
- Each manifest entry must either map to one or more active assignable Company Industry targets or record an explicit non-mapping disposition with a reason.
- Broad evidence must not be forced onto a more specific Company Industry merely to increase coverage.
- Synchronize mappings through an explicit, idempotent management command intended for deployment use.
- Validate the complete manifest before mutation, fail the command on invalid data, and report a deterministic per-Source change summary.
- Do not synchronize governed mappings automatically during API startup.
- Validate imported Source Industry Label identities and Company Industry targets before applying changes.
- Expose whether the selected Company population has usable mapping evidence.
- Block Start when the selected population has no usable mapping evidence and therefore cannot produce any successful Company Industry Assignment.
- Compute readiness against the exact candidate population selected by current Source/limit inputs, not against unrelated mappings elsewhere in the database.
- Permit Start when at least one selected candidate has usable mapped evidence; block only when the selected candidate population has zero usable mappings.
- Report selected, mapped, and unmapped candidate counts so partial coverage is explicit before Start.
- Preserve per-item failure isolation for unmapped candidates in a partially ready batch.
- Treat an explicit non-mapping disposition as a governed terminal exclusion during candidate selection, not as a failed Batch item.
- Report explicit non-mapping exclusions separately in Preview and exclude them from failed-only Retry.
- Reserve failures for missing dispositions, invalid/inactive targets, or malformed/contradictory evidence.
- Preserve the rule that Company Industry is based on company-level evidence and is never guessed from a Job's function.
- Defer a full operator-facing mapping CRUD editor.

## Acceptance Criteria

- [ ] A production deployment can install a reviewed mapping set without direct database mutation.
- [ ] The management command exits unsuccessfully without mutation when validation or synchronization fails, so deployment can stop visibly.
- [ ] A successful command reports deterministic created, updated, removed, and unchanged counts per Source.
- [ ] Reapplying the same mapping data is safe and deterministic.
- [ ] Synchronizing one Source creates/updates the supplied mappings and removes stale mappings for that Source in one transaction.
- [ ] A failed synchronization leaves the Source's previous mapping state unchanged.
- [ ] All 54 currently observed non-empty OfferToday runtime Source Industry Label identities have an explicit reviewed disposition in the initial manifest.
- [ ] A mapping may target only active, assignable Company Industry nodes; broad labels without defensible leaf-level evidence use an explicit non-mapping disposition.
- [ ] Invalid Source or Company Industry identities reject the import without partial application.
- [ ] The Automated Classification UI reports Company Industry mapping readiness before Start.
- [ ] Start is disabled with an actionable reason when no selected Company has usable mapped evidence.
- [ ] Mapping readiness cannot be satisfied by mappings that do not apply to any currently selected candidate.
- [ ] Preview reports selected, mapped, and unmapped counts; `mapped > 0` permits Start and `mapped = 0` blocks it.
- [ ] A partially mapped batch completes mapped items and isolates unmapped failures without rolling back successful assignments.
- [ ] Explicit non-mapping candidates appear in the Preview exclusion count, produce no Batch item, and never enter failed-only Retry.
- [ ] Missing dispositions and invalid mapping targets remain visible, actionable failures rather than being silently treated as non-mapping.
- [ ] With valid mapped evidence, at least one real Company success path completes and records provenance-bearing assignments.
- [ ] Existing no-guess and transaction rollback tests remain green.

## Out of Scope

- A general-purpose mapping CRUD editor.
- Inferring Company Industry from job-title or job-function evidence.
- Product-level mapping versions, releases, or revision history.
