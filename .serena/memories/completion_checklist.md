# Completion Checklist
- Run targeted backend tests for changed Python behavior with `pytest ... -v`.
- For frontend changes, at minimum run `npm --prefix frontend run lint` and `npm --prefix frontend run build`.
- If the task changes UI behavior without frontend test coverage, do a manual browser verification of the changed interaction.
- Avoid reverting unrelated user changes; this repo may contain a dirty worktree.
- When documenting design or implementation work, plans may live in `docs/plans/` by convention, but the user may explicitly request `ref/plan/` instead.
