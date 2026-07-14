# OfferToday practical IT production crawl parent execution plan

1. Complete the active child using the 2026-07-14 implementation plan.
2. Run focused production OfferToday tests before the research isolation audit.
3. Remove production imports of research-only modules, but preserve the
   research modules, CLIs, tests, schemas, and artifacts for historical replay.
4. Run Ruff, compilation, the complete backend suite, reference checks, and
   `git diff --check`.
5. Audit the final diff for unintended database, frontend, Compose, detail API,
   or unrelated worktree changes.

There are no remaining Phase D-H live evidence gates.
