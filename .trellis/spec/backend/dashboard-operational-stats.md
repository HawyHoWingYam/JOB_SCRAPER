# Dashboard Operational Statistics Contracts

## Scenario: Render retained-corpus taxonomy and Skill health

### 1. Scope / Trigger

Use this contract when changing `/api/stats/overview`,
`/api/stats/categories/dashboard`, `/api/stats/skills`, or the Dashboard cards
that consume them. The Dashboard is an internal operations surface over all
non-deleted acquired Jobs. It is not an active-listing or labor-market view;
expired source listings remain in the population.

Classification navigation and Jobs drill-down routes are separate consumers of
the stable codes and action-ready counts. This contract does not authorize a
batch start or define those routes.

### 2. Signatures

```text
GET /api/stats/overview
GET /api/stats/categories/dashboard
GET /api/stats/skills?limit=<1..100>&category=<optional exact label>
#jobs?canonical_subcategory_ids=<stable-code>
#jobs?skill_ids=<stable-code>
```

```python
_dashboard_job_population_predicate() -> ColumnElement[bool]
_accepted_job_taxonomy_assignment_job_ids(db: Session) -> Query
get_dashboard_category_stats(db: Session) -> DashboardCategoryStatsSchema
get_skill_stats(limit: int, category: str | None, db: Session) \
    -> DashboardSkillStatsSchema
```

The page boundary owns one Refresh coordinator. Each section keeps
`data`, `loading`, `error`, `lastUpdated`, and one abort controller.

```js
parseJobsRoute(hash) -> { canonicalSubcategoryIds, skillIds }
hashForJobsRoute({ canonicalSubcategoryIds, skillIds }) -> string
```

### 3. Contracts

- Overview `total_jobs`, taxonomy `population_total`, and all acquired-Job
  filters use `Job.is_deleted IS FALSE`. “Current” describes ordinary current
  canonical state, not listing activity.
- A Job contributes to taxonomy `assigned_total` only when its current Job
  assignment points to an active, assignable leaf under active Category and
  Domain ancestors. `unassigned_total = population_total - assigned_total`.
- `classification_ready_unassigned_total` applies the same accepted-assignment
  definition and additionally requires `Job.source_attribute_projection`.
  Merely having an assignment row to an inactive or unassignable node must not
  remove a Job from this readiness cohort.
- Taxonomy returns six concrete rows in `top_categories`. `other_categories`
  contains the summed count and every remaining concrete row. Concrete rows
  have stable `code`, visible `path`, `label`, `count`, and
  `share_of_assigned`; `Other` has no taxonomy identity.
- Skill `processed_total` is the count of non-deleted Jobs with
  `ai_enriched_at`; pending enrichment is outside the denominator.
  `matched_job_total` counts distinct Jobs in that cohort with at least one
  current assignment to an active, assignable Skill whose ancestors are
  active. Per-row `count` is distinct Jobs and `prevalence` uses
  `processed_total`. Multi-Skill prevalence values are independent and do not
  sum to 100%.
- The Skill leaderboard contains current canonical assignments only. Active
  Candidate Mentions are reported separately as distinct Candidate IDs,
  distinct affected Job IDs, and distinct Candidates meeting the threshold
  returned by `AIRuntimeSettingsService`.
- Skill rows are globally ordered by count descending then stable code
  ascending before applying `limit`. `dashboard_bucket` is backend-owned.
  Frontend grouping preserves response membership and relative order, keeps
  preferred known buckets first, and appends non-empty unknown buckets.
- The UI distinguishes returned from currently visible Skill rows. Per-bucket
  overflow and taxonomy `Other` use buttons with `aria-expanded`; full values
  and paths have accessible names and remain readable on narrow screens.
- Refresh is manual and page-owned; there is no polling. Sections commit
  independently. A failed refresh retains previous data only with an alert,
  stale label, unchanged last-successful timestamp, and retry action. An
  in-flight section with retained data remains visibly labelled refreshing.
- Every concrete taxonomy and Skill row is a semantic Jobs drill-down action.
  Navigation serializes only stable `code` values through the shared Jobs hash
  route. Labels, breadcrumbs, counts, and `dashboard_bucket` never select Jobs.
- The durable Jobs route accepts repeated `canonical_subcategory_ids` and
  `skill_ids` query keys. It trims, validates, de-duplicates, and bounds stable
  codes before `JobBrowser` creates one ordinary root search layer. Bare
  `#jobs` remains the unfiltered route; same-view hash changes rehydrate the
  scope for refresh and browser back/forward navigation.
- The taxonomy `Other` aggregate has no route identity and remains an expansion
  control. Its expanded concrete rows use their own stable codes.

### 4. Validation & Error Matrix

| Condition | Required result |
|---|---|
| Skill `limit` is below 1 or above 100 | HTTP 422; do not clamp silently |
| Population or processed denominator is zero | Coverage and prevalence are `0`; return valid empty summaries |
| Job is deleted | Exclude it from population, assignments, matches, and Candidate backlog |
| Assignment leaf or ancestor is inactive/unassignable | Treat the Job as unassigned for both coverage and readiness |
| Skill bucket is unknown to the frontend | Append the non-empty bucket after preferred buckets; do not crash or remap it |
| Initial section request fails | Show unavailable alert and section retry; render no fabricated data |
| Refresh fails after prior success | Keep data, mark it stale, show its prior timestamp, and keep other successful updates |
| Component unmounts or a newer request supersedes a request | Abort the old request and do not update state from it |
| Jobs route value is blank, malformed, or longer than the stable-code bound | Drop that value; never resolve it from a label |
| Jobs route contains duplicate stable codes | Preserve the first occurrence only |
| Hash is bare `#jobs` or all route values are invalid | Load the ordinary unfiltered Jobs scope |
| JobBrowser route hash changes while Jobs view remains mounted | Abort/supersede the old search and fetch the reconstructed scope |

### 5. Good / Base / Bad Cases

- **Good:** a non-deleted enriched Job with Python and SQL assignments counts
  once in matched Jobs and once in each Skill row; its two prevalence values
  are not presented as shares of one pie.
- **Good:** a ready Job whose stale assignment points to an inactive node is
  unassigned and classification-ready under the same accepted-assignment rule.
- **Base:** no accepted taxonomy or Skill assignments returns coverage cards
  with zero values and an accessible empty distribution.
- **Base:** `Support & Operations` arrives as a new Skill bucket and renders
  after the preferred buckets without frontend enum changes.
- **Good:** selecting Python writes `#jobs?skill_ids=<python-code>` and the Job
  search body contains the same code in `structured_filters.skill_ids`.
- **Base:** sharing or refreshing a canonical Subcategory route reconstructs
  the same root scope; direct `#jobs` still loads all Jobs.
- **Bad:** filter expired Jobs, divide Skill matches by all acquired Jobs,
  include Candidates in the canonical leaderboard, or treat any assignment row
  as accepted.
- **Bad:** blank all cards when only Skills fail, show retained data as fresh,
  or label hidden rows as shown.
- **Bad:** route by Skill name, taxonomy breadcrumb, Dashboard bucket, or one
  synthetic `Other` value.

### 6. Tests Required

- Backend stats tests assert deleted filtering, overview/taxonomy population
  equivalence, active/assignable hierarchy eligibility, invalid-assignment
  readiness, deterministic ties, limit validation, top-six/Other math, empty
  data, enriched Skill denominators, distinct Job counts, and Candidate
  threshold semantics.
- Chart tests assert accessible loading/empty/error/value names, visible versus
  returned counts, response-order preservation, dynamic buckets, keyboard
  expansion/collapse, full taxonomy paths, and retained-data refresh status.
- Dashboard tests assert four real response shapes, unified Refresh, request
  abort cleanup, partial stale retention, section retry, and independent
  successful updates.
- Route tests assert bare Jobs compatibility, stable-code round-trip,
  de-duplication, malformed-value fallback, deterministic serialization, and
  top-level view resolution with a query string.
- JobBrowser tests assert route hydration into `canonical_subcategory_ids` and
  `skill_ids`, same-view route changes, and unchanged manual FilterPanel scope
  submission. Chart tests assert pointer/keyboard activation and accessible
  action names containing destination and Job count; `Other` itself is not a
  Jobs drill-down.
- Before completion run focused backend stats/current-taxonomy contracts, the
  full frontend suite, ESLint, production build, backend lint/format checks,
  and browser QA at desktop and narrow viewports.

### 7. Wrong vs Correct

#### Wrong: readiness rejects every Job with an assignment row

```python
query.outerjoin(CurrentJobTaxonomyAssignment).filter(
    CurrentJobTaxonomyAssignment.job_id.is_(None),
    Job.source_attribute_projection.has(),
)
```

#### Correct: readiness rejects only Jobs with an accepted assignment

```python
accepted = _accepted_job_taxonomy_assignment_job_ids(db).subquery()
query.outerjoin(accepted, accepted.c.job_id == Job.id).filter(
    accepted.c.job_id.is_(None),
    Job.source_attribute_projection.has(),
)
```

The second form keeps assignment coverage and classification readiness on the
same canonical-acceptance boundary.

#### Wrong: re-rank a backend Top-N inside presentation buckets

```js
grouped.get(bucket).push(skill);
grouped.get(bucket).sort(localComparator);
```

#### Correct: preserve each bucket's response-order subsequence

```js
if (!grouped.has(bucket)) grouped.set(bucket, []);
grouped.get(bucket).push(skill);
```

Grouping is for scanning; the backend remains ranking authority.

#### Wrong: route from a presentation label

```js
window.location.hash = `#jobs?skill=${encodeURIComponent(skill.name)}`;
```

#### Correct: serialize the stable code through the shared route owner

```js
window.location.hash = hashForJobsRoute({ skillIds: [skill.code] });
```

The parser seeds the existing structured Job search filter; components do not
privately interpret route strings or translate labels back into identities.
