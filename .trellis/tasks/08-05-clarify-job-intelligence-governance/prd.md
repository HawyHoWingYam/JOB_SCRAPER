# Clarify Job Intelligence governance workflow

## Goal

Make governed Job Skills reliably support cross-Job search and filtering while removing Company Industry from the current product scope and replacing the confusing manual classification workflow with a small, understandable Skill review queue.

## Background and confirmed facts

- Job enrichment extracts Skill Mentions independently of classification batches. Existing governed Skills become assignments; unresolved terms become Skill Candidates; broad terms may become Generic Skill Tags; rejected terms remain evidence. See `backend/app/services/ai_enrichment_service.py:31-113` and `backend/app/job_intelligence/current_taxonomies/enrichment.py:125-229`.
- Job Detail shows governed assignments separately from unresolved candidate evidence. With no assignments, enriched Jobs can show candidate evidence while reporting that no governed Skills matched. See `backend/app/job_intelligence/product_read_model.py:48-125,343-354` and `frontend/src/components/JobDetailModal.jsx:389-408,602-615`.
- Skill normalization is needed for reliable cross-Job Skill search and filtering. Raw extracted terms alone are insufficient for the current product.
- The current runtime database has no Skill taxonomy nodes and no canonical Job Skill assignments. The observed snapshot held 59,049 active candidate mentions across 8,573 Jobs, 11,349 unresolved Skill Candidates, 1,673 generic-tag mentions, and 2,655 rejected mentions.
- The observed Skills run `189e0842-615c-4ce7-b091-0c9d3263b5f2` processed five candidates: SQL was disposed as a Generic Skill Tag, while Python, Java, Linux, and JavaScript failed because no valid placement path was available.
- The bundled Skill taxonomy manifest exists, but production bootstrap currently creates tables without synchronizing it. `_placement_paths` therefore returns no valid paths, and the batch has no Skill-taxonomy readiness guard.
- The current threshold is persisted as `skill_auto_create_distinct_job_threshold`, validated between 1 and 1000, and exposed in Settings. Its current default is 5; the product decision is to set the current value to 10 while keeping it configurable. See `backend/app/services/ai_runtime_settings_service.py:23-25,586-600,722-741` and `frontend/src/components/settings/AISettingsPage.jsx:1145-1155`.
- Company Industry is currently consumed by Job search filters/facets and Company/Job detail surfaces (`backend/app/api/jobs.py:364-397`, `backend/app/services/job_search_facets.py:229-270`, `backend/app/job_intelligence/product_read_model.py:189-231`), but the operator does not need that capability now.

## Product decisions

- Skill is the current Job Intelligence priority. Its primary user value is reliable Job Skill search and filtering; coverage dashboards and governance tooling are supporting mechanisms.
- Company Industry normalization is removed from the current product scope. Delete its user-facing frontend, API/domain paths, database tables, and retained historical data through the project's explicit destructive sandbox cutover. Do not accidentally remove shared infrastructure required by Skills.
- The bundled Skill taxonomy manifest is the initial governed taxonomy baseline. Synchronize it before Skill enrichment or governance work runs, then idempotently reproject retained Skill Mention evidence.
- Deterministic existing-name and alias matches, explicit generic rules, and explicit rejection rules happen automatically. An LLM decision alone cannot create a governed Skill.
- A Taxonomy Operator explicitly confirms a new Skill. Creation is allowed only beneath an existing active Category → Technology path; review cannot create new taxonomy parents. If no valid parent exists, the Candidate remains pending.
- Replace manual batch controls with a continuously maintained list of Skill Candidates ready for operator review. No batch size, preview, start, progress, or failed-only retry controls are part of the operator workflow.
- Candidate readiness remains backed by the existing Settings field rather than a hardcoded value. Set the current configured threshold to 10 distinct Jobs and relabel the setting to describe entry into the review list, not automatic Skill creation.
- Job Detail presents governed Skill assignments as ordinary Skills and makes only those assignments filterable. Unresolved Skill Mention evidence is visually secondary, collapsed, explicitly awaiting review, and not filterable. Generic and rejected evidence remain traceable but are not ordinary Skills.

## Requirements

- Provide an idempotent initial Skill taxonomy synchronization path and a readiness contract that blocks Skill enrichment/governance when the taxonomy is unavailable.
- Reproject historical Skill Mention evidence after synchronization without duplicating assignments, losing evidence, or silently overwriting Taxonomy Operator decisions.
- Provide a Skill Candidate review API and UI that lists ready Candidates, shows evidence and the suggested existing parent path, and supports explicit operator decisions.
- Reuse the current threshold setting for readiness selection, set its current value to 10, and update user-facing copy without hardcoding 10 into selection logic.
- Preserve current Skill Mention provenance, generic tags, rejected mentions, Candidate aggregation, and auditability.
- Remove Company Industry UI, user-facing API/domain paths, persistence tables, retained data, and related tests/spec references; preserve only shared code still required by Skills.
- Make empty taxonomy, missing evidence, invalid placement, and pending decisions visible in plain operator language with no misleading “no skills found” state.

## Acceptance criteria

- [ ] The product purpose of the Operations Dashboard, Skill review surface, and Job Detail evidence is stated in operator language.
- [ ] Company Industry frontend, user-facing backend paths, database tables, historical data, and dependent tests are removed by the documented destructive sandbox cutover without regressing Skill paths.
- [ ] Skill taxonomy synchronization is idempotent, runs before dependent work, and has a testable readiness failure state.
- [ ] Historical Skill Mention reprojection is idempotent, preserves evidence, and creates canonical assignments only for valid governed Skills.
- [ ] Existing Skill names and aliases bypass Candidate review; explicit generic/rejected rules bypass LLM placement.
- [ ] An LLM-only decision cannot create a governed Skill; operator confirmation can create one only under an existing active Category → Technology path.
- [ ] Candidate readiness reads the persisted Settings field, accepts the configured value 10, and the Settings label no longer claims automatic creation.
- [ ] The Skill review surface has no batch size, preview, start, progress, or failed-only retry controls.
- [ ] Job Detail distinguishes governed Skills from unresolved evidence, and unresolved evidence cannot enter Skill filters.
- [ ] Empty taxonomy and invalid placement states are explicit and actionable.
- [ ] The user reviews and approves the final PRD, design, and implementation plan before `task.py start`.

## Out of scope

- New Company Industry behavior, replacement mappings, or migration of Company Industry data after deletion.
- Automatic creation of new taxonomy Category or Technology parents.
- Implementation or production data changes before planning approval and task activation.
