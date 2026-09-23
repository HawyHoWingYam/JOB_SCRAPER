# UI settings and budgeted decision runs

## Goal

UI settings and budgeted decision runs for the first Jev Skill-only delivery.

Parent: research-jev-use-cases / GitHub #62. Planning only. First scope is Skill evidence plus candidate recommendations, reliability first. No user labeling assignment. Actual changes remain operator-confirmed; preserve current deterministic resolution. Initial paid evaluation allowance is USD 10 total, not USD 10 per task or restart.

## Requirements

- Dependency: None beyond final planning review; do not start implementation until reviewed.
- Extend existing AI Settings with a Jev section: enabled state, model/reviewer configuration, total allowance default USD 10, sample/batch limits, concurrency, retries and separate evidence/recommendation display thresholds. Provide defaults, validation and credential masking.
- Persist future-run defaults and immutable per-run resolved settings/model/rubric identities. Settings edits do not mutate active runs. Distinguish queue eligibility and display counts from decision thresholds and work limits.
- Implement a feature-scoped cumulative allowance ledger with atomic pre-dispatch reservations, usage reconciliation, uncertain-charge handling and no refill on retry/restart. Jev, reviewers and paid probes share the allowance. Stop calls when a conservative price bound is unavailable.
- Provide a narrow bounded-decision interface with answered/abstained/unavailable/invalid outcomes, immutable evidence references, usage and latency. Do not mutate Skills or Job facts.
- Provide an explicit bounded-run launch/status/cancel surface with resolved settings and spent/reserved/remaining amounts. Loading a page or saving defaults must not start paid work.

## Acceptance Criteria

- [ ] Settings round-trip with validation and secret masking; updated defaults apply only to new runs.
- [ ] Concurrency, retry, cancellation, ambiguous failures and resumed-run tests demonstrate no dispatch beyond the reserved allowance.
- [ ] Read-only page loads and settings saves issue no paid requests. Disabled/unavailable states preserve existing product behavior.
- [ ] ORM metadata and empty-sandbox bootstrap include the new Jev tables. Deployment follows the repository's stop → export → clear → bootstrap → import → verify → start cutover; no in-place migration, compatibility column, or schema-history table is introduced. Feature rollback disables Jev and leaves its inert records available for audit.
- [ ] The native System One adapter sends `state`, `model`, and named `questions` to the configured full endpoint, validates typed answers plus token usage, and never logs or returns the bearer credential.
- [ ] A paid request cannot start without an explicit conservative USD reservation. If pricing or a per-request upper bound is unavailable, the run remains unavailable and no request is sent.

## Dependencies

None beyond final planning review; do not start implementation until reviewed.

## Design references

Read parent `../09-23-research-jev-use-cases/design.md`, `prd.md`, `implement.md` and research evidence. Native endpoint details are supplied locally in `docs/jev.md`; its bearer credential is a secret and must never be copied into tracked source, task artifacts, logs, fixtures, or issue text.
