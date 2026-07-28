# Add dashboard Classification actions

## Goal

Turn Dashboard assignment gaps into safe Classification navigation backed by truthful readiness populations: classification-ready taxonomy Jobs open Job Taxonomy classification, while threshold-ready Skill Candidates open Skill classification.

## Requirements

- Add a durable Classification route target for `job_taxonomy` and `skill` that survives refresh and sharing.
- Preserve existing bare `#classification` behavior with Job Taxonomy as the default.
- Navigate from the taxonomy unassigned signal to Classification with Job Taxonomy selected.
- Define Job Taxonomy Classification readiness as non-deleted, currently unassigned Jobs with the required source-attribute projection, and use the same predicate for the Dashboard ready count and Classification preview.
- Navigate from the ready Skill Candidate signal to Classification with Skill selected.
- Navigation must not automatically preview, start, retry, or otherwise mutate a Classification batch.
- Invalid route targets must fall back safely without crashing or selecting an unknown domain.
- Keep response fields and Dashboard signal rendering owned by the parent stats task; this child owns the shared readiness predicate, Classification preview alignment, and action/route behavior.

## Acceptance Criteria

- [ ] The taxonomy action reports the Classification-Ready subset and opens Classification with `job_taxonomy` selected.
- [ ] Job Taxonomy Classification preview selects the same readiness population as the Dashboard action before optional source filters and limits.
- [ ] Jobs missing the required source-attribute projection remain visible in total unassigned coverage but are excluded from the ready count and preview rather than entering a predictably failing batch.
- [ ] The ready Skill Candidate action opens Classification with `skill` selected.
- [ ] Refreshing or sharing each targeted route preserves the selected Classification domain.
- [ ] Bare `#classification` retains its existing Job Taxonomy default.
- [ ] Invalid targets fall back to the default and do not issue a batch mutation request.
- [ ] Changing tabs updates the durable route without discarding normal Classification page behavior.
- [ ] Actions and tabs are keyboard operable and expose clear accessible names.

## Notes

- Depends on the parent task exposing taxonomy-unassigned, taxonomy-ready, and threshold-ready Skill Candidate counts.
- Automatic batch start, preconfigured source filters/limits, Jobs drill-down, and Classification workflow redesign are out of scope.
