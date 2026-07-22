# Design: GitHub issue lifecycle for Trellis tasks

## 1. Design intent

Use the existing Trellis lifecycle as the source of truth and add one
project-local GitHub adapter. Hooks handle deterministic task events; a
project-local skill handles the one event that is inherently conversational:
the user's manual QA report.

The design deliberately separates three states:

```text
planning ──task.py start──> implementation in progress
                               │
                               └─task archive──> committed, awaiting manual QA
                                                        │
                                  explicit user pass + close intent ──> closed
                                  explicit user failure ─────────────> open
```

An implementation commit is never treated as acceptance.

## 2. Boundaries

### Existing Trellis boundaries to reuse

- `.trellis/config.yaml` registers `after_start` and `after_archive` commands.
- `.trellis/scripts/task.py` and `common/task_store.py` continue owning task
  status, archive, and auto-commit behavior.
- `common/task_utils.run_task_hooks()` continues to provide `TASK_JSON_PATH`
  and non-blocking warning semantics.

### New project-local boundaries

- `.trellis/scripts/hooks/github_sync.py` owns all GitHub CLI calls, repository
  resolution, public-summary rendering, metadata persistence, idempotency, and
  warning-friendly exit codes.
- `.agents/skills/github-issue-task-lifecycle/SKILL.md` owns conversational
  routing when the user explicitly reports manual QA pass/failure and closure
  intent. It reads the active task and calls the sync script; it does not infer
  QA results from normal implementation language.
- `.trellis/hooks.local.json` is an optional gitignored override for local
  repository settings only. It never stores credentials.
- `task.json.meta` stores the remote binding, for example:

  ```json
  {
    "github_issue": 123,
    "github_issue_url": "https://github.com/owner/repo/issues/123"
  }
  ```

  `github_issue: false` is the explicit opt-out sentinel. No extra local status
  field is needed; GitHub open/closed plus append-only comments are the state.

## 3. Lifecycle flow

### A. `after_start` / create

1. Read `TASK_JSON_PATH` and task metadata.
2. Return without a GitHub call for explicit opt-out.
3. If an issue binding exists, validate the bound issue without reopening or
   replacing it; a missing/closed binding produces a warning.
4. Resolve repository from `git remote get-url origin`, with an optional
   gitignored local override.
5. Render a public-safe body from task metadata and selected PRD headings only:
   title, priority, task path, Goal, Requirements, Acceptance Criteria, and an
   optional parent issue reference. Never read design, implementation,
   journal, runtime, or environment files for the body.
6. Run `gh issue create`, recover the issue number/URL, and persist both in
   `task.json.meta` only after successful creation.

### B. `after_archive` / implementation update

1. Read the stored issue binding. If absent or invalid, warn and return.
2. Read `git rev-parse HEAD` after Trellis has completed its archive commit.
3. Append one comment that identifies the task, commit, and “awaiting manual
   QA”. The operation is idempotent by embedding a stable task/commit marker
   and checking existing comments before posting, or by recording a local
   event marker when comment lookup is unavailable.
4. Do not edit the body, close the issue, add labels, or claim a push.

### C. Conversational QA update

The local skill is intentionally narrow. It triggers only when the user gives
an unambiguous QA outcome tied to the current task, for example:

- “测试失败：<details>” → append a failure comment; issue remains open.
- “测试通过，可以关闭对应 issue” → append pass evidence and close the bound
  issue.

If the language is ambiguous, the agent asks for clarification and performs no
GitHub mutation. The skill must never close a parent issue because a child
passed.

The sync script exposes internal actions such as `qa-pass` and `qa-fail`; the
user does not need to invoke a command. The skill supplies the explicit intent
and evidence gathered in the conversation.

## 4. GitHub adapter contracts

### Repository resolution

- Default: parse the `origin` fetch URL into `owner/repository`.
- Optional: read a gitignored local override when a developer intentionally
  tracks a different repository.
- Authentication: delegate to the existing `gh` login/session. Never read or
  write PATs, `GITHUB_TOKEN`, or credentials from tracked files.

### Issue binding and idempotency

- The task's `meta.github_issue` is the authoritative binding after creation.
- A missing binding is the only condition that permits create.
- A closed/deleted bound issue is a warning state, not a create/reopen signal.
- Parent references are display-only and never a state dependency.
- Stable comment markers (`trellis-task:<task-path>:<event>:<commit>`) prevent
  repeated archive hooks from producing duplicate comments.

### Failure behavior

- The hook script returns non-zero on external failure so the existing hook
  runner prints a warning, but the runner does not fail the task operation.
- Missing `gh`, unauthenticated `gh`, network errors, malformed CLI output, or
  repository resolution failures must include an actionable warning.
- No metadata is persisted for a failed create. Later lifecycle invocations can
  retry.

## 5. Public-summary rendering

The renderer is deterministic and conservative:

```text
<task title>

Trellis task: <relative task path>
Priority: <priority>
Parent issue: #<N>                 # only when available

## Goal
<Goal section from prd.md, if present>

## Requirements
<Requirements section from prd.md, if present>

## Acceptance Criteria
<Acceptance Criteria section from prd.md, if present>
```

If a section is missing, omit it rather than guessing. The renderer never
performs heuristic redaction; the fixed allowlist is the safety boundary.

## 6. Compatibility and rollback

- With hooks disabled, all existing Trellis behavior remains unchanged.
- With `github_issue: false`, a task is completely local and creates no remote
  side effect.
- Removing the two hook registrations disables future sync without changing
  existing task metadata or GitHub issues.
- Removing the skill disables conversational QA automation without affecting
  lifecycle hooks.
- No database migration or application runtime change is required.

## 7. Key trade-offs

| Decision | Chosen approach | Reason |
|---|---|---|
| Trigger | `after_start` | Existing plan-confirmed lifecycle boundary |
| Completion update | `after_archive` | Runs after Trellis archive commit; no push claim |
| QA signal | Explicit user conversation | Human testing is not machine-observable |
| Issue body | One-time allowlisted summary | Prevents overwrites and public leakage |
| State | Comments + open/closed | Avoids label drift and custom state machine |
| Failure | Warning + retry | GitHub outage must not block local work |
| Parent/child | Separate issue with reference | Prevents accidental cascading closure |
| Credentials | Authenticated `gh` | No token storage in the repository |
