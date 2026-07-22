# Automate GitHub issue lifecycle for Trellis tasks

## Goal

Give every started Trellis task a durable, public GitHub tracking issue and
keep that issue accurate through implementation and human QA, without making
GitHub availability a prerequisite for local development or allowing an
implementation commit to be mistaken for product acceptance.

## Confirmed repository facts

- `.trellis/config.yaml` supports task lifecycle hooks at
  `hooks.after_start` and `hooks.after_archive`; this task enables both hooks
  for the GitHub adapter.
- `.trellis/scripts/task.py:70-141` changes a planning task to `in_progress`
  and invokes `after_start`.
- `.trellis/scripts/common/task_store.py:500-522` archives a task, performs the
  existing Trellis-owned auto-commit, and then invokes `after_archive`.
- `.trellis/scripts/common/task_utils.py:219-253` passes `TASK_JSON_PATH` to
  each hook and deliberately warns instead of failing the main lifecycle
  operation when a hook exits non-zero.
- `.trellis/scripts/hooks/linear_sync.py` is an existing external lifecycle
  sync example that stores its remote identifier under `task.json.meta`.
- The current repository is public and has an `origin` remote. The `gh` CLI is
  available in the development environment. Trellis itself has no local
  `git push` implementation; this task must not claim that an archive hook
  verified a push.

## Product decisions

- `task.py start` is the plan-confirmation boundary. Issue creation happens at
  `after_start`, not at task creation.
- Every started task creates an issue by default. A task may explicitly opt out
  with `task.json.meta.github_issue: false`.
- Each parent and child task gets its own issue. A child may reference the
  parent's issue, but issue state never cascades automatically.
- Issue body is written once at creation from a public-safe summary containing
  the task title, priority, task path, Goal, Requirements, and Acceptance
  Criteria. `design.md`, `implement.md`, journals, environment data, database
  samples, and credentials are never copied automatically.
- Later lifecycle events append comments; they never overwrite the issue body.
- After archive, the issue receives an implementation-complete / awaiting
  manual QA comment. This does not close the issue and does not assert that the
  branch was pushed.
- Human QA is outside the automation. The user reports a result in chat. Only
  an explicit statement that testing passed and the corresponding issue should
  be closed permits closing. A failure adds a comment and leaves the issue
  open. Ambiguous language does nothing.
- GitHub access uses the authenticated `gh` CLI and derives the repository from
  `origin`; no token or repository credential is committed. A local,
  gitignored override may be supported later for a different repository.
- External sync failures are visible warnings and are retryable; they never
  block task start, archive, commit, or other local Trellis work.
- If a stored issue is already closed, deleted, or otherwise unavailable, the
  sync must warn without reopening it or creating a duplicate.

## Requirements

### R1. Plan-confirmed issue creation

- An `after_start` hook creates one GitHub issue for a task with no existing
  `meta.github_issue`, unless `meta.github_issue` is explicitly `false`.
- The issue title is derived from the task title. The issue body is the
  public-safe summary defined above and includes the Trellis task path for
  traceability.
- On successful creation, the script persists the issue number and URL in
  `task.json.meta`.
- Re-running the hook for the same task is idempotent and never creates a
  second issue.
- If a parent task has a stored issue, the child body includes a non-authority
  parent reference; no parent status mutation occurs.

### R2. Implementation lifecycle update

- An `after_archive` hook looks up the stored issue and appends a comment with
  the task path, current commit identifier, and “awaiting manual QA” wording.
- The hook does not overwrite the issue body, add a required custom label, close
  the issue, or claim remote push success.
- Missing or invalid bindings produce a visible warning and leave the local
  archive result intact.

### R3. Conversational QA outcome

- A project-local skill/workflow instruction tells the agent how to handle an
  explicit user report of manual QA success or failure.
- A successful report appends evidence and closes only the bound issue when the
  user explicitly requests closure.
- A failed report appends the failure details and leaves the issue open.
- Ambiguous statements do not call GitHub mutations.
- Parent issues are never closed as a side effect of child QA.

### R4. Safety, configuration, and retry behavior

- All GitHub mutations go through a small project-local sync script using `gh`;
  no GitHub token is stored in the repository.
- `origin` is the default repository authority. Optional local configuration is
  gitignored and cannot silently override a task's stored issue binding.
- Hook failures are non-blocking, explicit, and retryable. A failed create does
  not write a fake issue ID.
- A stored closed/deleted issue is not reopened or duplicated automatically.
- The implementation does not add automatic `git push`, issue label state
  machines, webhook infrastructure, or parent/child issue cascading.

## Acceptance Criteria

- [ ] Starting a temporary task creates exactly one GitHub issue with the
      public-safe summary and persists its number/URL in `task.json.meta`.
- [ ] Starting the same task again does not create a duplicate; an explicit
      `meta.github_issue: false` task makes no GitHub call.
- [ ] Child issue creation references an existing parent issue without changing
      parent state.
- [ ] Archiving a task appends an implementation/awaiting-QA comment containing
      the commit identifier, without closing or overwriting the issue.
- [ ] GitHub auth/network failure leaves the local lifecycle successful and
      emits a warning; a later retry can recover without duplication.
- [ ] Closed/deleted stored issues are reported and never reopened or copied.
- [ ] Explicit conversational QA success can append evidence and close the
      bound issue; explicit failure appends evidence and keeps it open; vague
      language performs no mutation.
- [ ] No generated issue body contains `design.md`, `implement.md`, journal,
      credential, or environment/database content.
- [ ] Existing Trellis task lifecycle behavior and current unrelated GitHub
      issues remain unchanged.

## Out of scope

- Automatically pushing branches or verifying remote CI/deploy state.
- Replacing the current Trellis task/archive/commit implementation.
- GitHub Projects, labels, milestones, webhooks, pull-request automation, or
  issue templates beyond the generated body.
- Automatic interpretation of human test results from arbitrary comments.
- Automatic reopening, duplication, or cascading closure of issues.
