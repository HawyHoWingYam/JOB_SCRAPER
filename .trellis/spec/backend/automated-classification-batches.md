# Skill Candidate Review Contracts

## Scenario: Review repeated Skill evidence

### 1. Scope / Trigger

Use this contract when changing the Skill Candidate review queue, its Settings,
operator decisions, recommendations, or evidence shown to the operator.
Company Industry and automated classification batch controls are removed.

### 2. Signatures

```text
GET  /api/job-intelligence/skill-candidates?ready_only=true&limit=1..500&offset=0
POST /api/job-intelligence/skill-candidates/{candidate_id}/decision
GET  /api/job-intelligence/skills/tree
PUT  /api/settings/ai
```

`SkillCandidateDecisionRequest` accepts `match_existing`, `create`, `generic`,
or `reject`. `create` requires an existing active Category/Technology pair;
`generic` and `reject` require structured reasons.

### 3. Contracts

- Candidate selection uses persisted `skill_auto_create_distinct_job_threshold`;
  effective default is `10`.
- Candidate responses include `total_count`, `offset`, and `limit`; the UI uses
  bounded pages rather than requiring the operator to scroll an unbounded
  review list.
- Response includes `recommendations` (bounded by
  `skill_candidate_recommendation_limit`, default `5`) and `evidence` (bounded
  by `skill_candidate_evidence_limit`, default `5`).
- Recommendations are deterministic hints only. They never mutate taxonomy
  state until an operator submits a decision.
- Evidence is representative active Candidate Mention Job data and is not a
  governed Skill assignment or searchable Skill filter.
- New Skills can only be leaves under an existing Category → Technology.
  Candidate raw variants become aliases only when explicitly selected by the
  operator.
- Existing Skill and Technology choices are searchable, bounded option lists;
  they must not render a very long native select as the primary interaction.
- Settings bounds are `1..20` for recommendation and evidence counts.
- Operator decisions resolve Mentions, Candidate state, and affected Job Skill
  projections atomically and are idempotent for an already-resolved Candidate.

### 4. Validation & Error Matrix

| Condition | Required result |
|---|---|
| Candidate below threshold | Exclude from `ready_only=true` |
| Unknown existing Skill code | `400`; no mutation |
| Category/Technology missing, inactive, or unrelated | `400`; no mutation |
| New Skill stable code conflicts | `400`; no mutation |
| generic/reject reason missing or invalid | `400`; no mutation |
| Settings count outside `1..20` | `422`; preserve previous values |
| Taxonomy unavailable | UI shows blocked readiness state; no confirmation |

### 5. Good / Base / Bad Cases

- **Good:** operator clicks a high-confidence recommendation, confirms, and the
  Candidate disappears while affected Jobs gain the governed Skill.
- **Good:** operator creates a Skill under an existing Technology and selects
  only the variants that are true aliases.
- **Base:** no recommendation is strong enough; the operator searches the full
  Skill list or chooses generic/reject with a reason.
- **Bad:** auto-submit a recommendation, create a parent node, or expose
  Candidate evidence as a canonical Skill filter.

### 6. Tests Required

- Backend: threshold filtering, bounded recommendations/evidence, invalid
  codes, parent validation, structured reasons, idempotency, and atomic
  reprojection.
- Frontend: compact paged list/panel, scrollable evidence/actions, searchable
  Skill/Technology pickers, keyboard navigation, auto-next, skip,
  alias checkboxes, structured reason validation, taxonomy-unavailable state,
  and Settings field rendering.

### 7. Wrong vs Correct

#### Wrong

```js
onCandidateLoaded(candidate).then(() => decideSkillCandidate(candidate.id, {
  action: "match_existing",
  skill_code: candidate.recommendations[0].code,
}));
```

#### Correct

```js
operatorClickRecommendation(candidate.recommendations[0]);
submitDecisionOnlyAfterExplicitConfirmation();
```

## Independent maintenance availability

Candidate/Skill-tree reads and maintenance-status reads have separate failure
boundaries in `ClassificationBatchesPage`. A maintenance outage must not hide
successfully loaded Candidates or their evidence. Show a maintenance-local
message, disable maintenance dispatch when eligibility is unavailable, and
never turn missing status into a claim that maintenance is disabled in Settings.
Aborted requests may not update state after a route/page change. The component
regression test rejects maintenance while asserting evidence remains visible.
