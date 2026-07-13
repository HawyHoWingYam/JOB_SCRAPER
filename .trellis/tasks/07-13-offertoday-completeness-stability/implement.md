# OfferToday completeness and stability execution plan

## Ordered Children and Gates

1. Complete Phase A/B implementation-plan Tasks 1-8 in the active child; run deterministic verification before any live request.
2. Create and plan the Phase C child for Tasks 9-10 as deterministic no-live infrastructure under the user's explicit deferral of unresolved Phase B Issues #4 and #5; do not describe that deferral as Phase B acceptance.
3. Continue with separately scoped later children without treating Issues #4/#5 as sequencing blockers; each child must preserve unresolved-risk provenance and enforce its own live, write, and adoption review gates.
4. Create the production-adoption child only after three passing soak artifacts and an explicit adoption review.
5. Run a requirement-by-requirement integration audit across all children before archiving this parent.

## Cross-Child Validation

- Focused deterministic modules named in implementation-plan Section 7.1 plus every new phase-specific test module.
- `python -m pytest -q backend/tests`
- `git diff --check`
- Generic hash verification and strict replay for every artifact used as evidence.
- Production-default guards at Phase A/B and again before/after adoption.

## Review Gates

- No live request before deterministic Phase A/B review.
- A valid-but-rejected decision does not block later deterministic implementation when the user explicitly defers its issues; live work still requires the owning task's explicit review and authorization.
- No product writes in Phase B/C; no Job/Company publication in Phase D.
- No production-default change before Phase H and final adoption review.

## Risk and Rollback Points

- Stop at the first cursor-contract, auth, identity, gap, conservation, leak, or budget failure.
- Preserve rejected artifacts as evidence; never rewrite them to make a later gate pass.
- If browser context is lost, restart only the affected condition from page 1.
- If an edit overlaps unrelated dirty-worktree changes, isolate the required hunk or stop for user direction.
