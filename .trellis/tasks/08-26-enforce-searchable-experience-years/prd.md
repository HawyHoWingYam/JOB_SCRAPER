# Enforce searchable experience-year enrichment

## Goal

Make every AI-enriched Experience result coherent and usable by Job Browser's
year-based search. Explicit year requirements must never be lost, and inferred
seniority must not produce a level-only record that disappears from every
Experience search.

GitHub issue: [#61](https://github.com/HawyHoWingYam/JOB_SCRAPER/issues/61)

## Background

- The reported JobsDB Job `94140470`, “Sap Project Management Lead -
  Accenture”, persists `experience_level=lead_level` with both numeric bounds
  null. Its AI summary says that no minimum or maximum years were specified.
- Job Browser displays the level only because no numeric bound exists.
- An active year filter includes Jobs with explicit numeric bounds, plus the
  documented `not_specified + null bounds` virtual `[0, 1]` case. A non-
  `not_specified` level with null bounds matches neither branch and therefore
  disappears from every year-filtered search.
- The deterministic red-loop query currently finds 1,211 affected active,
  enriched Jobs out of 15,537 (7.79%), across JobsDB, CTgoodjobs, and
  OfferToday.
- At least 416 affected descriptions contain a strict explicit experience-year
  requirement. The current 3,200-character prompt context loses that evidence
  for 406 of those Jobs, including requirements such as `2+ years
  experience`, `Minimum 3 years`, and `Minimum 12 years`.
- The extractor prompt says that a posting without a specified experience
  requirement must return `not_specified` and null bounds, but normalization
  currently accepts another state: an inferred non-null level with both bounds
  null.

## Requirements

- Preserve explicit experience-year evidence from the full Job description in
  the extraction input, including HTML-formatted and long descriptions.
- Parse and persist explicit minimum/maximum year requirements as integer
  bounds without confusing contract duration or unrelated year mentions for
  experience.
- Define one invariant for the relationship among `experience_level`, numeric
  bounds, summary, and evidence; level-only records must not remain invisible
  to year-based search.
- When the employer states an experience-year requirement, treat that explicit
  requirement as authoritative. When no explicit year requirement exists but a
  reliable seniority level can be inferred, expose a documented level-derived
  estimated year window for search and presentation, with provenance that
  prevents it from being represented as employer-stated.
- When neither explicit years nor a reliable seniority level can be found,
  retain `not_specified` as the displayed data state but use the existing
  virtual `[0, 1]` interval for numeric search. This is a product fallback for
  recall, not an employer-stated or inferred requirement.
- Use one shared experience-window policy for enrichment normalization, Job
  detail presentation, lexical search, semantic/hybrid candidate filtering,
  facets, and CSV/API output.
- Preserve operator-authored experience bounds during AI enrichment and
  historical repair.
- Repair all existing affected active Jobs using their stored title and full
  description; the repair must be resumable, observable, and safe to retry.
- Report pre/post repair counts by source and disposition: explicit bounds,
  inferred bounds/window, genuinely unspecified, and failed/manual-review.
- Add regression coverage for long descriptions whose experience evidence is
  outside the current prompt prefix/tail, level-only model output, range
  overlap, UI labels, and historical repair idempotency.

## Constraints

- Do not present inferred years as an employer-stated requirement.
- Do not overwrite manual/operator-authored fields.
- Do not persist or display the `not_specified` search fallback as an explicit
  employer requirement or as an inferred entry-level classification.
- Existing explicit numeric search semantics remain inclusive interval overlap.
- The repair must not regenerate or overwrite unrelated AI Summary or Skill
  governance data unless explicitly required by the final design.

## Acceptance Criteria

- [ ] The red-loop count of active enriched Jobs with non-`not_specified`
  experience level and no searchable numeric/derived year window is zero.
- [ ] The reported JobsDB Job `94140470` has a truthful year-oriented display
  and participates in the expected Experience searches.
- [ ] All strict explicit year requirements detected in the full description
  are present in the extraction context or recovered deterministically before
  persistence.
- [ ] A regression fixture with experience evidence beyond the old 3,200-byte
  context boundary produces the correct numeric bounds.
- [ ] Job Browser results and facets apply the same experience-window policy
  for explicit, inferred, and unspecified Experience data.
- [ ] UI copy distinguishes employer-stated years from estimated years.
- [ ] Historical repair is idempotent, preserves operator-owned values, and
  publishes final affected/repaired/unresolved counts.
- [ ] Backend and frontend targeted tests, full relevant suites, lint, and type
  checks pass.

## Out of Scope

- Reclassifying Skills, Company Industry, or Source Classification.
- Rewriting unrelated AI summaries.
- Changing salary, location, employment-type, or posting-date search behavior.

## Confirmed Product Decision

- Explicit employer-stated years take precedence.
- If explicit years are absent but seniority is reliable, Job Browser uses a
  level-derived estimated year window.
- UI/API output must identify the estimated provenance; an inferred window may
  not be worded or exported as an employer requirement.
- If neither explicit years nor reliable seniority is found, retain the
  current `not_specified + null bounds` representation and its virtual `[0, 1]`
  search interval. The UI continues to say that experience was not specified;
  it must not claim that the employer requires 0–1 years.

## Notes

- Keep `prd.md` focused on requirements, constraints, and acceptance criteria.
- Lightweight tasks can remain PRD-only.
- For complex tasks, add `design.md` for technical design and `implement.md` for execution planning before `task.py start`.
