# Manual Jev batch orchestration

## Goal

Provider-free bounded preview and explicit manual Jev start, stop, resume,
retry, and per-operation eligibility, with the Jev API Console as the sole
monetary-limit authority.

## Requirements

- Preview is provider-free and selects a bounded historical/current Job set by
  source, keyword, explicit Job IDs, processing state, and maximum count.
- The operator selects any combination of Skills correction, Possible same
  vacancy, and Related Jobs. One explicit Start freezes the selected Jobs and
  creates independent per-Job/per-operation items.
- Eligibility is operation-specific. By default, never-run, stale, and failed
  items are eligible; successful unchanged items are skipped unless force
  reevaluation is selected.
- Preview reports selected/eligible/skipped counts per operation before any
  provider call. It does not estimate cost or enforce a local spending limit.
- Only explicit Start, Resume, and Retry authorize dispatch. Stop prevents new
  requests while allowing already-dispatched work to settle. Restarted work is
  left stopped and requires manual Resume; terminal failures never auto-retry.
- Partial failures do not roll back successful independent items. Retry creates
  work only for failed items.
- Jev API Console owns monetary quota and spending limits. Remove local
  allowances, reservations, token price estimates, request-cost ceilings, and
  all local monetary dispatch gates. Provider-returned request IDs, token usage,
  latency, and cost remain optional audit receipt data and never gate dispatch.
- Keep non-monetary operational bounds: explicit manual authority, bounded
  selection/question counts, concurrency, timeout, retry limits, idempotency,
  Stop, and restart-to-manual-Resume behavior.
- Scheduled Skill maintenance and ordinary AI enrichment must not initiate Jev.

## Acceptance Criteria

- [x] Preview performs zero provider requests and reports frozen Job membership
  and per-operation eligibility without local monetary estimates.
- [x] A single manual Start creates only the selected operations and each item
  has durable progress/result/error state.
- [x] Double Start is idempotent and cannot duplicate paid work.
- [x] Successful unchanged work skips by default; force reevaluation is explicit.
- [x] Stop prevents later items from dispatching; Resume is manual.
- [x] Interrupted running batches become stopped on process startup without
  dispatch and require manual Resume.
- [x] Retry targets failed items only and preserves prior successes.
- [x] Partial failure continues independent items and ends with an explicit
  completed-with-failures state.
- [x] AI enrichment and scheduler tests prove zero implicit Jev initiation.
- [x] A configured explicit run reaches Jev without any local allowance,
  reservation, rate, or cost-ceiling prerequisite; provider failures remain
  auditable and do not mutate protected domain state.

## Notes

- Keep `prd.md` focused on requirements, constraints, and acceptance criteria.
- Lightweight tasks can remain PRD-only.
- For complex tasks, add `design.md` for technical design and `implement.md` for execution planning before `task.py start`.
