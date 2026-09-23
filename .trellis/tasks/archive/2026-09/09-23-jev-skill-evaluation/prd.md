# Automated Skill evidence and recommendation evaluation

## Goal

Automated Skill evidence and recommendation evaluation for the first Jev Skill-only delivery.

Parent: research-jev-use-cases / GitHub #62. Planning only. First scope is Skill evidence plus candidate recommendations, reliability first. No user labeling assignment. Actual changes remain operator-confirmed; preserve current deterministic resolution. Initial paid evaluation allowance is USD 10 total, not USD 10 per task or restart.

## Requirements

- Dependency: Blocked by jev-settings-budget: frozen settings, decision adapter and shared cumulative budget ledger. Offline fixture preparation can precede it.
- Create separate explicit-answer controlled fixtures and real Job/Skill evidence datasets with bilingual slices, grouped development/held-out splits and provenance. Do not assign manual labeling to the user.
- Evaluate Skill source support separately from candidate disposition/existing-path recommendations. Compare local matching and available existing LLM baselines against Jev.
- Obtain blinded independent reviewer judgments where configured and budget permits. Record uncertainty and model identity; never call model agreement human-validated accuracy.
- Freeze numeric gates and scoring policies before held-out evaluation. Include negation, preference, incidental context, missing candidates, reordered options, unavailable responses and abstentions.
- Use the Phase 1A shared USD 10 allowance, including baselines/reviewers/retries; report fixture correctness, real-case agreement, actionable coverage, errors, latency and spend. No production writes.

## Acceptance Criteria

- [x] Reproducible manifests keep grouped examples out of both development and held-out sets.
- [x] Report separates controlled-answer correctness from uncertain real-case references and includes unresolved cases in denominators.
- [x] Produce a proceed/defer report for a limited recommendation rollout; a budget-limited inconclusive result remains inconclusive.
- [x] No manual labeling requirement and no Skill/fact writes occur during evaluation.

## Dependencies

Phase 1A (`jev-settings-budget`) is complete and supplies frozen settings,
native decisions, bounded runs, and the cumulative allowance ledger.

## Frozen held-out gates

- Controlled evidence answered correctness >= 0.90.
- Controlled recommendation top-1 correctness >= 0.85.
- Technical failure rate <= 0.05.
- Actionable coverage across all eligible cases >= 0.60.
- Option-reordering stability >= 0.95.

These gates were declared before held-out execution. Missing denominators are
`not_evaluable`; unresolved and errors remain in denominators. Real-case model
agreement is not labelled accuracy.

## Design references

Read parent `../09-23-research-jev-use-cases/design.md`, `prd.md`, `implement.md` and research evidence. This child remains planning; complete child-specific design and execution/check commands before its start.
