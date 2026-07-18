# Improve Task Control Board UI

## Goal

Make the Task Control Board easier and safer for an operator to understand and act on: distinguish recurring automation from one-off recovery runs, expose the most important runtime state, make destructive or high-impact actions predictable, and model source-specific crawl taxonomy without flattening or silently conflating different sources.

## Background and confirmed facts

- The current page is rendered by `ScheduleManager` and presents two top-level actions, `New Automation` and `Direct Override`, alongside a source selector (`frontend/src/components/scraper/ScheduleManager.jsx:1053-1095`).
- The page currently explains the two workstreams in two informational cards, then may show scheduler ownership/heartbeat, runtime warnings, errors, progress, and forms (`frontend/src/components/scraper/ScheduleManager.jsx:1109-1209`).
- `Direct Override` expands an inline configuration sequence with crawl phase, crawl mode, target sectors, volume, optional advanced listing-batch scope, backlog metrics, readiness messaging, and a start action (`frontend/src/components/scraper/ScheduleManager.jsx:1211-1457`).
- `New Automation` expands an inline form for task name, frequency, crawl phase/mode, volume, sectors, and create/cancel actions (`frontend/src/components/scraper/ScheduleForm.jsx:142-282`).
- Existing scheduled tasks are shown as cards with active/paused state, source, frequency, sectors, phase/mode, last/next run, latest outcome, Run Now, Logs, pause/resume, and delete actions (`frontend/src/components/scraper/ScheduleList.jsx:231-359`).
- The current visual system is a dark glass/cyber style with two-column launchpad cards and stacked panels (`frontend/src/components/scraper/Scheduler.css:1-155`).
- The current category API is source-aware but exposes a common flat payload (`id`, `name`, `slug`, `source_site`) and drops hierarchy/mapping metadata in `SourceCategoryRegistry` (`backend/app/services/source_category_registry.py:75-163`).
- JobsDB currently exposes 25 source-native top-level categories, including `Information & Communication Technology` (`backend/app/scraper/categories.py:18-45`).
- CTgoodjobs uses source-qualified string IDs and source-native labels such as `Information Technology`; its richer registry model already contains child counts and canonical-domain mapping metadata, but the shared category API omits those fields (`backend/app/scraper/ctgoodjobs/category_registry.py:34-80`, `backend/app/services/source_category_registry.py:135-143`).
- OfferToday has a validated two-level source taxonomy with 31 roots and 431 distinct query leaves, but the shared category API currently returns only the 31 roots (`backend/app/scraper/offertoday/category_registry.py:52-89`, `backend/app/scraper/offertoday/category_registry.py:107-168`, `backend/app/scraper/offertoday/category_registry.py:203-215`).
- Existing request schemas type `category_ids` as a flat list of strict integers or strings. Schedules persist that list in a JSON column; crawl jobs persist it inside an unversioned JSON `request_payload` (`backend/app/services/crawl_request_validation.py:7-20`, `backend/app/models/schedule.py:38-42`, `backend/app/models/crawl_job.py:31-42`).
- `source_site` currently provides the namespace used to validate primitive category IDs, but it is stored separately rather than being encoded into a stable Source Classification identity (`backend/app/services/crawl_request_validation.py:61-87`).
- Existing frontend forms, summaries, cards, and history assume a flat `{id, name}` catalog plus primitive `category_ids`; an enriched/tree contract therefore requires explicit compatibility adapters rather than an in-place response-shape swap (`frontend/src/components/scraper/ScheduleForm.jsx:36-45`, `frontend/src/components/scraper/ScheduleList.jsx:93-112`, `frontend/src/components/scraper/ScheduleHistory.jsx:183-205`).
- Source execution semantics differ: OfferToday parent selection may expand to a whole family and same-code aliases are not independent leaves; CTgoodjobs' dynamic registry is richer than the static registry currently used by its spider; JobsDB's Scrapy path currently carries selected category IDs as metadata without visibly placing them in the upstream API request (`backend/app/sources/offertoday/search_space.py:223-244`, `backend/scrapy_project/job_scraper_spiders/spiders/ctgoodjobs.py:67-100`, `backend/scrapy_project/job_scraper_spiders/spiders/jobsdb.py:66-78`).
- A destructive control-plane reset is technically separable from collected-job deletion: schedules own schedule executions; crawl jobs own events, executions, and staged listings; crawl runs and some execution references use `SET NULL`; pending outbox events have no foreign key and require explicit cleanup (`backend/app/models/schedule.py:39-60`, `backend/app/models/crawl_job.py:31-93`, `backend/app/models/crawl_run.py:24-52`, `backend/app/models/event_outbox.py:9-25`).
- Collected Jobs are a broader data boundary: they preserve source classification snapshots and canonical taxonomy references and own dependent enrichment/search data such as skills and embeddings (`backend/app/models/job.py:38-75`, `backend/app/models/job_skill.py:13-14`).

## Requirements

To be refined through the design interview. The final scope may introduce category schema and API changes with an explicit compatibility plan, while preserving scheduler/crawler execution semantics unless a deliberate product decision changes them.

### Confirmed product decisions

- The board is primarily an operations control room: active, blocked, failed, and upcoming work should be easier to see than configuration forms.
- `New Automation` and `Direct Override` remain available as secondary actions in the page header rather than defining the whole page hierarchy.
- Rename `Direct Override` to `One-off Run`; explain that it starts a crawl immediately without changing recurring automations. Use `Backlog Recovery` as a contextual mode/use case for detail runs rather than as the global action name.
- Scope is a substantial UI/UX redesign of the `New Automation` and `One-off Run` flows: redesign information architecture, field grouping, interaction flow, copy, status/error/empty/blocked states, responsive behavior, and accessibility while preserving backend APIs, task state models, and crawler behavior.
- The current frontend already has enough data for a control-room summary without a new endpoint: schedules include latest execution and next-run fields; progress exposes active, attention, backlog, and terminal snapshots; runtime capabilities expose scheduler and worker health (`ScheduleManager.jsx:760-791`, `ScrapeProgressPanel.jsx:220-329`, `backend/app/services/crawl_task_snapshot_service.py:1173-1242`).
- Keep the board scoped to one source at a time; represent the source context as a more visible tab/segmented control while preserving source-specific defaults and validation.
- The redesign may replace the current inline form layout and field order; it is not limited to styling or converting the existing forms into a drawer.
- Both flows should be intent-first and progressively disclose technical configuration in the sequence `intent → scope → execution settings → final confirmation`; advanced options remain available for experienced operators.
- Use distinct intent copy for the two workflows: `New Automation` offers `Discover listings` and `Enrich job details`; `One-off Run` offers `Discover listings now` and `Recover detail backlog`.
- Redesign all four combinations as first-class flows: `New Automation → Job ID`, `New Automation → Job Detail`, `One-off Run → Job ID`, and `One-off Run → Job Detail`.
- The provided screenshots confirm that the current forms are long desktop-first layouts with duplicated technical fields and a wide 8-column sector checkbox grid; the redesign must address this structure rather than only changing labels or colors.
- Summary copy must match the selected intent and phase: a Job ID run must not be described as backlog recovery.
- Use a shared wizard shell with intent-specific step content rather than four entirely separate form implementations.
- Use a four-step wizard with visible progress, back/continue navigation, a persistent live summary, and a final review/confirmation step.
- Preserve the dark product theme but move to a calmer operations-console visual system: reduce decorative glass/glow and all-caps micro-labels, strengthen typography and spacing hierarchy, and reserve accent colors for state, risk, and primary actions.
- Rework recurring frequency into a friendly schedule builder with a natural-language summary; retain custom cron as an advanced option mapped to the existing cron contract.
- Require a final review step before creating a recurring automation or starting a one-off run; show intent, source, scope, volume, execution settings, readiness, and relevant risks in the confirmation summary.
- If an active manual detail run conflicts with a new recovery request, block the new run, show the active run context and progress, and provide a path to cancel the current run; after cancellation succeeds, refresh readiness and allow the new run to be configured/launched.
- Reuse the existing crawl-job cancellation capability; expose it from the conflict state with explicit inline confirmation and preserve completed records while leaving remaining work in backlog.
- Optimize this redesign for desktop first; mobile-specific full-screen wizard behavior and sticky mobile actions are explicitly out of scope for this iteration.
- Treat crawl mode as a recommended execution setting: keep the default mode out of the primary decision path, expose alternatives under advanced options, and show headed-worker readiness and dependency guidance whenever `Headed` is selected.
- Make target scope explicit: offer `All available sectors` versus `Choose specific sectors`, use searchable multi-select with select/clear-all and counts, and distinguish global backlog, sector-scoped backlog, and specific listing-batch scope in the detail recovery flow and final summary.
- For recurring discovery automations, JobsDB and CTgoodjobs require an explicit choice between all source categories and selected source categories; OfferToday may default to its explicit `All IT categories` scope, which must remain visible in review.
- Expand the redesign through the data boundary: define a source-taxonomy schema, preserve source-native IDs/names/hierarchy, expose source-specific depth and capabilities to the frontend, and carry unambiguous scope selections through schedule and one-off-run payloads.
- Source-native taxonomy is the execution authority for Crawl Scope. Canonical Job Domains may group or explain classifications but must not silently expand into source queries; future cross-source Automations require explicit per-source scopes (`docs/adr/0001-source-native-taxonomies-define-crawl-scope.md`).
- Crawl Scope supports explicit Exact Scope and Subtree Scope rules. Subtree rules resolve against the current Source Catalog Revision and include future descendants; referenced nodes that disappear or become non-executable require operator review (`docs/adr/0003-model-crawl-scope-as-exact-or-subtree-rules.md`).
- Correct source catalogs, executable scope semantics, and crawler query behavior take priority over retaining legacy schedule/run data shaped by ambiguous flat `category_ids`; a clean or destructive migration is acceptable once the exact discard boundary is agreed.
- Taxonomy cutover will reset Crawl Control Data—Automations, schedule executions, crawl jobs/events/executions, listing staging/backlog, crawl run history, and pending crawl outbox events—while preserving the Published Job Corpus, Companies, canonical taxonomy, and attached enrichment (`docs/adr/0002-reset-crawl-control-data-during-taxonomy-cutover.md`).
- Source execution correctness is part of this program and is a prerequisite to schema and UI work: JobsDB selections must demonstrably constrain upstream requests, CTgoodjobs must expose and execute one authoritative catalog, and OfferToday parent/leaf/alias semantics must be contractual and tested.
- CTgoodjobs currently advertises and executes headed-only crawl jobs; legacy headless requests are upgraded to headed, even though separate HTTP listing/detail fetchers and registry discovery can operate without a visible browser (`backend/app/crawl_modes.py:6-19`, `backend/app/scraper/ctgoodjobs/list_scraper.py:28-59`, `backend/app/scraper/ctgoodjobs/detail_scraper.py:19-49`).
- CTgoodjobs catalog authority is independent from crawl mode: the API/validation can use a live registry while headed runtime resolution uses a static snapshot, so a live classification can pass validation and still fail at execution (`backend/app/services/source_category_registry.py:100-149`, `backend/scripts/ctgoodjobs_standalone_crawl.py:120-136`).
- CTgoodjobs remains headed-only for this program. Headless-first execution and automatic headed escalation are out of scope; manual-action handling continues on the existing headed runtime.
- Live source discovery creates a Catalog Candidate. UI, validation, and crawler execution use only one validated, published Source Catalog Revision and switch revisions together (`docs/adr/0004-execute-only-against-published-source-catalog-revisions.md`).
- Every first-version Source Catalog Revision requires explicit operator publication after automated validation and impact review; no catalog change auto-publishes.
- Catalog candidate discovery, diff, validation, impact review, and publication live on a dedicated `Source Catalogs` governance page. The Task Control Board displays revision health and links there but cannot publish revisions inline.

### Initial design hypotheses to validate

- The board should prioritize operational awareness and safe action over merely exposing configuration fields.
- `New Automation` and `Direct Override` should be presented as different intent paths, with language that explains when to use each.
- The direct-run flow should make scope, expected impact, readiness/blockers, and the final action obvious before execution.
- Scheduled automations should expose the next meaningful operator action without forcing the user to parse every metric in a dense card.
- The layout must remain usable at narrow widths and retain accessible labels, status semantics, and confirmation for destructive actions.

## Acceptance Criteria

- [ ] Final product decisions are recorded as testable UI requirements.
- [ ] The proposed information hierarchy clearly separates recurring automations, one-off runs, active progress, and runtime health.
- [ ] The final design defines the behavior and copy for `New Automation`, `Direct Override`, `Run Now`, pause/resume, Logs, and delete.
- [ ] The final design defines source taxonomy terminology, hierarchy semantics, stable identity, API payloads, compatibility behavior, and UI rendering for sources with different category depth.
- [ ] Crawl requests and saved automations preserve exact source-qualified selections without relying on display-name equality across sources.
- [ ] The design identifies responsive, accessibility, loading, empty, error, and blocked-readiness states.
- [ ] Before implementation, complex-task planning artifacts (`design.md` and `implement.md`) describe boundaries, trade-offs, and validation.

## Child task map

1. `source-catalog-runtime-correctness` — establish authoritative source catalogs and prove selected Source Classifications constrain crawler queries.
2. `source-catalog-governance-ui` — add the dedicated candidate diff/validation/impact/publish page; depends on child 1's governance contract.
3. `versioned-crawl-scope` — introduce the versioned Crawl Scope contract and perform the approved Crawl Control Data cutover; depends on child 1's executable catalog contracts.
4. `task-control-board-wizard-ui` — implement the operations board and four shared-wizard flows against the new contract, including revision-health links; depends on children 1-3.

The parent owns the source requirement set, cross-child terminology/ADRs, dependency order, and final integration review. Each child owns independently testable implementation and validation.

The existing `07-18-offertoday-taxonomy-mapping` task remains separate: it governs post-collection source-to-canonical mapping and AI enrichment exclusions. This parent governs pre-dispatch source-native catalogs, Crawl Scope, crawler execution, and control-board UX; neither task may make the Canonical Job Domain authoritative for crawling.


## Scope guardrails

- This phase is design and requirements discovery only; do not edit frontend implementation until planning is approved and the task is started.
- Backend/schema work is now in scope, but crawler behavior changes and automatic cross-source category inference are not assumed until explicitly decided.
- Do not mix this task with the existing bootstrap task or unrelated uncommitted changes.
