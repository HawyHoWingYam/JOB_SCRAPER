# Stop localized generic Skills from retrying

## Goal

Fix GitHub issue #36 so localized generic Skill mentions resolve without entering an endless failed-only retry loop.

## Background

- Local generic/rejection rules are loaded from `backend/app/data/skill_curation_rules.json`.
- The current loose matching key retains only ASCII letters and digits. Chinese labels therefore normalize to an empty key and cannot match the English-only rule set.
- Unmatched candidates proceed to LLM placement. An `uncertain` result correctly remains failed and Retry-eligible, which turns permanently unrecognized localized generic terms into a retry loop.
- QA reproduced the defect with `項目管理`, `銷售`, and `客戶服務`; no partial Skill node was created.

## Requirements

- Localized generic Skill Mentions must be recognized before LLM placement when governed curation data already defines their disposition.
- Known localized generic terms are governed by explicit multilingual curation data. Runtime translation or fresh LLM inference must not override that known disposition.
- Multilingual aliases resolve to one canonical Generic Skill Tag while the originating Skill Mention retains its raw localized evidence.
- Unknown candidates may continue through the existing LLM placement flow.
- A generic resolution must be terminal: the originating candidate has no remaining unresolved occurrences and failed-only Retry does not select it again.
- Generic resolution must not create a Skill or ordinary Skill assignment.
- Existing alias reuse, rejection, atomic Skill creation, uncertain-placement failure, and rollback semantics must remain intact.

## Acceptance Criteria

- [ ] `項目管理`, `銷售`, and `客戶服務` exercise the agreed governed localized disposition without LLM placement.
- [ ] Repeating a known localized input produces the same disposition without a translation or LLM dependency.
- [ ] Localized aliases of the same broad concept produce one canonical Generic Skill Tag while retaining each raw mention value.
- [ ] Resolved generic mentions retain traceability to their originating candidate and no longer contribute unresolved candidate counts.
- [ ] Failed-only Retry excludes candidates fully resolved to a generic outcome.
- [ ] No Skill taxonomy node or ordinary Skill assignment is created for a generic outcome.
- [ ] Existing English generic-term and uncertain-placement tests remain green.
