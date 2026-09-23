# Improve Settings page and configuration workflow UX

## Goal

Improve Settings and its downstream configuration workflows as the fourth deliverable in the active operations UX goal. Explicitly added and authorized by the user on 2026-09-23.

## Requirements

- Make configuration sections, current values, editable values, save state, validation and operational effects understandable.
- Keep configuration controls directly accessible; preserve the dark theme and plain English interface.
- Distinguish saved configuration, runtime readiness, free validation and explicit paid/provider actions.
- Preserve existing API contracts, credential handling, configuration authority and future-run versus active-run semantics.
- Provide clear recovery from loading/save/validation failures and preserve unsaved inputs where safe.
- Make AI Enrichment-to-Settings troubleshooting and return paths understandable.

## Acceptance criteria

- [x] Audit rendered Settings and existing workflows; persist concrete design and implementation plan before implementation.
- [x] Configuration editing, save success/failure, validation and retry paths have accurate accessible feedback.
- [x] Existing settings remain reachable at laptop and narrow widths with keyboard navigation.
- [x] Focused regressions, full frontend checks and isolated browser workflows pass; no live crawl or paid AI is required for verification.
- [x] Cross-page operational acceptance is recorded under parent #74.

## Scope and sequencing

Follow Crawl Tasks #76 and AI Enrichment #77. Main agent implements and verifies. Backend/provider redesign, destructive data operations and unrelated product features are excluded. GitHub closure requires explicit manual QA success.

Parent: https://github.com/HawyHoWingYam/JOB_SCRAPER/issues/74
