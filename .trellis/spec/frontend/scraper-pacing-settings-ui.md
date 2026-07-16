# Scraper Pacing Settings UI Contract

## Scenario: Source-owned Job Detail pacing editors

### 1. Scope / Trigger

Use this contract when displaying or editing the global manual Job Detail pacing
for JobsDB, CTGoodJobs, and OfferToday. It does not control listing or scheduled
crawls and never edits the pacing snapshot of an existing task.

### 2. Signatures

```http
GET  /api/v1/settings/scraper-pacing
PUT  /api/v1/settings/scraper-pacing/{source_site}
POST /api/v1/settings/scraper-pacing/{source_site}/reset
```

```jsx
<ScraperPacingSettings onOpenCrawlTasks={() => void} />
<ScraperPacingSummary
  sourceSite="jobsdb|ctgoodjobs|offertoday"
  settings={savedSettings}
  onOpenSettings={() => void}
/>
```

### 3. Contracts

- `GET` returns `items` and `active_detail_task_count`. Cards are keyed by
  `source_site`; never use array position as source identity.
- Each card owns its server snapshot, editable strings, pending action, dirty
  derivation, validation, and feedback. A Save or Reset response replaces both
  the saved snapshot and form values for only that source.
- Fields are `interval_min_seconds`, `interval_max_seconds`, `burst_size`, and
  `burst_pause_seconds`. The shared API helper owns URLs and summary formatting.
- Active tasks do not disable Save. The warning states that edits affect new
  tasks only and links to Crawl Tasks.
- Direct Override fetches the same saved settings and renders the selected
  source only. It contains no pacing inputs and does not add pacing fields to
  the crawl-dispatch payload.

### 4. Validation & Error Matrix

| Condition | UI result |
|---|---|
| minimum or maximum outside 0.1-60 | field error; Save disabled |
| minimum greater than maximum | maximum field error; Save disabled |
| burst size not an integer in 1-1000 | field error; Save disabled |
| burst pause outside 0-3600 | field error; Save disabled |
| unchanged card | Save disabled |
| backend 422 | render formatted backend detail in that card's alert |
| GET failure | render page-level alert; do not invent defaults |
| Direct Override GET failure | render unavailable summary plus Settings link |

### 5. Good / Base / Bad Cases

- **Good:** CTGoodJobs is edited and saved; only its server/form state is
  rebuilt from the PUT response while JobsDB and OfferToday stay unchanged.
- **Base:** Two detail tasks are active; the count and new-task-only warning are
  shown, but every valid card can still be saved.
- **Bad:** Direct Override duplicates the four inputs and lets its local values
  drift from the server-owned Settings page.

### 6. Tests Required

- Settings navigation preserves the existing AI Runtime screen.
- Card tests cover independent state, Save/Reset response adoption, local
  validation, backend 422 alerts, active count, and Crawl Tasks navigation.
- Direct Override summary tests assert exact selected-source values, no
  spinbuttons, and the Settings navigation action.
- Run the full frontend test suite and production build.

### 7. Wrong vs Correct

#### Wrong

```jsx
const [pacing, setPacing] = useState(DEFAULTS);
await save(source, pacing);
setSaved(pacing);
```

This guesses defaults and treats the submitted body as authoritative even when
the backend normalizes or rejects it.

#### Correct

```jsx
const response = await saveScraperPacingSettings(source, requestValues);
setCards((current) => ({
  ...current,
  [source]: createCardState(response),
}));
```

The server response is the saved/effective source of truth and state ownership
remains isolated by source.
