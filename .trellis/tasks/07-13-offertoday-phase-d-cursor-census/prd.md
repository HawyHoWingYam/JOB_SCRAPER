# OfferToday practical IT production crawl

## Supersession Decision

On 2026-07-14 the user replaced the Phase D-H census/research route with a
practical production objective. The old supplemental successor, repeated
census, stable denominator, canary, soak, and candidate-gated adoption work is
cancelled and frozen. Existing research source, tests, schemas, strict
verifiers, specifications, and runtime artifacts remain available for
historical replay; this task no longer expands them.

The active authoritative specification is:

- `docs/specs/2026-07-14-offertoday-practical-it-production-crawler-spec.md`

The implementation plan is:

- `docs/specs/2026-07-14-offertoday-practical-it-production-crawler-implementation-plan.md`

## Goal

Make the daily OfferToday crawler collect the practical IT result cohort with
the response-derived cursor, then fetch detail only for new and incomplete or
failed canonical IDs.

## Requirements

1. Use the search endpoint, omitted `rcdType`, page size 10, and the four-field
   response cursor for every production IT category/keyword/hybrid condition.
2. End naturally after two cursor-continuous empty `resultList` pages.
3. Observe but never stage/detail `suppleRcdList` rows; supplemental identity
   issues are counted and excluded, not treated as run blockers.
4. Remove the 5,000-ID cap; keep 100 logical pages per condition as a safety
   cap.
5. Retain page-cap prefixes, continue later conditions, and complete the crawl
   with `listing_partial=true`.
6. Hard-stop auth/WAF/IP, cursor/endpoint/page, identity, gap, and persistence
   errors; never convert them into partial success.
7. Classify each validated page in bulk with no per-ID existence queries.
8. Skip complete published jobs and recorded code-2520 terminal IDs.
9. Create one current-crawl pending target for every new or repair ID.
10. Start detail only after every listing condition is natural or allowed
    partial.
11. Add exact partial, skipped, target, and detail outcome metrics.
12. Keep the existing research source, tests, schemas, strict verifier, and
    runtime artifacts available for historical replay; stop adding new
    production dependencies or research phases after extracting the production
    staging sink.

## Acceptance

The acceptance criteria and test matrix in the authoritative 2026-07-14 spec
apply verbatim. Deterministic focused/full backend verification replaces the old
live census/canary/soak gates.

## Boundaries

- No frontend, Compose, or detail API change.
- No database migration is planned; the user permits one only if implementation
  proves the existing staging JSON/status model insufficient.
- No live request is authorized by this planning artifact.
- Preserve unrelated dirty-worktree changes.
- Historical research code and artifacts are explicitly preserved; only the
  production import boundary and stale-reference audit are in scope.
