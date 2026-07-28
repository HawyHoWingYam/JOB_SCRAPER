# Dashboard taxonomy and skills audit

## Current data flow

- `Dashboard` fetches `/api/stats/overview`, then renders `SkillChart` and passes `total_jobs` to `CategoryChart` (`frontend/src/components/Dashboard.jsx:15-51`, `:224-230`).
- `CategoryChart` independently fetches `/api/stats/categories/dashboard` (`frontend/src/components/charts/CategoryChart.jsx:35-51`). The backend joins Jobs to their one current Job Taxonomy assignment and active hierarchy, filters `Job.is_deleted = false`, orders by count and labels, returns six rows, and rolls the rest into Other (`backend/app/api/stats.py:75-125`, `:216-256`).
- `SkillChart` independently requests the global top 30 `/api/stats/skills` rows (`frontend/src/components/charts/SkillChart.jsx:80-98`). The backend reads current Skill assignments, joins active canonical nodes, counts distinct jobs by English display label, globally limits the rows, then assigns presentation buckets (`backend/app/api/stats.py:27-68`, `:141-200`).
- A Skill assignment exists only for an AI-extracted term that exactly resolves to an active canonical code. Unknown terms remain Candidate Mentions and do not enter the aggregate (`backend/app/job_intelligence/current_taxonomies/enrichment.py:275-405`).

## Confirmed findings

### P1 — Skill summary overstates what is shown

`visibleGroupedSkillCount` sums every grouped API row, but each group renders only the first four and replaces the rest with inert `+N more` text (`frontend/src/components/charts/SkillChart.jsx:133-174`). The existing test explicitly expects the full grouped count despite overflow (`frontend/src/components/charts/SkillChart.test.jsx:29-76`). With the live top-30 response observed on 2026-07-27, the badge reports 30 while only 27 names render.

### P1 — Aggregate population contracts differ

Job Taxonomy and overview filter `Job.is_deleted = false` (`backend/app/api/stats.py:75-125`; `backend/app/services/enrichment_run_service.py:326-379`). Skills never join `jobs`, so the query cannot apply the same filter (`backend/app/api/stats.py:141-186`). No deleted Skill assignments existed in the inspected local database, so this is a confirmed contract defect with latent rather than current numerical impact.

Neither aggregate filters the Python-only `Job.is_expired` projection (`backend/app/models/job.py:221-244`). The existing overview is explicitly “Total Jobs Acquired”, so the least surprising default is all non-deleted acquired jobs; an active-listing view needs a separate explicit filter and a queryable expiry contract.

### P1 — “Requested Skills” hides canonical coverage bias

The chart counts current resolved canonical assignments, not every requested term. Candidate, generic, and rejected mentions are omitted by design (`backend/app/job_intelligence/current_taxonomies/enrichment.py:303-397`; `.trellis/spec/backend/ordinary-current-taxonomies.md`, Contracts). The title and empty copy do not make that boundary clear (`frontend/src/components/charts/SkillChart.jsx:136-149`).

The global SQL `LIMIT` occurs before client bucketing, and the client then truncates every bucket to four (`backend/app/api/stats.py:182-186`; `frontend/src/components/charts/SkillChart.jsx:152-174`). This can make bucket representation uneven while hiding globally top-ranked returned rows.

### P2 — Ordering and contract residue

- Skills order only by count, so ties are nondeterministic; the client tie sort is also count-only (`backend/app/api/stats.py:186`; `frontend/src/components/charts/SkillChart.jsx:73-77`).
- `limit` has no FastAPI bounds (`backend/app/api/stats.py:141-146`).
- The Job Taxonomy response still carries `fallback_total` and `fallback_buckets`, but the current backend hardcodes them to zero/empty and the frontend deliberately ignores them (`backend/app/api/stats.py:233-255`; `backend/app/schemas/stats.py:19-39`; `frontend/src/components/charts/CategoryChart.test.jsx:26-130`). This conflicts with the ordinary-current-taxonomy no-fallback product contract.
- Skills group by English display labels rather than stable codes, which can merge distinct codes with the same label (`backend/app/api/stats.py:151-186`).

### P2 — Accessibility and resilience

- Full taxonomy breadcrumbs are only in a hover `title` while visible labels are truncated (`frontend/src/components/charts/CategoryChart.jsx:124-145`).
- Visual bars and Skill rows have no explicit list/chart/value semantics; loading and errors have no live status/alert, retry, or request cancellation (`frontend/src/components/charts/CategoryChart.jsx:40-79`, `:124-185`; `frontend/src/components/charts/SkillChart.jsx:85-130`, `:151-179`).
- Empty states exist, and dynamic unknown Skill buckets are correctly preserved. Keep the regression in `frontend/src/components/charts/SkillChart.test.jsx:107-139` and the contract in `.trellis/spec/frontend/component-guidelines.md`.

### P2 — Dashboard partial failures and duplicated presentation policy

- The main Dashboard deliberately tolerates a failed `/api/ai/overview` request by substituting nullable failure telemetry, but it does so silently and does not distinguish a transport failure from unavailable fields (`frontend/src/components/Dashboard.jsx:14-43`). The derived cards handle that nullable failure count, while the acquired and pending cards still call `toLocaleString()` on raw response fields and can throw on a malformed-but-successful stats payload (`frontend/src/components/Dashboard.jsx:176-203`).
- Skill presentation bucketing is authoritative in the backend response, but the frontend retains a fallback copy of part of the same keyword policy (`backend/app/api/stats.py:27-68`; `frontend/src/components/charts/SkillChart.jsx:19-56`). The copies have already drifted: the frontend omits the backend's `jenkins`, `github actions`, `unix`, and `vmware` tokens. Either make `dashboard_bucket` required for this endpoint or explicitly test a complete compatibility fallback; do not maintain two unverified policy implementations.
- The page mixes an internal operational “Command Center” with corpus-distribution charts. Before changing metric population or adding filters, resolve whether these charts are operational data-quality indicators, labor-market analytics, or a deliberately labelled secondary snapshot; each purpose implies a different denominator and freshness contract (`frontend/src/components/Dashboard.jsx:46-55`, `:83-95`, `:223-231`).

## Test gaps

- No focused backend tests reference `get_skill_stats` or `get_dashboard_category_stats`.
- `Dashboard.test.jsx` mocks both charts, so it does not verify their contracts (`frontend/src/components/Dashboard.test.jsx:6-62`).
- Component tests cover ordinary rendering and dynamic buckets but not deleted-job semantics, deterministic ties, API limits, loading/error/empty/retry, expansion, accessibility, responsive behavior, or request cleanup.

## Runtime observations

Read-only calls to the locally running API on 2026-07-27 returned 12,882 non-deleted acquired jobs, 2,814 current accepted Job Taxonomy assignments, and 30 globally limited Skill rows. The current grouping rendered 27 Skill names while its badge counted 30. A read-only database query found zero deleted jobs with current Skill assignments at that instant; implementation still needs the filter and regression test to preserve the shared contract.

These values are diagnostic snapshots, not acceptance thresholds and must not be copied into public product contracts.

## Skill coverage denominator

- `Job.ai_enriched_at` is the only persisted per-Job enrichment-completion marker (`backend/app/models/job.py:76-78`). The enrichment transaction sets it before replacing Skill projections and commits both together; failures roll the transaction back (`backend/app/job_intelligence/enrichment_service.py:80-138`). A successful extraction with no matched Skills is therefore distinguishable from a Job that has not completed enrichment.
- Skill projection supersedes previous active mentions, records matched/candidate/generic/rejected outcomes, and replaces the Job's current Skill assignments; an empty matched list validly leaves no assignments (`backend/app/job_intelligence/current_taxonomies/enrichment.py:275-405`; `backend/app/job_intelligence/current_taxonomies/store.py:197-221`). Candidate resolution may later reproject current assignments without another AI run (`backend/app/job_intelligence/classification_domain_adapters.py:402-441`).
- Canonical Skill match coverage can therefore use successfully AI-enriched, non-deleted Jobs as its processed denominator and distinct Jobs with at least one current canonical Skill assignment as its numerator. Using all acquired Jobs as the only denominator would conflate the AI backlog with completed extractions that produced no canonical match. The existing Dashboard already reports AI-eligibility/enrichment coverage separately.

## Jobs drill-down capability

- Both chart components are display-only. Category rows expose only label paths and Skill rows expose only names/categories; neither response includes the stable taxonomy or Skill code needed for an unambiguous filter (`frontend/src/components/charts/CategoryChart.jsx:124-146`; `frontend/src/components/charts/SkillChart.jsx:137-178`; `backend/app/api/stats.py:141-200`, `:217-247`). “Other” is an aggregate over multiple taxonomy paths and cannot represent one filter.
- The Jobs search backend already accepts canonical Domain/Category/Subcategory IDs and Skill/Technology/Skill Category IDs in structured filters (`backend/app/schemas/job_search.py:54-77`; `backend/app/api/jobs.py:363-429`). The missing boundary is Dashboard payload identity plus navigation state.
- Current application routing supports only top-level hashes such as `#jobs`; `JobBrowser` receives no route filter and constructs its search scope from local state (`frontend/src/appRoute.js:1-24`; `frontend/src/App.jsx:69-70`; `frontend/src/components/JobBrowser.jsx:177-203`). Click-through therefore requires a deliberate stable-code response and deep-link/state contract, not a presentation-only handler.
