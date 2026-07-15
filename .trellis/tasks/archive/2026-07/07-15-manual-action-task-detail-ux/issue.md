## Problem

The Crawl Tasks `Task Details` panel does not give operators a clear recovery
path when a crawl enters `manual_action_required`. In the helper-offline state it
shows raw setup values alongside several equally weighted actions, some of which
cannot succeed until the host helper or reusable browser is available.

## Scope

- Replace the flat manual-action control cluster with a capability-driven guided
  flow: helper recovery -> browser connection -> explicit crawl resume.
- Copy the exact helper start command and poll health after the copy action.
- Keep browser opening and crawl resume as explicit operator actions.
- Describe reusable browser state as connected, not authenticated or verified.
- Keep fresh-profile resume as a warned secondary fallback.
- Collapse diagnostics and confirm profile cleanup and crawl cancellation.
- Preserve legacy/manual-review and non-manual Task Detail behavior.

This delivery is frontend-only. It does not add a resident host launcher or a
source-specific backend access-verification API.

## Acceptance criteria

- [ ] Helper-offline tasks show one clear primary recovery action.
- [ ] Helper polling advances UI state without automatically opening a browser.
- [ ] Browser connection and crawl resume remain explicit actions.
- [ ] Connectivity wording does not claim source access has been verified.
- [ ] Fresh-profile fallback stays visible with a consequence warning.
- [ ] Diagnostics are collapsed and disruptive/destructive actions are confirmed.
- [ ] Reusable-browser, unsupported manual-action, and existing non-manual paths
      have automated frontend coverage.

## Planning artifacts

Trellis task: `.trellis/tasks/07-15-manual-action-task-detail-ux`
