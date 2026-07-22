---
name: github-issue-task-lifecycle
description: "Use when the user explicitly reports manual QA success or failure for the current Trellis task and asks to update or close its GitHub issue. Do not trigger on ordinary implementation progress or ambiguous approval language."
---

# GitHub Issue QA Update

This project uses Trellis lifecycle hooks to create a GitHub issue at
`task.py start` and append an implementation/awaiting-QA comment after task
archive. This skill handles only the user's explicit manual QA report.

Before mutating GitHub:

1. Read the current task with:

   ```bash
   python3 ./.trellis/scripts/task.py current --source
   ```

2. Read the active task's `task.json` and confirm `meta.github_issue` is a
   positive issue number. Respect `meta.github_issue: false` as opt-out.
3. Treat the task's stored issue binding as authoritative. Never infer an issue
   from a title search, and never update a parent issue because a child passed.
4. Require an unambiguous user outcome:
   - failure details → QA failure, issue stays open;
   - pass evidence plus an explicit request to close the corresponding issue →
     QA pass and close;
   - vague approval such as “looks good” → ask for clarification and make no
     GitHub call.

Use the project-owned adapter so all mutations share the same repository
resolution, idempotency, and closed-issue safety rules:

```bash
TASK_JSON_PATH="<absolute task.json path>" \
  python3 ./.trellis/scripts/hooks/github_sync.py qa-fail --notes "<failure details>"

TASK_JSON_PATH="<absolute task.json path>" \
  python3 ./.trellis/scripts/hooks/github_sync.py qa-pass --close --notes "<pass evidence>"
```

The adapter uses the authenticated `gh` CLI. A warning or authentication
failure must be reported to the user; do not invent an issue number, reopen a
closed issue, or create a replacement automatically.
