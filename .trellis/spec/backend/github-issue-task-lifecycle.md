# Trellis GitHub Issue Lifecycle Contracts

## 1. Scope / Trigger

Use this contract when changing the project-local integration between Trellis
task lifecycle hooks, the authenticated `gh` CLI, and manual QA updates.

## 2. Signatures

```text
after_start  -> python3 .trellis/scripts/hooks/github_sync.py create
after_archive -> python3 .trellis/scripts/hooks/github_sync.py archive
qa-fail --notes <failure details>
qa-pass --close --notes <pass evidence>
```

The adapter receives the absolute task metadata path through `TASK_JSON_PATH`.

## 3. Contracts

- `task.json.meta.github_issue` is the authoritative positive issue number;
  `false` opts a task out. Successful create also stores
  `meta.github_issue_url`.
- `origin` supplies the `owner/repository` authority, unless the gitignored
  `.trellis/hooks.local.json` provides an explicit local repository override.
- Issue creation reads only task metadata and the `Goal`, `Requirements`, and
  `Acceptance Criteria` sections of `prd.md`.
- Archive and QA updates append marker-tagged comments. Archive means
  implementation committed and awaiting manual QA; it never claims a push.
- Only explicit QA pass evidence with `--close` closes the bound issue. QA
  failure leaves it open. Parent and child issues are independent.

## 4. Validation & Error Matrix

| Condition | Required result |
|---|---|
| Missing `TASK_JSON_PATH`, invalid task JSON, missing binding | Non-zero warning; no GitHub mutation beyond any already-completed call |
| `github_issue: false` | Zero exit; no repository or `gh` call |
| GitHub/`gh`/origin failure | Non-zero warning; local Trellis lifecycle remains non-blocking and retryable |
| Closed or deleted bound issue | Warn and never reopen or duplicate |
| Existing archive/QA marker | Do not add a duplicate comment |
| Repeated QA pass after the same pass closed the issue | No duplicate comment or close call; report already closed |
| Ambiguous conversational QA language | Ask for clarification; make no mutation |

## 5. Good / Base / Bad Cases

- **Good:** start creates one issue and persists its binding; archive adds one
  commit/awaiting-QA comment; explicit pass closes that issue.
- **Base:** GitHub is unavailable during a hook; Trellis still completes the
  local start/archive and prints a warning for a later retry.
- **Bad:** search by title, create a replacement for a closed issue, close a
  parent when a child passes, or copy `design.md`, `implement.md`, journals,
  credentials, environment, or database data into the public body.

## 6. Tests Required

- Mock every `gh` call and assert public-summary allowlisting, metadata
  preservation, origin/override parsing, parent references, opt-out behavior,
  marker idempotency, closed-binding safety, and QA close/no-close behavior.
- Assert repeated QA pass after close performs no second comment or close.
- Run Trellis task validation, Python compilation, unit tests, and `git diff
  --check`. Any real issue smoke is a separate user-approved manual action.

## 7. Wrong vs Correct

### Wrong

```text
task.py archive -> close the issue automatically
```

This confuses an implementation commit with product acceptance and prevents
manual QA from reporting failures.

### Correct

```text
task.py archive -> append “awaiting manual QA”
explicit QA pass + close intent -> append evidence and close the bound issue
```
