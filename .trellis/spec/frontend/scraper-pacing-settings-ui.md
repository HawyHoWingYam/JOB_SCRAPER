# Scraper Pacing Settings UI Contract

## Scenario: Source-owned Job Detail pacing editors

### 1. Scope / Trigger

Use this contract when displaying or editing the global manual Job Detail pacing
for JobsDB, CTGoodJobs, and OfferToday. It does not control listing or scheduled
crawls and never edits the pacing snapshot, frozen membership, or complete-run
cap of an existing task.

### 2. Signatures

```http
GET  /api/settings/scraper-pacing
PUT  /api/settings/scraper-pacing/{source_site}
POST /api/settings/scraper-pacing/{source_site}/reset
```

```jsx
<ScraperPacingSettings onOpenCrawlTasks={() => void} />
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
- Saved pacing is read only when preparing a future Dispatch Plan. Save/Reset
  cannot mutate a prepared or consumed plan, expand its frozen detail
  membership, or change its reviewed `detail_run_cap`.
- `burst_size` is an execution pacing partition. It is never a detail target
  limit, Recovery Segment continuation authority, or complete-run cap.

### 4. Validation & Error Matrix

| Condition | UI result |
|---|---|
| minimum or maximum outside 0.1-60 | field error; Save disabled |
| minimum greater than maximum | maximum field error; Save disabled |
| burst size not an integer in 1-1000 | field error; Save disabled |
| burst pause outside 0-3600 | field error; Save disabled |
| unchanged card | Save disabled |
| settings change while a detail plan is active | save for future plans; active snapshot/membership/cap remain unchanged |
| burst size differs from a plan run cap | show each in its own context; never treat burst size as the cap |
| backend 422 | render formatted backend detail in that card's alert |
| GET failure | render page-level alert; do not invent defaults |

### 5. Good / Base / Bad Cases

- **Good:** CTGoodJobs is edited and saved; only its server/form state is
  rebuilt from the PUT response while JobsDB and OfferToday stay unchanged.
- **Base:** Two detail tasks are active; the count and new-task-only warning are
  shown, but every valid card can still be saved.
- **Base:** Changing burst size from 20 to 50 affects a subsequently prepared
  plan only; an active 500-target plan keeps its frozen pacing and run cap.
- **Bad:** A Save updates an active task or uses `burst_size` to enlarge its
  frozen target membership.

### 6. Tests Required

- Settings navigation preserves the existing AI Runtime screen.
- Card tests cover independent state, Save/Reset response adoption, local
  validation, backend 422 alerts, active count, future-plan-only wording, and
  Crawl Tasks navigation.
- Backend/frontend integration assertions keep prepared/active plan pacing,
  frozen membership, and `detail_run_cap` unchanged after settings mutation.
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

// Existing task cards continue rendering task.detail_pacing and
// task.detail_snapshot; they never read this newly saved settings response.
```

The server response is the saved source of truth for future preparation and
state ownership remains isolated by source. Existing plans retain their own
immutable snapshots.

## Settings navigation and unsaved state

- `#settings?section=ai-runtime|scraper-pacing` restores the selected section on reload/history navigation. Visited sections stay mounted while on Settings; switching sections preserves drafts in memory only.
- Both editors warn before document unload when dirty. Credentials are never copied into local/session storage. Leaving the Settings page is explicitly described as requiring Save first.
- AI Runtime displays its saved-versus-draft state, supports discard to the server baseline, retains drafts on failed saves and offers initial-load retry. Feedback receives keyboard focus; major runtime sections have focusable navigation targets with all controls still visible.
- Profile tests explicitly describe contacting the provider with draft values; testing and saving remain separate.
- Scraper Pacing offers per-source discard and load retry. Reset asks for confirmation when unsaved changes would be overwritten; the returned server snapshot still owns the saved result.
- AI troubleshooting links may carry validated `profile=jobs|companies|throughput`, `return=ai` and a bounded `returnRun`. Return links are constructed locally as AI routes; never accept arbitrary return URLs.
