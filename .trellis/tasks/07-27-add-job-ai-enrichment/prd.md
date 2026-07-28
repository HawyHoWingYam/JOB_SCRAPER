# Redesign Add Job with AI enrichment and flexible companies

## Goal

Make manual Job creation a reliable intake path into the same downstream intelligence workflows as collected Jobs. The operator authors the Job and identifies an existing or new Company; AI work remains explicitly triggered later through the existing Job AI Enrichment and Companies batch pages.

## Confirmed Current State

- Add Job already accepts an operator-authored title, searches existing Companies, and can create a Company inline, but it persists the Company before the Job.
- `POST /api/jobs/manual` currently couples persistence to a dedicated enrichment run, waits for terminal completion, and returns an enrichment-oriented result.
- Manual Jobs lack the Source Attribute Projection required by unified Job batch selection and by the enrichment implementation itself. Source projection constraints correctly admit only JobsDB, CTgoodjobs, and OfferToday.
- Manual Companies with blank descriptions already satisfy the global Company-description eligibility query, but Company batching is independently operated from the Companies page.
- Company create input currently accepts derived `ai_description`; Company storage lacks website and description scheduling time.
- Manual Job input currently mixes free-text and structured salary, while Job read schemas omit structured salary fields.
- Manual experience values can currently be overwritten by enrichment, and there is no post-create Job editing path or intelligence-freshness state.
- Manual creation has no duplicate-decision or request-idempotency contract. Company source identity also inherits defaults that do not describe Manual Entry correctly.
- The audited `Company.extra_data` and `Job.search_vector` columns have no active read consumers. `extra_data` still has repository/backfill writers that must be removed with the column.
- The project has no in-place migration chain. Current-schema changes are deployed through stopped-service export, destructive sandbox rebuild, import, and exact verification.

## Requirements

### Manual Job intake

- Require an operator-authored Job title and Company choice. Allow description to be blank for persistence while labelling it `Optional for saving · Required for AI enrichment`.
- Support either selecting an existing Company or holding a New Company draft containing name plus optional website, location, and free-text Company Industry evidence.
- Keep the New Company draft unpersisted until final Job submission. Create the Company, Job, governed Employment Type assignments, Manual evidence, and idempotency result atomically.
- Treat Company name matches as possible duplicates, not identity equality. Show candidates and require an explicit decision to reuse an existing Company or create a distinct one; never silently merge or name-upsert.
- Warn about likely Job duplicates using Company, normalized title, location, and posted date. Allow explicit creation because repeated titles can be distinct openings.
- Make one logical submission idempotent. Same key and same command replays the first result; same key with a different command conflicts; transport retry cannot create another Company or Job.
- Accept structured salary minimum, maximum, and currency only. Do not expose legacy `salary_range` or legacy `employment_type` in Manual Job input; use governed Employment Type codes.
- Validate trimmed required strings, normalized website, supported currency, non-negative values, and minimum-not-greater-than-maximum ranges at the command boundary.
- Structure the form around title, Company, and description. Put structured salary, location, Employment Types, posted date, and experience under collapsed `Optional job details`.
- Label the primary action `Add Job`. Add Job reports persistence only, starts no AI request, contains no per-record AI controls, and makes no enrichment-success claim.

### Manual Job editing and authority

- Allow Job Detail to edit the same operator-authored fields for Manual Jobs only. Collected Source Jobs and AI-derived fields remain read-only.
- Reuse the Manual intake validation, Company choice/draft, duplicate-decision, governed Employment Type, and provenance rules for edits.
- Treat every explicitly supplied Manual Job value as an Operator-Authored Job Fact. Enrichment must not silently overwrite title, Company, description, location, salary, Employment Types, or operator-authored experience.
- AI may generate summary, Canonical Taxonomy Assignment, and Skill data. It may fill omitted experience values; conflicting extraction remains evidence rather than replacing operator facts.
- When an enrichment-relevant operator fact changes, mark existing Job Intelligence stale and make the Job eligible for a later batch. Keep old intelligence visibly stale until successful atomic replacement; failure preserves old intelligence and stale status.

### Job AI Enrichment batch

- Keep Job enrichment on the existing Job AI Enrichment page and Company-description generation on the existing Companies page. They remain independent batches.
- Include supported Manual Jobs in the same persisted Job run lifecycle, pending counts, preview, monitor, Stop, and failed-item retry behavior as collected Jobs.
- Rename the displayed Job filter dimension from `Source` to `Origin`, with JobsDB, CTgoodjobs, OfferToday, and Manual Entry. Manual Entry is an origin, not a fourth external Source.
- Keep Source Attribute Projections and Source Taxonomy identities exclusive to external Sources. Provide explicit Manual evidence to the shared enrichment seam rather than fabricating Source paths or weakening Source constraints.
- Require a non-blank description for Manual Job enrichment. Save blank-description Jobs, count/report them as `Needs job description`, and make them pending after a description is added.
- Use the same origin-aware evidence/eligibility inspection for overview, filter options, preview, run creation, and worker preflight so Manual Jobs cannot appear runnable and then fail for missing Source attributes.
- When Manual Entry alone is selected, expose no Source Classification/Subclassification cascade and never broaden an empty Manual scope into all pending Jobs.

### Company-description batches

- Keep Company-description generation on the Companies page. Companies created through Manual intake follow the same eligibility rules as all other Companies.
- Provide two explicit modes:
  - Generate selects Companies with blank descriptions.
  - Regenerate selects Companies with existing descriptions and requires confirmation.
- Let the operator enter a positive Company Enrichment Run Limit with no product-level fixed maximum. Freeze `min(requested, eligible)` records; runtime concurrency remains independently bounded.
- Generate selects oldest Companies first by creation time and stable ID. Regenerate selects null/oldest `ai_description_updated_at` first and then stable ID.
- Persist run mode, requested limit, frozen item identities, and Web Search intent. Failed-item retry preserves the original item identities and mode.
- On successful Generate or Regenerate, update `ai_description` and `ai_description_updated_at` atomically. A failed Regenerate preserves the previous description and timestamp.
- Keep Company Web Search explicit, default-off, capability-gated, and separate from Job enrichment.

### Schema and product contracts

- Add nullable normalized `Company.website` as identity/enrichment evidence and nullable `Company.ai_description_updated_at` as scheduling state.
- Split Company create input from read output. Ordinary Company creation and Manual Job intake must not accept `ai_description`; only Company enrichment writes it.
- Remove `Company.extra_data`, `Job.search_vector`, and all remaining read/write references. Do not remove other compatibility fields or retired schemas in this task.
- Preserve `salary_range`, legacy `employment_type`, source classification scalars, `job_id`, and `company_id` where existing collected-source/read compatibility still depends on them.
- Align composed Job reads with structured salary, Job Origin, Manual editability, enrichment eligibility, operator authority, and current/stale intelligence.
- Update current-schema bootstrap and sandbox retained-data export/import/verification for new retained data and removed columns. Do not introduce Alembic or in-place upgrade behavior.
- Maintain an evidence-backed schema classification in `design.md` covering authoritative, derived/projection, compatibility-only, missing-needed, and removed fields.

## Acceptance Criteria

### Intake and editing

- [ ] The operator can add a Job with an existing Company or a non-persisted New Company draft.
- [ ] New Company + Job submission commits both records and related governed/manual evidence or commits none.
- [ ] New Company accepts optional validated website, location, and Company Industry evidence without treating free text as a governed assignment.
- [ ] Same/similar Company and likely Job duplicates require an explicit identity/creation decision and never silently merge.
- [ ] Idempotent replay returns the first result; key/hash conflict is explicit; concurrent/transport retry creates one result.
- [ ] Add Job submits structured salary and governed Employment Type codes only, validates numeric ranges, and returns structured values in the composed result.
- [ ] The initial form emphasizes title, Company, and description; optional details remain accessible in one collapsed section.
- [ ] Add Job starts no enrichment request and contains no automatic-enrichment label, summary, or control.
- [ ] Job Detail can edit operator-authored fields on Manual Jobs and rejects the same operation for collected Source Jobs.

### Job intelligence

- [ ] Supported Manual Jobs appear under `Origin → Manual Entry` in pending counts, preview, and created runs without any fabricated Source Classification Path.
- [ ] A blank-description Manual Job is saved, reported as `Needs job description`, and excluded from pending work until edited.
- [ ] Preview, run creation, and worker preflight agree on every Manual Job's eligibility and stable reason.
- [ ] Manual enrichment preserves every operator-authored field and may fill only omitted experience values.
- [ ] Editing enrichment-relevant facts marks prior intelligence visibly stale and pending; successful enrichment replaces it and clears stale atomically, while failure preserves stale data.
- [ ] Existing JobsDB, CTgoodjobs, and OfferToday Source projection, taxonomy preflight, filtering, run, Stop, exclusion, and retry contracts remain valid.

### Company enrichment

- [ ] The Companies page starts separate Generate and confirmed Regenerate runs with a positive operator-entered Run Limit and no product-level fixed maximum.
- [ ] Each run freezes at most the requested eligible count in the documented deterministic order and persists mode, limit, items, and Web Search intent.
- [ ] Successful generation updates description and scheduling timestamp together; failed regeneration changes neither previous value.
- [ ] Retrying failed Company items preserves the original frozen identities and mode.
- [ ] Manual Companies need no Add Job-specific enrichment action and participate through ordinary Companies-page eligibility.

### Schema, safety, and verification

- [ ] Ordinary Company-create contracts reject/exclude `ai_description`; response and enrichment contracts continue to expose/write it appropriately.
- [ ] `Company.extra_data` and `Job.search_vector` are absent from current metadata/bootstrap and from all application reads/writes.
- [ ] Company website, Manual evidence/freshness, idempotency results, structured reads, and description scheduling state survive exact sandbox export/import verification.
- [ ] Backend contract/integration tests, frontend focused/full tests, lint, build, fixture equality, and disposable PostgreSQL sandbox rehearsal pass as defined in `implement.md`.

## Out of Scope

- Combining the Job AI Enrichment and Companies pages.
- Per-record AI actions on Add Job or Job Detail.
- Treating Manual Entry as an external Source or admitting it into Source Taxonomy projections.
- Removing compatibility fields other than `Company.extra_data` and `Job.search_vector`.
- Company-description model/provider provenance, prompt hashes, Web Search source URLs, or other generation evidence beyond `ai_description_updated_at` scheduling state.
- An in-place database migration, downgrade, mixed-version deployment, or shared-sandbox rebuild without the documented operator cutover.
