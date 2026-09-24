# Unify Jev processing and simplify experience display

## Goal

Make ordinary AI enrichment produce usable Skills independently, add a separate Jev pass, simplify experience-year presentation, and consolidate Jev operations into one page. Product decisions are recorded below; the complete plan awaits final review before implementation.

## Requirements

- R1 (confirmed): Ordinary AI enrichment must process Skills itself; Jev must perform an additional pass. Ordinary AI results must not depend on Jev being enabled or succeeding.
- R2 (confirmed): Prefer one numeric lower-bound label for experience: at least two years becomes `2+`; one to two years becomes `1+`. Preserve source evidence and stored bounds. Audit and update search-related code as needed so compact display, filtering, result totals, facets, pagination, and exports remain coherent; retain inclusive overlap against the original experience bounds, not filtering by the compact displayed minimum. Clarify the filter as the experience range required by the Job and make the original bounds inspectable. Both search result cards and Job Detail must use the compact format: minimum/range lower bound as `N+`, explicit no-experience as `0+`, upper-only as `≤N`, unspecified as `未注明` (localized equivalent), and inferred minimum as `约 N+` with explicit estimated provenance. Job Detail retains the complete original range and source explanation. Missing/unprocessed data must not be fabricated as zero or an estimate; inferred values depend on the policy owned by issue #61.
- R3 (confirmed): Consolidate Jev operations into one page. The operator selects one bounded Job batch, chooses any combination of Skills correction, Possible same vacancy, and Related Jobs, and starts all selected operations with one explicit action. Show progress and results separately for each operation. Jev operations with different subjects, including taxonomy maintenance, search relevance advisory, incident triage, and crawl content quality, are available on the same page with their own explicit manual starts. Selection supports Source, keyword, processing-status filters, explicit Jobs, and a maximum Job count; historical Jobs can be selected. Proposed configuration placement is documented in design.md for final review.
- R4 (confirmed): Include Jev processing for both Possible same vacancy and Related Jobs in the selectable Job batch operations. Preserve their separate meanings: suspected duplicate identity versus similarity. For Related Jobs, existing vector retrieval supplies a bounded candidate set; manually started Jev processing filters and ranks candidates using Job content and supplies short reasons. Persist the result for read-only display in Job Detail. Before any successful Jev evaluation, display existing algorithmic recommendations labeled as not evaluated by Jev. A successful empty Jev result is authoritative: display no related Jobs instead of refilling with rejected candidates. When supporting Job evidence changes, mark affected Jev recommendations as awaiting reevaluation and retain their history, but show current algorithmic recommendations labeled as awaiting Jev reevaluation. Never trigger Jev on invalidation. When evidence is unchanged, a failed rerun retains the previous successful result, including an authoritative empty result.
- R5 (confirmed): AI Skill results take effect first. A successful later Jev pass may add, correct, or remove AI-generated Skills and update the effective result; preserve the AI baseline and correction provenance. If Jev fails, retain the prior usable result. On an AI rerun with unchanged source Job text, refresh the AI baseline but retain the effective Jev-corrected Skills. When source text changes, mark the old Jev result as awaiting reevaluation and use the newly generated AI Skills until a manually started Jev pass succeeds; retain historical results and never automatically rerun Jev. Operator-authored Skill corrections take precedence and must not be silently overwritten by either AI or Jev.
- R6 (confirmed): All Jev processing must be explicitly started by the operator. Ordinary AI enrichment must not invoke Jev automatically. Remove scheduled Jev initiation, including taxonomy maintenance; page reads, crawl completion, and search must not implicitly launch Jev processing. A manually started bounded run may execute in the background. Stop prevents new requests while preserving completed results; stopped runs and runs interrupted by service restart require explicit manual resume. Failed items require manual retry.
- R7 (confirmed investigation scope): Review existing search correctness, usability, and performance opportunities alongside the experience change. Prioritize applied search-mode consistency, stale Jev previews, capability-failure behavior, experience-filter clarity, and cross-mode regression coverage. See research/search-audit.md for evidence and proposed fixes; performance changes require measurement rather than assumed index benefits.
- R8 (confirmed): Eligibility is tracked per selected operation. By default select unprocessed, changed-evidence, or previously failed items and skip successful unchanged items; permit explicit force reevaluation. Before starting, preview selected Job count and actual eligible count per operation. Partial failures preserve successful results and allow independent work to continue; retry only the failed items when manually requested.
- R9 (confirmed): Jev API Console is the sole monetary-limit authority. Remove local allowances, reservations, token price rates, cost ceilings, local cost estimation, and monetary dispatch gates. Retain explicit manual authority and non-monetary operational limits. Provider-returned usage and cost may remain as audit receipt data and must not block dispatch.
- Coordinate experience presentation with existing issue #61 (searchable experience-year enrichment); this issue does not silently absorb its historical repair or inference scope.

## Acceptance Criteria

- [ ] With Jev disabled or unavailable, successful ordinary AI enrichment still produces the applicable Skill assignments/candidates, without incorrectly claiming no technical skills were extracted.
- [ ] AI Skills are usable before Jev runs. A manually started successful Jev pass can add/correct/remove AI Skills with traceable provenance; failed Jev processing preserves usable results.
- [ ] Reenrichment with unchanged source text preserves effective Jev corrections while updating the AI baseline. Changed text invalidates the old Jev result and uses the new AI result pending manual reevaluation; historical results remain traceable.
- [ ] Operator-authored Skill corrections survive both ordinary AI and Jev processing.
- [ ] No Jev work starts from AI enrichment, schedules, page reads, crawl completion, or search without an explicit operator start. Tests cover the existing inline classification and scheduled maintenance paths.
- [ ] Both search cards and Job Detail show minimum 2 as `2+`, range 1–2 as `1+`, explicit no-experience as `0+`, upper-only 2 as `≤2`, unspecified as `未注明` (localized equivalent), and inferred minimum 3 as `约 3+` with estimated provenance. Stored numeric bounds and search semantics are preserved; detail exposes original range/source evidence.
- [ ] On one Jev page, selecting a Job batch and any combination of the three Job operations allows one manual start to launch all selected work, with separate progress/results and no unselected operation executed.
- [ ] Other Jev operations have separate manual starts on that same page. The console exposes bounded scope, progress, failures, retry, and provider receipt visibility when available.
- [ ] Preview reports selected Jobs and per-operation eligible counts without a local cost estimate. Unchanged successful items are skipped unless force reevaluation is explicitly selected; historical Jobs are selectable.
- [ ] Partial failure preserves successes and does not abort independent work. Failed-item retry, stopped-run resume, and service-restart recovery all require explicit operator actions; stop prevents new requests.
- [ ] Possible same vacancy retains separate source records; Related Jobs remains distinguishable from duplicate identity.
- [ ] Related Jobs uses bounded retrieval followed by manually initiated Jev filtering/ranking with short reasons and persisted results. Job Detail reads do not call Jev.
- [ ] Related Jobs distinguishes never-evaluated fallback, stale-evidence fallback labeled awaiting reevaluation, unchanged-evidence failed reruns retaining prior success, and successful empty evaluations with no algorithmic refill. Historical results remain traceable and invalidation causes zero Jev calls.
- [ ] For query 3–4 years, a Job requiring 1–2 years is excluded and a Job requiring 1–5 years is included, even though both have compact label `1+`. Original bounds remain inspectable and filter wording explains range overlap.
- [ ] Experience cases are validated across lexical, semantic, and hybrid candidate filtering, contextual facets, and CSV export using a shared matching policy; compact display does not silently redefine that policy.
- [ ] Search improvements selected from the audit bind displayed results, counts, pagination, and exports to one applied search state, and fence stale Jev previews to their original scope/mode.
- [ ] Planning questions are resolved and the user reviews the final plan before implementation begins.

## Confirmed Current Behavior

- Ordinary AI extracts Skill candidates, then inline Jev classification gates nonempty Skill projection: `backend/app/services/ai_enrichment_service.py:59-110,150-185`. Disabled Jev preserves prior assignments rather than persisting the new AI candidates.
- `jev_disabled` records an unavailable classification without a provider request: `backend/app/services/jev_online_skill_runner.py:71-96,261-268`.
- Governed Skills and latest Jev receipt are distinct UI elements: `frontend/src/components/JobDetailModal.jsx:645-701`.
- Experience display currently emits ranges, minimums, or upper bounds: `frontend/src/components/JobDetailModal.jsx:101-129`. Storage already has separate numeric bounds: `backend/app/models/job.py:78-80`.
- Possible same vacancy already uses Jev: `backend/app/services/jev_duplicate_association.py:108-185,329-369`.
- Related Jobs currently uses vector similarity (80%), governed Skill overlap (15%), and freshness (5%): `backend/app/services/job_recommendation_service.py:45-60,76-145`.
- Scheduled Skill maintenance currently launches Jev work: `backend/app/services/scheduler_service.py:283-325` and `backend/app/services/jev_skill_maintenance.py:87-177`; this conflicts with the newly confirmed manual-start requirement.
- Jev controls are distributed across AI Enrichment, Classification, Settings, Job Detail, Job Browser, and Crawl Tasks. Settings already exposes shared bounded run history: `frontend/src/components/settings/AISettingsPage.jsx:1849-1951`.

## Final Review Items

The remaining review concerns the concrete design and execution plan, not unresolved core product behavior:

- Keep credentials and model defaults in Settings with a direct link from the unified Jev page; move processing, previews, histories, stop/resume/retry, and explicit smoke execution into the unified page.
- Include the audit's applied-mode consistency, stale-preview fencing, and capability-unavailable handling fixes. Performance changes remain conditional on measurements.
- Review the phased work map and issue #61 dependency in implement.md before activation.

## Out of Scope

- Implementation before the planning interview and review are complete.
- Merging, hiding, or deleting Jobs solely on duplicate-association results.
- Treating the requested experience display simplification as permission to rewrite stored source bounds.

## Planning Structure

This issue is the planning umbrella. `design.md` defines the proposed contracts and `implement.md` splits delivery into independently verifiable work packages with explicit dependencies. Keep the current task in planning; implementation sessions should create/link child tasks for those packages from this approved source rather than activating the umbrella as one monolithic change. Existing issue #61 remains a separately owned dependency for inferred experience windows and historical repair.
