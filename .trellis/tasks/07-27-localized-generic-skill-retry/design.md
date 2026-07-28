# Design: Stop localized generic Skills from retrying

## Curation contract

Extend `backend/app/data/skill_curation_rules.json` with an explicit mapping from multilingual aliases to canonical Generic Skill Tags. Existing `generic_terms`, `suppressed_review_terms`, and `canonical_aliases` remain valid.

Initial aliases include:

- `項目管理` → `Project Management`
- `銷售` → `Sales`
- `客戶服務` → `Customer Service`

Alias keys use the existing Unicode-safe exact Skill normalization, not ASCII-only `_loose_key`. The raw Skill Mention remains unchanged; only `generic_tag` receives the canonical label.

## One disposition seam

Create one curation resolver that returns a structured local disposition: match-existing, generic with canonical tag, reject with stable reason, or no local decision. Reuse it at both boundaries:

1. `CurrentTaxonomyEnrichment.replace_job_skills` applies known generic/reject decisions before Candidate upsert, so new known localized Mentions never create unresolved Candidates.
2. `SkillClassificationAdapter.process_candidate` applies the same resolver before LLM placement, so already-persisted Candidates are repaired to a terminal disposition.

Generic resolution continues to clear active `candidate_id`, retain `origin_candidate_id`, zero Candidate counts, and reproject affected Jobs without creating `current_job_skill_assignments`. Unknown terms retain the existing LLM create/generic/reject/uncertain flow.

## Compatibility

- No schema change: `generic_tag` already stores a string and raw Mention evidence already persists separately.
- English `generic_terms` behave as canonical self-mappings.
- Existing exact Skill aliases retain precedence over generic disposition.
- Uncertain unknown placement remains a retryable failure; this fix does not convert uncertainty into a generic result.

## Validation

- Prove all three localized aliases bypass the LLM and resolve to canonical tags.
- Prove raw evidence and origin Candidate lineage remain available.
- Prove repeated ingestion is deterministic and does not recreate Candidates.
- Preserve English generic, suppressed, alias reuse, atomic creation, uncertain failure, and rollback tests.
