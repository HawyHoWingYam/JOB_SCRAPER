# QA automated classification batches through the UI

## Goal

Use the Automated Classification console as the primary operator surface to
exercise and validate backend candidate selection, batch lifecycle,
classification, persistence, Stop, and Retry behavior for Company Industry and
Skills. The historical Job Taxonomy QA evidence is superseded by task
`07-29-remove-canonical-job-taxonomy`. Turn every confirmed product defect into reproducible,
actionable GitHub issue evidence.

## Background

- The intended lifecycle is preview, start, progress monitoring, cooperative
  Stop, failure inspection, and failed-item Retry.
- Preview is read-only. Start, Stop, and Retry persist batch state; execution can
  mutate classification data and invoke an external LLM.
- GitHub issue #32 is the umbrella QA tracker:
  `https://github.com/HawyHoWingYam/JOB_SCRAPER/issues/32`.
- The current session has working Chrome DevTools, Playwright, read-only
  PostgreSQL, and GitHub MCP connections.
- The repository has Vitest component tests but no repository-owned browser E2E
  suite or classification-specific seed environment. Existing UI tests mock the
  API; existing backend runtime tests use fake adapters and SQLite.
- The current local environment and database are disposable sandbox
  infrastructure. Mutating lifecycle actions and real calls to the configured
  external LLM are approved; no second QA deployment is needed.
- Planning-time inventory found 19,731 eligible unassigned Jobs, 5,303 eligible
  unassigned Companies, and 1,738 unresolved Skill Candidates at the effective
  five-Job threshold. The configured `custom` Jobs LLM has a key, its most
  recent connection test passed, and no classification run was active.

## Requirements

### Test boundary and evidence

- Treat the UI as the primary action path and backend behavior/data as the
  primary test target; appearance is not the center of this QA pass.
- Use Chrome DevTools MCP for primary interaction, console, network, snapshot,
  and screenshot evidence. Use Playwright MCP for independent reproduction when
  useful.
- Use read-only API and PostgreSQL inspection after UI actions to prove hidden
  candidate snapshots, state transitions, aggregate counts, and persisted
  effects. Do not write to the database or fabricate state directly.
- Use existing sandbox candidates. Branches that cannot be reached naturally
  through supported UI actions must be covered by automated tests where
  possible and reported as interactive-coverage limitations.

### Shared batch lifecycle

- Verify source filtering and limit validation, including normal, boundary,
  invalid, loading, empty, and error behavior where reachable.
- Verify preview/start selection parity, persisted stable item snapshots,
  per-domain active-run exclusivity, cross-domain independence, terminal states,
  aggregate counts, item failure isolation, and failed-only Retry.
- Verify cooperative Stop: finish an in-flight item, cancel untouched items,
  expose the stopping/terminal state, and keep counts consistent.
- Begin ordinary real runs with one to three candidates per domain. One combined
  concurrency/Stop scenario may request at most 20 candidates and must issue
  Stop immediately; it is acceptable if all 20 finish before Stop takes effect.
- Classify observed failures as product behavior, candidate/data constraint, LLM
  configuration, or provider/network behavior before filing a defect.

### Domain behavior

- Company Industry must select only eligible non-deleted unassigned Companies,
  respect Source filters, require mapped Source Industry evidence preserved by
  Jobs, and never guess from display labels.
- Skills must ignore Source filtering, apply the configured distinct-Job
  threshold, reuse current name/code/alias matches, reject known generic terms,
  and create a new Skill only under a confirmed active Category/Technology path
  without fallback nodes or partial writes.

### Defect handling

- Preserve environment, severity, exact reproduction steps, expected behavior,
  actual behavior, UI/network/database evidence, and affected domain for every
  confirmed defect.
- Keep #32 as the umbrella tracker. File each confirmed, reproducible,
  independently fixable defect as a thin behavior-focused issue linked to #32.
  Keep non-reproducible observations in the QA report.
- Do not modify product code unless the user separately approves a fix phase.

## Acceptance Criteria

- [x] A reviewed QA matrix covers shared lifecycle contracts and both retained
      domain contracts, driven through the UI whenever an action is exposed.
- [x] Relevant frontend and backend automated tests are run and recorded.
- [x] UI-driven actions are correlated with network responses and read-only
      PostgreSQL evidence for item snapshots, counts, states, and persisted
      effects.
- [x] At least one real processing attempt is made for each retained domain with an
      initial limit of one to three.
- [x] Same-domain exclusion, cross-domain independence, and cooperative Stop are
      attempted with no run larger than the approved 20-item ceiling.
- [x] Failed-only Retry is verified interactively when a natural failed item is
      available; otherwise its automated coverage and interactive limitation are
      recorded.
- [x] Every filed defect meets the evidence and reproducibility requirements and
      links to #32.
- [x] The final report contains pass/fail status by contract, run IDs, defects,
      blocked scenarios, coverage limitations, and residual risks.

## Out of Scope

- Product-code fixes during the initial QA pass.
- Production data or production classification runs.
- A second QA database or separate deployment.
- Direct database writes or manufactured test states.
- Dedicated responsive-design, Lighthouse, visual-polish, load, or performance
  testing unless an issue blocks the backend workflow.
