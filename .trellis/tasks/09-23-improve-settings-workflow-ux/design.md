# Settings workflow design

## Navigation and editing

Settings owns validated section navigation in the existing hash query, preserving existing #settings links. Once visited, AI Runtime and Scraper Pacing remain mounted within this page so switching sections preserves unsaved inputs without persisting credentials to browser storage. Browser refresh reloads server configuration; show unsaved state and a before-unload warning.

AI Runtime derives a saved baseline from the server response, displays dirty state, and offers explicit discard. Preserve the existing Save action for reapplying configuration; disable actions while save/test is in flight. Saving, validation errors and readiness testing remain distinct. Draft edits are preserved on failure. Add load retry and feedback focus. Keep all provider, Jev, concurrency and maintenance controls directly accessible.

Add a compact anchor navigation to major runtime sections; it scrolls/focuses without hiding controls. Describe provider testing as using draft configuration and contacting the provider; saved-readiness remains separate. Preserve existing explicit Jev paid actions.

Scraper Pacing keeps per-source state and adds load retry, discard per card and confirmation before reset overwrites unsaved edits. Existing plan snapshots and future-task semantics remain unchanged.

## AI troubleshooting handoff

AI readiness links carry Settings section, Jobs profile focus and a bounded internal return target to the AI console or exact run. Settings provides an explicit return link. Validate the return target; never navigate arbitrary external URLs.

## Safety and rollback

No API or provider policy changes. No new credential persistence. Existing server validation remains authoritative. Frontend-only rollback; no migration.
