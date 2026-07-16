# Design scraper pacing settings UI

## Goal

Give the operator a clear, safe Settings experience for independent JobsDB,
CTGoodJobs, and OfferToday Job Detail pacing without duplicating controls in
Direct Override.

## Requirements

- Reorganize the Settings destination into `AI Runtime` and `Scraper Pacing`
  sections with clear navigation/hierarchy.
- Scraper Pacing shows three parallel source cards with interval min/max, burst
  size, and burst pause controls.
- Display units and safety ranges next to every control.
- Each card owns independent local state, dirty/saved/saving/error feedback,
  Save, and Reset to defaults. Saving/resetting one source must not alter another.
- Use server responses as the saved/effective source of truth after writes.
- Frontend validation gives immediate feedback; backend validation remains
  authoritative and 422 details are visible.
- Saving is allowed while detail tasks are active. Show active detail-task count,
  warn that edits affect only newly started tasks, and provide Open Crawl Tasks.
- Direct Override shows only the selected source's saved pacing summary and a
  Settings link. It has no editable pacing controls.
- Show the approved defaults and do not introduce a countdown or runtime attempt
  counters.

## Acceptance Criteria

- [ ] Settings sections are navigable and preserve existing AI Runtime behavior.
- [ ] Three cards render correct values, ranges, units, defaults, and independent
      save/reset/dirty/error states.
- [ ] Invalid local values block save with accessible feedback; backend 422
      feedback is also rendered.
- [ ] Active detail count/warning/link are accurate and do not block save.
- [ ] Direct Override renders a read-only source summary/link and no duplicate
      pacing inputs.
- [ ] Focused interaction/accessibility tests and full frontend build pass.

## Dependencies

- Depends on the pacing settings API and active-detail task query contract.
- Does not depend on Crawl Tasks pacing-card rendering.
