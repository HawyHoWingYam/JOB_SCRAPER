# Implementation plan: GitHub issue lifecycle for Trellis tasks

Implementation must not begin until this plan is reviewed and the task is
activated with `task.py start`.

## Phase 1 — GitHub sync adapter

- [x] Add `.trellis/scripts/hooks/github_sync.py` with explicit internal
      actions for create, archive, QA failure, and QA pass/close.
- [x] Resolve `origin` safely and support only a gitignored local repository
      override; use the authenticated `gh` CLI for all mutations.
- [x] Read/write only the approved `task.json.meta` keys and preserve all
      unrelated task metadata.
- [x] Render the allowlisted public summary from `prd.md` without reading or
      copying design, implementation, journal, runtime, environment, or
      database content.
- [x] Make create, archive comments, and QA actions idempotent. Never reopen or
      duplicate a bound issue.
- [x] Return actionable failures so Trellis' existing hook runner warns without
      blocking local lifecycle operations.

## Phase 2 — Lifecycle wiring

- [x] Add `hooks.after_start` and `hooks.after_archive` entries to
      `.trellis/config.yaml` without changing existing auto-commit behavior.
- [x] Ensure archive sync observes the commit produced by the existing archive
      flow and reports “awaiting manual QA” without claiming a push.
- [x] Verify `meta.github_issue: false`, missing bindings, closed bindings, and
      parent issue references behave as specified.

## Phase 3 — Conversational QA skill

- [x] Add a project-local skill under `.agents/skills/` with a precise trigger
      for explicit user QA pass/failure language.
- [x] Require explicit closure intent before invoking QA pass/close.
- [x] Route failures to append-only comments that leave issues open.
- [x] Keep parent/child issue state independent and ask for clarification on
      ambiguous user statements.
- [x] Document that the skill must inspect the active task and its stored issue
      binding before any GitHub mutation.

## Phase 4 — Verification and regression coverage

- [x] Add unit tests for public-summary rendering, metadata persistence,
      repository parsing, idempotency, parent references, and opt-out behavior.
- [x] Add subprocess-mocked tests for successful and failed `gh` calls,
      closed/deleted bindings, archive comment markers, QA pass/close, and QA
      failure/no-close behavior.
- [x] Add lifecycle-hook tests or a temporary repository smoke script proving
      `after_start` and `after_archive` receive `TASK_JSON_PATH` and remain
      non-blocking when the sync script fails.
- [x] Run existing Trellis/task script checks and the repository's relevant
      lint/format checks.
- [ ] Exercise a disposable task end to end with a mocked `gh` executable; do
      not create real public issues during automated tests.
- [ ] Manually verify one real issue creation/update only after the user
      approves the implementation and confirms `gh auth` is ready.

## Validation commands

Expected commands after implementation (adjust to the repository's available
test runner):

```bash
python3 -m compileall .trellis/scripts
python3 -m unittest discover -s .trellis/tests -p 'test*.py'
python3 ./.trellis/scripts/task.py validate .trellis/tasks/07-22-github-issue-task-lifecycle
git diff --check
```

The test suite must mock `gh`; it must not mutate the public repository. A
real issue smoke is a separate, explicit manual step.

## Risk and rollback points

- Risk: a lifecycle hook creates duplicate public issues. Mitigation: existing
      metadata binding plus mocked repeated-start tests.
- Risk: public issue body leaks internal planning data. Mitigation: fixed PRD
      heading allowlist and tests asserting forbidden files/sections are absent.
- Risk: GitHub outage blocks work. Mitigation: existing non-blocking hook runner
      and no fake metadata persistence.
- Risk: an issue is accidentally closed after a vague QA statement. Mitigation:
      skill requires explicit closure intent and QA pass action is separate.
- Rollback: remove hook registrations and the project-local skill. Existing
      task metadata and remote issues remain untouched.
