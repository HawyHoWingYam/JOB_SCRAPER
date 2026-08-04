# Implementation plan

1. Read the backend specs and the exact catalog mutation boundary.
2. Verify the live catalog still matches the reviewed 127-enabled baseline.
3. Export the live CSV, construct the approved delta in memory, preview it, and programmatically assert exactly seven adds plus one disable.
4. Confirm with the single-use token; verify 133 enabled entries, disabled `pentest`, retained terms, absent `Splunk`, and a mutation log entry.
5. Record sanitized before/preview/after evidence without secrets or the confirmation token.
6. Commit only task-owned evidence/artifacts and summarize the result on issue #49 without closing it.

## Rollback points

- Before CSV confirmation, discard the preview token if any baseline or action-set assertion fails.
- After confirmation, use a new governed CSV preview/confirm operation to disable the seven additions and re-enable `pentest` if rollback is required.

## Validation

- Programmatic catalog baseline, preview action-set, post-confirmation, and mutation-log assertions.
- Secret-bearing artifact scan, `git diff --check`, and a staged-path audit before committing.
