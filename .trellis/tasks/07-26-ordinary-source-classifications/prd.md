# Replace Source Catalog with ordinary classifications

Parent: `07-26-excluded-jobs-governance-handoff`

## Goal

Remove Source Catalog version governance and implement one ordinary
Source-qualified classification registry plus top-level crawl scope across
JobsDB, OfferToday, and CTgoodjobs.

## Requirements

- Directly synchronize/upsert Source classifications; no candidate, publication,
  active revision, rollback, or provenance repair.
- Expose only active top-level classifications for new crawl authoring while
  preserving inactive roots and complete child-path Job evidence.
- Simplify authored scope to Source plus all/selected active top-level IDs.
- Let each Source adapter compile a dedicated query or documented broader-fetch
  fallback; reject malformed query data.
- Remove Source Catalog UI/API/schema/specs and revision references from Source
  attributes, crawl scope, dispatch, and AI preflight.
- Missing Source mapping/provenance never blocks AI solely for that reason.

## Acceptance Criteria

- [ ] All three Sources populate the same ordinary registry before first ingest.
- [ ] Ingest idempotently fills missed classifications and preserves child paths.
- [ ] Label update and confirmed disappearance produce current/inactive state
      without physical deletion or historical Job rewrite.
- [ ] New crawl authoring uses only all/selected active roots; source-specific
      query/fallback tests pass.
- [ ] No Source Catalog publication/revision/provenance repair production seam
      remains, and AI preview does not emit the removed blockers.

## Dependency

First implementation child. It must expose stable Source classification IDs and
scope contracts consumed by later taxonomy/runtime/cutover children.
