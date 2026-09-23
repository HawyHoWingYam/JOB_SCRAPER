# Task portfolio closeout — 2026-09-23

This record distinguishes tasks that are complete, tasks closed as superseded,
and work that remains genuinely open. It prevents old manual-QA wording or
historical product scope from being mistaken for current delivery requirements.

## Archive now

| Task | Closure basis |
| --- | --- |
| `09-23-research-jev-use-cases` | All Jev phases implemented; backend 748/748, frontend 224/224, Playwright 15/15, and seven real OpenRouter UI paths passed. |
| `07-27-qa-automated-classification-frontend` | QA matrix, evidence, terminal cleanup, defect filing, and final report are complete. |
| `07-29-diagnose-ai-enrichment-409` | Root cause, actionable UI remediation, active-run behavior, and regression coverage are complete. |
| `07-27-localized-generic-skill-retry` | Fix committed in `71fce2c9`; focused regression and current full regression are accepted instead of a separate human browser pass. |
| `07-27-invalidate-classification-preview` | Fix committed in `71fce2c9`; component race/invalidation coverage and current full regression are accepted instead of a separate human browser pass. |
| `07-27-company-industry-source-mapping` | Close as superseded. Company Industry was subsequently removed; the unperformed positive-mapping scenario is not represented as tested. |
| `07-27-fix-automated-classification-qa-defects` | Child outcomes are resolved as two verified fixes and one explicitly superseded product scope. |

## Update and keep open

| Task/workstream | Current remaining boundary |
| --- | --- |
| JobsDB detail recovery parent and children | Backend/live headless and stale-profile verification remain outstanding. |
| Cross-source expired-detail audit | Still planning; no completion evidence. |
| OfferToday adaptive listing coverage | Large planned redesign remains open; archived child is historical evidence only. |
| Job Intelligence governance | Jev absorbed the Skill and Company-surface implementation, but destructive retained-data reconciliation remains explicit before closure. |
| Cross-source detail ingest drift | Plan exists; completion evidence is absent. |
| OfferToday hung executions | Deadline/watchdog work remains separate from cursor-window recovery. |
| OfferToday/CTgoodjobs isolated failure recovery | Implementation and database widening are recorded; controlled OfferToday live verification and a new CTgoodjobs retry remain. |
| Searchable experience years | Still planning. |

## Consolidated decisions

- Human review is not a standing closure dependency when deterministic
  component/integration/browser coverage exercises the same contract and the
  user has explicitly waived a separate manual pass.
- Superseded work is closed honestly as superseded; its retired acceptance case
  is not relabelled as successfully tested.
- The 95 MB PostgreSQL safety dump under `database/backups/` is operational
  recovery evidence. It stays local and ignored rather than entering Git.
- Jev uses PostgreSQL persistence and real OpenRouter validation for the
  supplemental provider smoke; deterministic fake-provider tests remain the
  repeatable failure/edge-case gate.
