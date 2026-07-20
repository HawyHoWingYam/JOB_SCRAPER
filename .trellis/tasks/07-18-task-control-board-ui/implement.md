# Parent implementation and integration plan

## Purpose

This parent coordinates two completed backend children and three independently
checked UI children. It remains `planning` and is not an implementation target.

## Gate 0 — final planning approval

- [x] User approved CP10 live rollout separately; Versioned Crawl Scope is
  archived with live evidence.
- [x] User approved final Task Control Board UI planning and starting three UI
  children.
- [x] Split the combined Board/Wizard scope into Governance, Wizard, and
  Board/Task Details children.
- [x] Preserve unrelated dirty `.codex`, frontend, spec, and historical-doc
  changes.
- [x] Record the two narrow server-contract gaps in their owning UI children;
  do not reopen completed backend checkpoints broadly.

## Completed backend dependencies

### Child 1 — Source Catalog runtime correctness

- [x] Immutable Catalog lifecycle, three Source adapters, durable validation,
  published compatibility API, and runtime query authority delivered.
- [x] Child checked, committed, and archived.

### Child 2 — Versioned Crawl Scope and Automation control

- [x] Authored/Resolved Scope, Automation lifecycle, Dispatch Plans,
  listing/detail authority, normalized run projections, migration/cutover tools,
  and real Catalog impact delivered.
- [x] CP10 backup, migration, initial publication, fenced reset, bounded smoke,
  acknowledged cancellation, and post-rollout verification completed.
- [x] Child checked, committed, and archived.

## Three UI children

### UI child 1 — Source Catalog governance

Task: `07-18-source-catalog-governance-ui`

- [x] Establish compatible structured API errors and `#source-catalogs` route.
- [x] Build revision health, discovery, diff, durable validation/manual action,
  real Automation impact, publish/rollback, and immutable history.
- [x] Prove page load is read-only and stale impact/candidate cannot publish.
- [x] Pass feature-focused tests and build checkpoint; do not rerun unrelated
  backend suites.
- [x] Commit and archive after its Trellis check.

Rollback: hide/remove the frontend route without changing active Catalog state;
CLI/API publication remains server-gated.

### UI child 2 — Automation and One-off wizard

Task: `07-18-task-control-board-wizard-ui`

- [x] Add the narrow read-only Automation review/fingerprint seam with focused
  backend contract tests.
- [x] Establish feature-local Crawl Control route, decoders, versioned draft,
  reducer, and four-step shell.
- [x] Implement Automation listing/detail and One-off listing/detail flows,
  Edit, Run now, schedule/timezone, scope tree, workload review, plan dispatch,
  and detail-conflict cancellation recovery.
- [x] Keep the legacy Board/forms reachable until all four routes pass.
- [x] Pass focused backend/frontend tests and production build checkpoint.
- [x] Commit and archive after its Trellis check.

Rollback: remove Wizard routes/review endpoint while preserving Automations,
plans, and the legacy board; stale plans are discarded, never reconstructed.

### UI child 3 — Task Control Board and Task Details

Task: `07-21-task-control-board-operations-ui`

- [x] Add the narrow Board V2/source-summary/action-capability and normalized
  single-task projections with focused backend tests.
- [x] Implement `#scheduler` source tabs/banner, Needs attention, Active runs,
  Upcoming Automation table, and All clear.
- [x] Implement Pause/Resume, Archive/Restore, permanent-delete impact, and
  links to Wizard/Governance/Logs.
- [x] Refactor `#crawl-tasks?task=<id>` Task Details to use normalized authority,
  workload/snapshot, issue/manual-action, recovery, and cancellation fields.
- [x] Remove ordinary raw `manual_action`/`request_payload` JSON rendering.
- [x] Retire legacy scheduler composition only after parity tests pass; remove
  the temporary switch before acceptance.
- [x] Pass focused backend/frontend tests and production build checkpoint.
- [x] Commit and archive after its Trellis check.

Rollback: switch `#scheduler` back to the old composition while leaving backend
state untouched. Retain normalized Task Details/API work if only the board
visual composition is reverted.

## Implementation ordering

1. Move all three UI children from `planning` to `in_progress` under the user's
   approval.
2. Implement Governance first because it owns the compatible shared API-error
   update and Source Catalog route.
3. Implement Wizard second because it establishes shared Crawl Control route,
   decoder, draft, and confirmation seams.
4. Implement Board/Task Details third because it consumes Wizard route/action
   seams and replaces the legacy scheduler composition.
5. Do not implement the three children concurrently in overlapping `App.jsx`,
   API-client, or shared feature files. Status may be active while delivery stays
   sequential.

## Parent integration review

- [x] Published candidate/revision state, wizard catalog selection, Dispatch
  Plan authority, Board, and Task Details show identical Source/Revision IDs.
- [x] Candidate data cannot enter scope validation or runtime execution.
- [x] Automation review and save revalidate the same configuration/revision;
  One-off and Run now consume the exact reviewed plan fingerprint.
- [x] Board section membership, priority, action capabilities, schedule summary,
  latest outcome, and catalog health are backend-owned.
- [x] Page Depth/Run Page Cap and Detail Run Cap/Recovery Segment/snapshot/future
  backlog remain distinct end to end.
- [x] Pause/Archive do not imply run cancellation; run cancellation remains
  `cancelling → cancelled` and preserves committed work.
- [x] Task Details and all new features contain no raw payload/event parsing for
  scope, readiness, metrics, or recovery actions.
- [x] CTgoodjobs exposes headed-only behavior.
- [x] Browser hash back/forward, versioned draft corruption/storage failure,
  request abort/version guards, keyboard/focus, and narrow desktop pass.

## Validation budget

During each child:

```text
direct pure/component tests
  -> focused backend contract tests only when that child changes a projection
  -> scoped lint/build checkpoint
  -> one Trellis check
```

At final cross-child integration only:

```bash
cd frontend
npm test
npm run lint
npm run build
```

Also run focused backend API/projection tests for the two narrow additions and
`git diff --check`. Do not rerun the full backend suite or CP10 rollout without
new regression evidence.

## Parent acceptance evidence map

| Acceptance | Owner | Evidence |
| --- | --- | --- |
| Candidate/revision governance is explicit and stale-safe | Governance | route/API/reducer/dialog/manual-action tests |
| Four authoring flows create truthful reviewed commands | Wizard | reducer/route/draft tests plus Automation-review and Dispatch Plan contracts |
| Board prioritization and Automation actions are normalized | Board | Board V2 projection/API/component tests |
| Listing/detail Task Details contain no payload archaeology | Board | normalized single-task contract and source-search guard |
| Cancellation waits for acknowledgement | Wizard + Board | conflict and Task Details one-second polling/terminal tests |
| Desktop navigation/accessibility | all UI children | hash, keyboard, focus, dialog, table/nested-list tests |
| Full UI convergence | parent | one full frontend suite/lint/build and cross-layer smoke matrix |

## Final handoff

- [x] All three UI children are checked, committed, and archived.
- [x] Parent acceptance criteria map to exact test/evidence paths.
- [x] Any direct integration fix is placed in a separately approved child; do
  not silently start the parent.
- [x] Update `docs/20260718.md` and run `trellis-finish-work` once the complete
  Crawl Control UI program is accepted.
