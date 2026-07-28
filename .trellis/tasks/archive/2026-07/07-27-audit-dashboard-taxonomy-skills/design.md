# Design: trustworthy dashboard taxonomy and Skill analytics

## Product role

Keep the Dashboard as an internal Operations Dashboard. The taxonomy and Skill sections are secondary corpus snapshots for observing canonical-assignment health and retained-corpus distribution; they are not evidence of current labor-market demand. Do not add market-analysis filters or silently reinterpret source expiry as an active-listing predicate in this task.

## Boundary and population contract

Create one reusable backend predicate/query seam for the dashboard population: non-deleted acquired Jobs. Overview, Job Taxonomy, and Skill stats must either use that seam or prove equivalent filtering in contract tests. “Current” continues to mean current canonical state; no Python `is_expired` property is translated into an implicit SQL filter.

## Job Taxonomy flow

Keep the stable-code assignment as authority and the top-six-plus-Other projection. Lead the card with assigned Jobs, unassigned Jobs, and Canonical Assignment Coverage against the shared Dashboard population; treat the distribution as the secondary view among assigned Jobs. Simplify the response to current fields only: the shared population denominator, total accepted assignments, top categories, and an `Other` summary with its constituent concrete rows. Keep numerator and denominator in one response snapshot rather than coupling the component to independently timed totals. Show the full Domain / Category / Subcategory breadcrumb as visible secondary text.

Render `Other` as an accessible expand/collapse control. Its expanded content exposes the remaining deterministically ordered concrete paths and counts; `Other` itself carries no canonical code and is never treated as one taxonomy identity.

Return `unassigned_total` for all non-deleted Jobs without a current accepted assignment and `classification_ready_unassigned_total` for the subset that also has the source-attribute projection required by Job Taxonomy classification. Coverage uses `unassigned_total`; action copy uses the ready subset. Readiness describes known prerequisites, not a guarantee that the classifier will select a reliable taxonomy target.

## Skill flow

Join Skill assignments to the shared Job population and aggregate by stable Skill code plus display labels. Sort by count descending and stable code ascending. Bound the API limit with FastAPI validation.

Return a Skill matching summary in the same response snapshot: distinct successfully enriched, non-deleted Jobs as `processed_total`, distinct Jobs in that cohort with at least one current canonical Skill assignment as `matched_job_total`, and the derived Canonical Skill Match Coverage. Do not use all acquired Jobs as the match denominator because that would conflate pending enrichment with completed extractions that produced no canonical match. Candidate resolution may update current assignments after extraction, so the metric describes current match state within the successfully enriched cohort rather than assignment provenance.

Each ranked row returns its distinct Job count and Canonical Skill Prevalence derived from `processed_total`. The percentages are independent multi-label prevalence values and are not expected to sum to 100%.

Keep global top-N semantics for “Top Matched Canonical Skills”; do not allocate per-bucket quotas. The backend supplies the ranked rows and `dashboard_bucket`; the frontend may group them for scanning, but grouping must not change membership or rank and all returned rows must remain reachable. Cards initially show four rows and use a real button to expand/collapse overflow. Summary text reports the total returned canonical Skills and, when collapsed, the number currently visible. Dynamically returned non-empty buckets remain append-only after known preferred buckets.

The UI explains that unresolved Candidate Mentions, generic tags, and rejected mentions are excluded. Any Candidate backlog signal remains separate from the ranking. Candidate auto-classification is not added here.

Add a separate Candidate backlog summary derived from active `CurrentJobSkillMention` rows whose resolution is `candidate`. Count distinct referenced Candidate IDs and distinct Job IDs directly from active mentions. Also count the distinct referenced Candidates whose current `distinct_job_count` meets the runtime `skill_auto_create_distinct_job_threshold`; obtain that threshold through `AIRuntimeSettingsService` rather than copying a default. Do not use `CurrentSkillCandidate.resolved_skill_code IS NULL` as the unresolved predicate: generic/rejected processing clears active candidate mentions and metrics without necessarily setting a resolved Skill code. Do not sum per-Candidate `distinct_job_count`, because one Job may contribute to multiple Candidates. The summary links to the existing Classification view but never contributes rows or counts to the canonical leaderboard.

The parent response provides action-ready counts only. The child `07-28-dashboard-classification-actions` owns durable `job_taxonomy` / `skill` target routing and Dashboard navigation behavior.

## UI state and accessibility

Use semantic sections/lists with labelled counts. Give loading a status, errors an alert and retry button, and abort requests during cleanup. Ensure full breadcrumbs and hidden Skill rows are available by keyboard, pointer, touch, and assistive technology. Preserve the current responsive card layout.

Move refresh ownership to the Dashboard boundary so one manual Refresh action requests all operational sections together. Maintain data, loading/error state, and client-observed last-successful time per section. Successful sections commit independently; a failed section may retain its previous data only with an explicit stale/error state and unchanged last-successful time. The page reports overall refresh progress without claiming one atomic timestamp when section freshness differs. Do not add polling in this task. Section retry affordances call the same refresh coordinator for their own key rather than starting untracked duplicate requests.

## Compatibility and rollback

Search all consumers before removing legacy fallback schema fields. If no consumer exists, remove backend schema fields and stale fixtures atomically. If one is found, keep a separate documented compatibility response rather than carrying always-empty fields in the dashboard contract.

Changes are additive or local except the response cleanup. Roll back response cleanup independently if an external consumer is discovered; population filtering, deterministic ordering, copy, expansion, and tests remain safe.

Expose stable canonical codes on concrete taxonomy and Skill rows for the child drill-down task, but keep navigation and JobBrowser route seeding outside this parent implementation.
