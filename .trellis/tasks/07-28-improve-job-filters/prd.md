# Improve job filters frontend and backend

## Goal

Make the Jobs Filters workflow readable, predictable, and efficient on desktop,
while giving every visible structured filter one coherent frontend-to-backend
contract.

## Background

- The supplied screenshot shows long native multi-select values clipped inside
  a three-column grid. The affected controls are implemented in
  `frontend/src/components/FilterPanel.jsx:260` and laid out by
  `frontend/src/components/JobBrowser.css:243`.
- Governed IDs already cross the layered POST `/jobs/search` contract, and the
  backend already applies Source, Source Classification, Employment Type,
  taxonomy, industry, date, and experience filters
  (`frontend/src/components/JobBrowser.test.jsx:220`,
  `backend/app/schemas/job_search.py:54`, `backend/app/api/jobs.py:313`).
- Filter option sources are inconsistent: `/jobs/filters` derives Employment
  Type and Source Classification from retained Jobs and returns
  `industries=[]`, while separate current-taxonomy routes return complete Job
  Taxonomy and Company Industry trees (`backend/app/api/jobs.py:993`).
- Layered search already ANDs appended layers, but the visible trail can fall
  back to `Structured filters only`, omits supported filters, offers removal but
  no editing, and has no clear-all action
  (`frontend/src/components/JobBrowser.jsx:631`,
  `backend/app/api/jobs.py:456`).
- Search scope and pagination currently live only in React state, so refresh
  loses the search. Existing automated coverage does not exercise narrow-width
  layout, layer editing/restoration, contextual facets, or the complete
  date/experience contract.

## Requirements

### Filter interaction and layout

- Redesign only the currently visible filter set: Source, Source
  Classification, Employment Type, Canonical Job Taxonomy, Company Industry,
  explicit posted-date range, experience range, and Posting Window presets.
- Replace native multi-selects with collapsible inline selector cards. A closed
  card shows selected count and removable summaries; an open card provides
  search and checkbox selection.
- Use source-grouped paths for Source Classification, a flat checkbox list for
  Employment Type, and hierarchical browsing for Job Taxonomy and Company
  Industry. Keep date, experience, and Posting Window directly visible.
- Make hierarchical selectors parent-first. Major categories are visible before
  collapsed children. Selecting a parent includes all descendants, removes
  redundant selected descendants, and prevents covered descendants from being
  selected until the parent is cleared.
- Optimize for desktop: simple fields use at most two columns and complex
  selectors use the full row. Narrow widths collapse to one usable column; a
  separate mobile drawer is not required.

### Draft and layered-search workflow

- Filter edits are drafts and never request Jobs merely because a selector is
  opened, searched, or changed. Pending state and a discard action must be
  explicit.
- With no applied layers, `Search all jobs` applies the draft as the root
  search. With applied layers, users can either replace all layers with
  `Search all jobs` or append the draft with `Refine current results`.
- Show applied layers as a human-readable stack covering every visible filter.
  A user can inspect, edit in place, remove, or clear all layers. Editing saves
  back to the same position rather than appending.
- `Discard changes` exits draft/edit mode without a request. `Clear all layers`
  clears draft and applied scope, immediately loads unfiltered Jobs, and clears
  restoration state.
- Persist only normalized applied scope in the current tab's `sessionStorage`.
  Refresh restores and reruns it from page one. Closing the tab clears it;
  unapplied drafts, pagination, and the URL are not persisted.

### Backend facets and contracts

- A successful applied search returns Jobs and contextual facet data derived
  from the same validated scope. Draft edits leave displayed facet counts
  unchanged until a successful apply/reset.
- Each facet is calculated from the applied text and other filter dimensions
  while excluding that facet's own field(s) across all layers.
- Return complete active governed catalogs for Source, Employment Type,
  Canonical Job Taxonomy, and Company Industry with distinct available-Job
  counts. Parent counts include descendants without double-counting a Job.
- Keep zero-count governed nodes visible but disabled, except that an already
  selected zero-count value remains visible and removable.
- Source Classification is data-backed until a complete governed hierarchy
  exists: return only source-qualified paths represented by retained searchable
  Jobs, with distinct contextual Job counts.
- Preserve governed stable codes as authority, OR semantics within a filter
  field, AND semantics across fields/layers, the existing legacy adapters, and
  the rule that unspecified experience represents 0–1 years.

## Acceptance Criteria

- [ ] At the demonstrated width, labels, values, help, and actions neither
      overlap nor become unintelligibly clipped; desktop uses at most two
      columns and narrow layouts remain usable in one column.
- [ ] Complex selectors support local search, checkbox selection, removable
      summaries, parent-first browsing, and ancestor/descendant de-duplication.
- [ ] Pending drafts do not fetch Jobs; discard restores the prior state; replace,
      refine, edit, remove, and clear-all each issue the intended normalized
      scope and keep visible results synchronized.
- [ ] Applied layers have complete human-readable summaries and can be edited in
      place, removed individually, or cleared together.
- [ ] Refresh restores only applied layers in the same tab, starts at page one,
      and does not restore drafts or change the URL.
- [ ] Facet counts exclude their own dimension, respect every other applied
      layer/filter, count distinct Jobs, aggregate descendants correctly, and
      stay stable while a draft is pending.
- [ ] Complete active governed catalogs retain zero-count nodes as disabled;
      selected zero-count nodes remain removable; Source Classification remains
      limited to retained source-qualified paths.
- [ ] Existing GET/POST search consumers and current-taxonomy consumers remain
      compatible, and all visible filters retain explicit validated semantics.
- [ ] Frontend and backend automated tests cover the new selectors, state
      transitions, session restoration, layered scope operations, facet
      contracts, date/experience behavior, and compatibility paths.

## Out of Scope

- Adding Location, Region, District, Salary, Skills, or other currently hidden
  backend fields to this panel.
- Making layered searches shareable by URL or persisting them after the current
  browser tab closes.
- Introducing a mobile drawer, server-side selector search, a taxonomy release
  workflow, or a complete Source Classification registry hierarchy.
- Changing Posting Window into a backend enum; it remains a frontend preset
  serialized as explicit posted-date bounds.

## Constraints and Related Work

- Source Classification labels are display evidence; source-qualified IDs are
  authoritative. Employment Type uses the governed seven-code registry.
- Current taxonomy stable codes and current-state tables remain authoritative;
  no revision, release, or legacy industry fallback may be introduced.
- The planning task `07-28-dashboard-chart-jobs-drilldown` may add explicit Jobs
  route seeds. If present, a valid explicit route seed takes precedence over
  session restoration, and hidden route-seeded governed fields must survive
  scope normalization even though this task does not add them to FilterPanel.
- Implementation begins only after this PRD, `design.md`, and `implement.md`
  receive user approval.
