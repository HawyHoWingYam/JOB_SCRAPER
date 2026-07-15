# OfferToday practical IT production crawl parent

## Decision

The 2026-07-13 completeness/stability research program is superseded by the
user's 2026-07-14 practical production decision. Phase D-H and their production
gates are cancelled and the historical research implementation remains
available for replay without further production expansion.

## Active Child

- `07-13-offertoday-phase-d-cursor-census` now owns the practical IT production
  crawler implementation and research isolation despite its historical task ID.

## Authoritative Documents

- `docs/specs/2026-07-14-offertoday-practical-it-production-crawler-spec.md`
- `docs/specs/2026-07-14-offertoday-practical-it-production-crawler-implementation-plan.md`

## Parent Completion

The parent completes when the active child passes its deterministic production
quality gate and the historical research implementation is isolated without
damaging replay capability, shared production primitives, or unrelated
worktree changes.
