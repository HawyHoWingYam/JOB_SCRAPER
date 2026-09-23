# Implementation plan: Stop localized generic Skills from retrying

- [x] Add failing tests for `項目管理`, `銷售`, and `客戶服務`: canonical tag, raw evidence, no LLM call, no Skill assignment, and zero unresolved Candidate counts.
- [x] Add a failing regression proving failed-only Retry cannot select a Candidate after governed generic resolution.
- [x] Extend `skill_curation_rules.json` with canonical multilingual generic aliases.
- [x] Replace ASCII-only generic lookup with a shared Unicode-safe local disposition resolver while preserving existing rule compatibility and precedence.
- [x] Apply the resolver before Candidate creation in `replace_job_skills`.
- [x] Apply the same resolver before LLM placement in `SkillClassificationAdapter` to repair existing Candidates.
- [x] Run `cd backend && pytest -q tests/test_current_taxonomies.py tests/test_classification_batch_runtime.py` (29 passed).
- [x] Run backend Ruff (passed) and Mypy (executed; repository baseline has 257 existing errors across 20 modules, with none reported in the new curation module).
- [x] Review transaction boundaries: no partial Skill, Mention, Candidate, or Job projection write may survive an exception.
- [x] Update the automated-classification/current-taxonomy specs with the multilingual terminal-disposition contract.
- [x] Closure evidence for #36 uses the focused automated assertions plus the
  2026-09-23 full backend/frontend/E2E regression. Separate human browser QA was
  explicitly waived by the user.

## Rollback point

Revert the shared resolver and rule entries together. Do not leave ingestion and batch processing with different curation semantics.
