# Technical design

## Boundary

The defect belongs to CTGoodJobs page-state classification, before parsing and ingest. The parser and ingest validation remain strict: they should never receive the known expired-page representation.

## Classification flow

1. The browser fetch captures HTTP status, final URL, title, and HTML.
2. `classify_ctgoodjobs_detail_page` inspects HTTP 404/410 and explicit top-level state containers only.
3. Extend the explicit state-token vocabulary to recognize CTGoodJobs' owned `jd--expired` container.
4. Continue requiring a known unavailable message inside the captured state container. The class token alone enables capture; the marker establishes the terminal reason.
5. Raise `CTGoodJobsTerminalUnavailableError` before returning HTML to the caller.
6. The existing crawl loop marks the individual detail target `terminal_unavailable`, updates progress, and continues to the next target.

## Safety properties

- Do not scan arbitrary body text for expiration phrases.
- Do not infer expiration from missing parser fields or company identity.
- Do not fabricate company identity for terminal pages.
- Preserve existing reason `job_expired`, status code, and final URL evidence.
- Keep source-specific detection in the CTGoodJobs adapter; cross-source normalization is a separate task.

## Compatibility and rollback

This is an additive recognition rule inside the existing CTGoodJobs terminal-unavailable contract. Rollback is the removal of the new explicit state token and its fixture. No database migration or API schema change is required.
