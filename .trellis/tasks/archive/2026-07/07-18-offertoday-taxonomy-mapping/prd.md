# Fix OfferToday taxonomy mapping coverage

## Goal

Prevent valid OfferToday jobs from failing AI enrichment before the LLM call because their source classification is missing from the source-to-internal taxonomy mapping. Make unsupported future source classifications visible before a run starts instead of allowing them to fail item by item.

## Background and confirmed facts

- The authoritative OfferToday catalog contains 31 unique level-1 category codes (`backend/app/scraper/offertoday/category_catalog_v1.json`).
- OfferToday canonicalization reads the first `job_functions` entry and stores its code as `offertoday:<code>` (`backend/app/sources/contracts.py:203-223`).
- Pending enrichment selection currently treats any non-empty `source_classification_id` as actionable and does not verify registry coverage (`backend/app/services/enrichment_run_service.py:103-110`, `343-360`).
- The taxonomy registry performs an exact mapping-key lookup and raises `Unknown source classification` when the key is absent (`backend/app/services/job_taxonomy_registry.py:44-55`).
- The mapping currently contains only eight OfferToday root entries (`backend/app/data/job_source_taxonomy_mapping.json:504-551`), while recent runs failed on valid catalog codes including `103000`, `105000`, `108000`, `109000`, `110000`, `111000`, `117000`, `119000`, `121000`, `124000`, `127000`, and `999000`.
- The observed LLM empty-response failures are a separate provider issue and are out of scope for this task.
- Some OfferToday roots have no exact same-named internal domain; they must be explicitly excluded rather than implicitly or misleadingly mapped.

## Requirements

### R1. Cover the authoritative OfferToday source taxonomy

Every OfferToday level-1 catalog code must have an explicit handling rule using the canonical `offertoday:<code>` key: either a source mapping entry or an explicit unsupported/excluded classification. Mapped entries must name an existing internal taxonomy domain, define a valid default path, and preserve the source classification identity used by stored jobs. Where a source category needs narrower guidance, its mapping may include source-subclassification hints. The plan must not force a misleading internal destination merely to avoid an exclusion.

### R2. Keep mapping and internal taxonomy contracts valid

The mapping must not introduce internal domains, categories, or subcategories that are absent from `job_category_taxonomy.json`. Existing JobsDB and CTgoodjobs mappings must remain unchanged in behavior.

### R3. Detect mapping drift before enrichment execution

The system must have a deterministic validation seam that fails or reports when an authoritative OfferToday root code lacks a mapping or a mapping points to an invalid internal taxonomy path. This check must run in automated tests and be fast enough for local/CI execution.

### R4. Prevent silent known failures in run selection

Before creating or executing a pending enrichment run, unsupported source classifications must be identified and excluded from the work sent to the enrichment workers. The operator must be told which jobs/categories were excluded and why; these items must not be reported as enrichment failures.

### R5. Preserve partial-run truthfulness

If a run contains unsupported items, its selection and final counters must clearly distinguish excluded items from LLM failures and successful enrichments. The operator-facing result must include excluded count and enough category/job detail to explain what was not attempted. If no supported items remain, the system must not dispatch an empty AI run. The existing custom-provider JSON failure behavior is not changed by this task.

### R6. Keep AI enrichment independent of live OfferToday access

The enrichment path must use only the persisted job fields and local taxonomy files. It must not fetch OfferToday categories, call OfferToday APIs, or require an OfferToday browser session. The source classification is an internal prior used to bound the AI prompt and final category resolution, not a live source connection.

## Acceptance Criteria

- [ ] All 31 OfferToday root codes in the catalog have exactly one explicit mapped-or-excluded handling rule.
- [ ] Every mapped OfferToday default path and allowed taxonomy slice resolves against the internal taxonomy file.
- [ ] A regression test fails if a catalog root is added without a corresponding mapping entry.
- [ ] Existing non-OfferToday registry behavior and mappings remain covered and unchanged.
- [ ] A pending enrichment preview/create path identifies and excludes unsupported source classifications before work is dispatched.
- [ ] The UI/API reports the excluded count and the unsupported source classification IDs/names with an actionable reason.
- [ ] Excluded items are not counted as failed, completed, pending, or LLM/provider errors.
- [ ] A run cannot dispatch an empty worker workload after preflight exclusion.
- [ ] The original observed `Unknown source classification: offertoday:<code>` failure pattern is covered by a deterministic test and no longer occurs for the current catalog.

## Scope boundaries

- Include source mapping data, registry validation, pending-run preflight/reporting, and regression tests.
- Do not change LLM provider selection, retry policy, response parsing, or the separate empty-response failures.
- Do not change the internal taxonomy vocabulary unless required to create a valid default destination for an OfferToday root; any such vocabulary change requires an explicit follow-up decision.

## Resolved product decision

When unsupported source classifications remain, exclude those items, show the excluded count and the specific unsupported categories/jobs, and continue processing supported items. Exclusions are a distinct non-attempted outcome, not failures. If every candidate is excluded, return an explicit no-supported-items result and do not start a worker run.

## Resolved taxonomy decision

OfferToday roots without a defensible internal taxonomy destination are explicitly excluded and reported. They are not forced into a nearest internal domain, because a wrong domain would silently bias both the AI prompt and the persisted category.
