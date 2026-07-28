# Add dashboard chart Jobs drill-down

## Goal

Let an operator move from a concrete Canonical Job Taxonomy or Matched Canonical Skill signal on the Operations Dashboard to the exact underlying Jobs without manually rebuilding filters.

## Requirements

- Make each concrete Job Subcategory and Skill row an accessible drill-down action.
- Carry stable canonical codes across the Dashboard stats response and navigation boundary; labels and presentation buckets are not identities.
- Open the Jobs browser with the equivalent canonical Subcategory or Skill structured filter already applied.
- Give the filtered Jobs view a durable, refresh-safe and shareable route representation rather than transient component-only state.
- Preserve keyboard, pointer, touch, and assistive-technology operation, including a clear accessible action name.
- Keep the aggregated `Other` control non-navigational because it does not identify one filter. When the parent card expands it into concrete canonical paths, those concrete rows may drill down by stable code. Do not approximate `Other` with label matching.
- Preserve the ordinary Jobs search contract and existing manual FilterPanel behavior.

## Acceptance Criteria

- [ ] A concrete taxonomy row opens Jobs filtered by its exact canonical Subcategory code.
- [ ] A concrete Skill row opens Jobs filtered by its exact canonical Skill code.
- [ ] Refreshing or sharing the resulting route reconstructs the same filter.
- [ ] Duplicate or changed display labels cannot redirect the filter to a different canonical node.
- [ ] Drill-down actions are keyboard reachable and expose their destination and count to assistive technology.
- [ ] `Other` remains visibly aggregated but is not exposed as a misleading single-filter action.
- [ ] Concrete taxonomy rows revealed by expanding `Other` use the same exact-code drill-down contract as Top 6 rows.
- [ ] Existing direct `#jobs` navigation and manually authored Jobs filters continue to work.
- [ ] Focused backend response-contract, route parsing/serialization, Dashboard interaction, and JobBrowser filter-seeding tests pass.

## Notes

- Depends on the parent taxonomy/Skill stats contract exposing stable codes.
- Aggregated `Other` navigation, unassigned-Job drill-down, multi-row selection, and arbitrary Dashboard query building are out of scope.
