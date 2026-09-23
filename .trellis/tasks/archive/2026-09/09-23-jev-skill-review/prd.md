# Evidence-backed Skill Candidate review

## Goal

Evidence-backed Skill Candidate review for the first Jev Skill-only delivery.

Parent: research-jev-use-cases / GitHub #62. This rollout did not proceed because
its Phase 1B release gate was inconclusive. The specification is retained as a
future reference, not an implemented product contract. No user labeling
assignment was introduced, and current deterministic/operator-confirmed review
remains unchanged.

## Requirements

- Dependency: Blocked by jev-settings-budget AND a jev-skill-evaluation report supporting a limited recommendation rollout. Parent-child nesting does not replace these blockers.
- Extend the existing Skill Candidate review page with validated source passages, evidence findings, existing-Skill recommendations and unresolved/unavailable/over-budget states.
- Keep local name/alias similarity distinguishable from Jev decision scores; do not label scores as accuracy. Existing queue/display controls and new settings remain editable through Settings.
- Use precomputed bounded-run results; candidate GET and page navigation trigger no paid work. Preserve current review when Jev is disabled or unavailable.
- Require explicit operator actions for matching, creating, generic disposition, rejection and proposed corrections. Validate current evidence and taxonomy before applying stale-sensitive suggestions.
- Observe ordinary-use accept/correct outcomes and available handling-time signals without a separate labeling exercise. Report unmeasured time savings honestly.

## Acceptance Criteria

- [ ] Operator can inspect evidence and explicitly apply or reject suggestions through existing review actions.
- [ ] Stale evidence/taxonomy, absent source passages, errors and exhausted budget preserve existing manual review without automatic writes.
- [ ] Suggestions and settings work end-to-end; no automatic new Skill or candidate resolution is introduced.
- [ ] Rollback disables Jev suggestions while retaining original records and existing review functionality.

## Dependencies

Blocked by jev-settings-budget AND a jev-skill-evaluation report supporting a limited recommendation rollout. Parent-child nesting does not replace these blockers.

## Closure decision

The settings/budget dependency completed, but Phase 1B did not produce a report
supporting limited rollout because independent English and Traditional-Chinese
real-case references were unavailable. No acceptance criterion above is claimed
as implemented. Revisit through a new authorized rollout task only after that
evidence prerequisite is met.

## Design references

Read parent `../09-23-research-jev-use-cases/design.md`, `prd.md`, `implement.md` and research evidence. This child remains planning; complete child-specific design and execution/check commands before its start.
