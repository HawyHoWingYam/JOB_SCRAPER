# Dashboard Operational Statistics Contracts

## Scenario: Monitor retained corpus and governed Skill health

### 1. Scope / Trigger

Use this contract when changing Dashboard overview, AI telemetry, Skill stats,
chart drill-down, refresh isolation, or accessibility. The
Dashboard has no Job-category distribution or Job-classification readiness.

### 2. Signatures

```text
GET /api/stats/overview
GET /api/ai/overview
GET /api/stats/skills?limit=<1..100>&category=<optional>
```

```js
onSelectSkill(skill) -> #jobs?skill_ids=<stable-code>
```

### 3. Contracts

- Overview counts the non-deleted retained corpus and separates AI-eligible,
  enriched, pending, ineligible, active-run, and failure signals.
- Skill denominators are successfully enriched Jobs, not all acquired Jobs.
- Skill rows use governed assignments only and preserve backend response order.
- Dashboard loads overview, AI overview, and Skills independently. Refresh
  aborts superseded requests, retains prior successful data on partial failure,
  and marks only the failed section stale.
- Skill drill-down serializes stable Skill codes through the shared Jobs route.

### 4. Validation & Error Matrix

| Condition | Required result |
|---|---|
| Skill limit outside API bound | `422` |
| No enriched Jobs | Return truthful zero/N/A denominators |
| Initial section request fails | Section unavailable alert and retry |
| Refresh fails after prior success | Retain data, mark stale, show last timestamp |
| Request is superseded/unmounted | Abort; ignore late result |
| Unknown frontend bucket | Append without remapping or crashing |

### 5. Good / Base / Bad Cases

- **Good:** Python counts distinct enriched Jobs and drills into
  `#jobs?skill_ids=python`.
- **Base:** Skills fail to refresh while overview remains current and old Skill
  data is visibly stale.
- **Bad:** include Candidate Mentions in the governed Skill leaderboard.
- **Bad:** restore a removed Job-category chart or classification target.

### 6. Tests Required

- Backend stats tests cover enriched denominators, distinct Job counts,
  deterministic ordering, and bounds.
- Skill chart tests cover loading/empty/error/stale states, accessible action
  names, dynamic buckets, and governed rows.
- Dashboard tests assert exactly three independent endpoints, unified Refresh,
  stale retention, request cleanup, and Skill drill-down.
- Route tests cover stable Skill codes.

### 7. Wrong vs Correct

#### Wrong

```js
fetch('/stats/categories/dashboard')
```

#### Correct

```js
fetch('/stats/skills?limit=30')
```

Operational classification health is Company/Skill oriented; Job categories
remain Source-owned evidence outside the Dashboard.
