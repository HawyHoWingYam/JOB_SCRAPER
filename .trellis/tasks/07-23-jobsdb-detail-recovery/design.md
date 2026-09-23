# Technical design

## Boundaries

The parent coordinates two child deliverables:

1. The detail scraper resolves the reviewed mode for a fresh browser launch while leaving explicit live-browser attachment intact.
2. A JobsDB recovery layer owns profile allocation/liveness/reset and projects safe actions to both recovery surfaces in the frontend.

The crawl job, detail checkpoint, dispatch-plan authority, and parser contracts remain the source of truth; profile state is operational metadata and must not alter target scope.

## Data flow

```text
reviewed crawl_mode + resume_strategy
        │
        ├─ fresh_profile ──> allocate task-owned profile ──> launch with mode headless flag
        │                                      │
        │                                      └─ terminal cleanup / lazy orphan cleanup
        │
        └─ reuse_open_browser ──> verify helper + registry session ──> CDP attach

launch failure ──> liveness check ──> safe cleanup once ──> one retry
                                  └─> uncertain/live ──> manual_action_required + diagnostics
```

The manual-action payload carries `crawl_mode`, `resume_strategy` capability, browser profile metadata, and a structured recovery stage. A headless task may opt into `reuse_open_browser` only from the explicit verification-browser controls; its ordinary fresh path remains headless.

## Contracts

- `fresh_profile` is the default API strategy and receives a task/run-owned profile path persisted in the resume context or request payload so a paused task can be resumed safely.
- `reuse_open_browser` requires a browser channel/profile path and a reachable registry session. Failure reports “open/reconnect verification browser” rather than a generic Edge instruction.
- Reset returns a structured safety result: `reset_available`, `liveness`, `profile_scope`, `removed_lock_markers`, and a reason when disabled. It is idempotent and never deletes a fixed profile’s user data.
- Task Details action projections advertise only capabilities proven by the normalized manual-action payload. The generic action is replaced by explicit strategy actions; helper health remains a prerequisite for opening/reusing a browser.
- Recovery events record the selected strategy, cleanup attempt/result, profile scope, liveness evidence, and final stage. Completed-target checkpoint data is not rewritten.

## Profile lifecycle and safety

- Fresh allocation creates a deterministic child directory under the configured JobsDB profile root, keyed by task/run identity plus a collision-resistant suffix. Allocation first lazily removes only orphaned task-owned directories older than the TTL.
- The process liveness adapter is injectable for tests. It checks matching worker processes for container-owned fresh profiles and the live-browser registry/helper reachability for fixed headed profiles.
- Lock marker deletion is limited to known Chromium singleton markers. If process enumeration or registry reachability is unavailable, the operation fails closed.
- Terminal cleanup is best-effort and observable; a failed cleanup does not change crawl outcome. A later allocation may remove the orphan after TTL.

## Compatibility and rollout

- Read/resume paths continue through `normalize_manual_action_payload`, filling missing fields for legacy events without a migration.
- Existing tasks with trustworthy request payload/checkpoint data can use the new actions. A record lacking enough identity to safely allocate/reset a profile is shown a clear “start a new scoped task” fallback.
- Roll out backend contracts and tests before enabling the new Task Details buttons. Keep the existing recovery panel as the canonical helper flow and make both surfaces consume the same capability projection.
- Rollback is configuration/code-level: disable new reset action projection and fall back to fresh resume; do not delete profile data or rewrite task events.
