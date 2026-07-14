# OfferToday practical IT production crawl implementation plan

## Authorization Boundary

This artifact authorizes deterministic production implementation and isolation
of the historical research stack. It does not authorize deletion or rewriting
of research source/tests/schemas/artifacts, and it does not authorize an
OfferToday live request. Preserve unrelated worktree changes.

## Ordered Work

- [x] Review the proposed lightweight route against the live checkout.
- [x] Replace the Phase D-H task documents with the approved production scope.
- [x] Publish the authoritative production specification and implementation
      plan.
- [x] Add failing production cursor/partial/bulk-classification tests.
- [x] Switch all production IT conditions to search, omitted `rcdType`, page
      size 10, and condition-local response cursor.
- [x] Add retain-and-continue page-cap behavior and immediate validated-page
      staging.
- [x] Move the production staging sink out of the research-named module.
- [x] Implement bulk complete/terminal/new/repair classification without N+1.
- [x] Freeze detail targets only after all listing conditions finish naturally
      or partially.
- [x] Add partial/skipped/new/repair/detail metrics and exact status handling.
- [x] Run focused production tests.
- [x] Verify production import isolation and stale references while preserving
      research code/tests/CLIs/artifacts for historical replay.
- [x] Run Ruff, compilation, complete backend tests, reference audit, and
      `git diff --check`.

## Detailed Plan

Follow
`docs/specs/2026-07-14-offertoday-practical-it-production-crawler-implementation-plan.md`
Tasks 1-9 in order. The research isolation audit runs after the production
staging sink is moved and focused production tests pass; it must not mutate the
historical replay stack.

## Completion Gate

Completion requires all eight conditions in the implementation plan's
Completion Definition. No Phase D census, supplemental successor, canary, soak,
or live research artifact is required.

## Verification Record

- Focused production suite: `438 passed`.
- Cross-production/research compatibility suite: `335 passed`.
- Complete backend suite: `1441 passed`, with 63 existing deprecation warnings.
- Ruff and `py_compile`: passed for all touched production/compatibility Python.
- Production research-import audit, historical artifact presence/ignore audit,
  stale-deletion reference audit, and `git diff --check`: passed.
- No OfferToday live request was sent.
