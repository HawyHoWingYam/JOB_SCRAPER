# Fix SkillChart dashboard crash on unknown buckets

## Goal

Prevent the dashboard from going blank when the skills statistics API returns a
valid `dashboard_bucket` that is not yet listed in the frontend's fixed bucket
order.

The user impact is that the dashboard initially loads, then the React tree
crashes a few seconds later when the skills request completes.

## Requirements

- R1: `SkillChart` must render successfully for the current API response,
  including dynamic buckets such as `Product & Delivery`.
- R2: Unknown-but-valid dashboard buckets must not cause an exception or blank
  dashboard. They should remain visible after the established bucket order so
  newly introduced backend categories are not silently discarded.
- R3: Existing known-bucket ordering, skill sorting, per-bucket display limit,
  overflow count, empty state, and loading/error states must remain unchanged.
- R4: Add a regression test covering a skill whose `dashboard_bucket` is not in
  `SKILL_BUCKET_ORDER`.

## Confirmed Facts

- `frontend/src/components/charts/SkillChart.jsx:59-75` initializes a `Map`
  only with `SKILL_BUCKET_ORDER`, then calls `grouped.get(bucket).push(skill)`.
- `frontend/src/components/charts/SkillChart.jsx:20-24` returns a non-empty
  `dashboard_bucket` verbatim, so it bypasses the local category fallback.
- `backend/app/api/stats.py:41-78` intentionally returns most taxonomy
  categories verbatim; the local API currently returns `Product & Delivery`.
- The crash occurs when the async skills request completes and `loading` turns
  false, which explains the delayed black screen.

## Acceptance Criteria

- [x] A skills response containing `dashboard_bucket: "Product & Delivery"`
      renders the dashboard skill chart without throwing.
- [x] The unknown bucket and its skills appear after the predefined buckets.
- [x] The regression test passes, and existing `SkillChart` tests continue to
      pass.
- [x] No backend contract or unrelated dashboard behavior is changed.

## Out of Scope

- Adding a React error boundary as the primary fix.
- Redesigning the skill taxonomy or changing backend bucket generation.
- Expanding the work to unrelated dashboard charts.

## Implementation Plan

1. Update `groupSkills` to register unseen non-empty buckets while preserving
   the predefined order and appending dynamic buckets afterward.
2. Add a focused `SkillChart` regression test for `Product & Delivery`.
3. Run the focused frontend test and the relevant frontend quality checks.

## Notes

- Keep `prd.md` focused on requirements, constraints, and acceptance criteria.
- Lightweight tasks can remain PRD-only.
- For complex tasks, add `design.md` for technical design and `implement.md` for execution planning before `task.py start`.
