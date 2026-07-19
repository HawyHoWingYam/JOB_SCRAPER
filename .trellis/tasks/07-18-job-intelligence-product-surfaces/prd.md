# Job intelligence product surfaces

## Goal

Build one coherent post-collection Job Intelligence experience: a three-area governance workspace and consistent read-only terminology, filters, evidence, and states across Job Browser, Job Detail, Add Job, Companies, AI Enrichment, and Dashboard.

## Background

- Existing UI overloads Job Taxonomy/Classification/AI Category, labels Employment Type as Job Type, exposes polluted Industry strings, and presents unresolved mentions as Provisional Skills.
- Existing frontend tests use incomplete hand-built payloads rather than real backend response contracts.
- Domain decisions and exact language are in `CONTEXT.md` and parent PRD.

## Requirements

- Keep mapping and transition rules out of React; surface adapters consume only the reviewed API/read/decision contracts from children 2–5.
- Create `Job Intelligence Governance` with peer Job Taxonomy Review, Skill Candidates, and Company Industries areas.
- Provide summary/backlog counts, stable queues, filters/search, evidence/recommendation detail, explicit confirmation, conflict reload, audit timeline, and deep links.
- In the product UI, governance decisions are available only inside this workspace; other surfaces remain read-only and link into it. This UI placement is not an authentication boundary: v1 assumes trusted local access and warns against exposing unprotected decision routes to an untrusted network.
- Apply canonical terms everywhere and remove `Job Type`, `AI Category`, bare canonical `Classification`, and `Provisional Skills`.
- Job Browser uses hierarchical/multi-select stable-ID filters for Canonical Job Taxonomy, Company Industry, Employment Type, and Source paths as applicable.
- Job Detail displays all Source Classification Paths, Employment Types, accepted/unassigned canonical state/provenance summary, Company Industries, governed Skills, and secondary Unreviewed Skill Mentions.
- Company surfaces display Primary + N and full breadcrumbs; Add Job/manual inputs become evidence or governed selectors according to backend contracts.
- AI Enrichment shows source-qualified Source Classification Path filters and exclusion/review links without governance controls.
- Dashboard reports governed coverage, Unassigned reasons (including fallback/default evidence), review backlog, and Unknown counts explicitly; it never presents a fallback as an accepted assignment or collapses raw values into governed metrics.
- Implement loading, empty, error, stale-conflict, partial evidence, Unknown, responsive, keyboard, focus, label, and screen-reader states.
- Replace hand-built contract assumptions with backend schema fixtures/consumer tests.

## Acceptance Criteria

- [x] Three governance areas are navigable, deep-linkable, accessible, and execute only their own reviewed decision contracts.
- [x] The governance workspace displays the trusted-local/no-auth warning, and tests treat route placement as UX isolation rather than authorization.
- [x] Confirmation shows action, target, affected count, evidence, and irreversible consequences; stale version refreshes safely.
- [x] Retired terms are absent from user-facing UI except migration/audit history.
- [x] Job Browser filters support correct multi-value/ancestor semantics and show active chips with canonical names.
- [x] Job Detail never presents raw/provisional evidence as governed knowledge.
- [x] Company and Industry UI uses HSIC breadcrumbs and Primary + N without inferring Primary.
- [x] AI Enrichment and read-only surfaces deep-link but cannot decide governance items.
- [x] Loading/empty/error/Unknown/conflict and narrow-width behavior pass component tests and manual visual checks.
- [x] Frontend tests consume fixtures validated by backend response models.

## Dependencies and scope

- Depends on reviewed children 2–5 contracts and foundation conflict/idempotency conventions.
- Does not own backend domain rules, schema migrations, or destructive cutover.
- Parent integration requires this child plus child 7.

## Notes

- Complex child: requires `design.md` and `implement.md` review before start.
