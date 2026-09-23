# Crawl Tasks workflow design

The existing normalized backend projection remains authoritative. The frontend owns navigation and presentation only.

## Navigation and state

Extend the existing Crawl Tasks route codec with validated list filters and page. Keep task and events deep links compatible. Selection and audit navigation preserve list context; browser history restores the complete route. An off-page selection remains loadable and is explicitly explained.

Render audit events inside the application, scoped to the exact task. Fetch the bounded existing events endpoint, show loading/error/empty states and retry, and label the displayed tail versus total. Events are diagnostics, never progress authority.

## Monitoring and actions

Keep valid snapshots visible during refresh failures. Display actual cancellation refresh cadence. Preserve backend acknowledgement, capability gates, finite snapshot counts, and separate future eligibility. Prioritize task status, workload and actionable issues over immutable identifiers and optional cross-task analysis. Retain all existing configuration controls.

## Compatibility and rollback

No backend API or mutation changes. Existing Scheduler links remain valid. Route codec defaults tolerate unknown query values. Rollback consists of reverting frontend changes; no migration is needed.
