# Source Catalog runtime correctness implementation plan

## Ordered implementation

### 1. Establish schema and repository

- [x] Add catalog candidate, validation-run, revision, active-pointer, and publication-audit models.
- [x] Register models in `app.models`.
- [x] Add existing-DB migration and fresh `bootstrap_db.py` convergence.
- [x] Add repository tests for immutability, unique active pointer, idempotent discovery, and transaction rollback.
- [x] Update `.gitignore` exceptions so every new backend test file is tracked.

Checkpoint commit: catalog persistence only; no runtime consumer changes.

### 2. Add normalized catalog contracts

- [x] Implement deterministic node/source payload serialization and fingerprints.
- [x] Implement generic tree/identity/alias/capability/query-target validation.
- [x] Implement catalog-level all-scope roots/recommendation plus deterministic all/subtree expansion and expansion fingerprints.
- [x] Implement diff categories: add/rename/move/remove/alias/capability/query semantics.
- [x] Test malformed hierarchy, duplicate IDs, cycles, alias collisions, and deterministic hash.

Checkpoint commit: pure domain logic; easy rollback.

### 3. Implement the three adapters

- [x] JobsDB discovery and shared request-param compiler.
- [x] CTgoodjobs candidate discovery and strict published URL compiler.
- [x] OfferToday tree/alias normalization and category-only compiler.
- [x] Add deterministic compile and captured-final-request tests proving URL/query/body constraints change per selected classification.
- [x] Add regression proving no classification-only OfferToday target is categoryless.

Checkpoint commit: adapters are unused by runtime until next step.

### 4. Align all retained runtime paths

- [x] Make JobsDB standalone and Scrapy requests share the category query builder.
- [x] Make CTgoodjobs standalone/Scrapy resolve only known compiled targets; delete raw fallback.
- [x] Make OfferToday scoped execution consume explicit category targets and preserve existing unscoped keyword behavior only outside Crawl Scope v1.
- [x] Preserve staging/source-classification metadata and logging contracts.
- [x] Run focused source executor/spider tests.

Rollback point: revert runtime call sites while keeping catalog tables/domain code.

### 5. Implement durable validation

- [x] Add validation coordinator, claim/retry semantics, and status projections.
- [x] Implement full offline validation and changed-target smoke selection.
- [x] Implement bounded JobsDB, headed CTgoodjobs, and OfferToday smoke runners.
- [x] Persist bounded evidence/manual-action context and redact logs.
- [x] Keep live tests opt-in/marked; unit tests use fixtures/fakes.

Checkpoint commit: validation jobs cannot activate a revision.

### 6. Implement lifecycle service and API

- [x] Add discover, summary/tree, candidate, validation, review, publish, history, rollback commands.
- [x] Persist expiring single-use publish/rollback review records bound to candidate/target fingerprint, base active revision, impact digest, and actor.
- [x] Enforce conditional active-pointer compare-and-swap, fresh review bindings, and explicit operator action.
- [x] Add structured errors and request-ID logging.
- [x] Add initial-publication management command that still requires explicit confirmation.
- [x] Do not add a permissive impact adapter; defer production activation until real impact is available if necessary.

### 7. Replace executable category authority

- [x] Make `SourceCategoryRegistry` a published-revision compatibility reader.
- [x] Make request validation reject unpublished/candidate/unknown/non-executable IDs.
- [x] Ensure runtime code never calls discovery.
- [x] Add integration tests showing API, validator, and runtime use the same revision/fingerprint.
- [x] Verify capability API reports revision health without triggering discovery.

Cutover checkpoint: only switch consumers when all three initial revisions exist in the test/staging environment.

### 8. Verify

Focused examples:

```bash
python3 -m pytest -q backend/tests/test_source_catalog_models.py
python3 -m pytest -q backend/tests/test_source_catalog_service.py
python3 -m pytest -q backend/tests/test_source_catalog_adapters.py
python3 -m pytest -q backend/tests/test_source_catalog_validation.py
python3 -m pytest -q backend/tests/test_jobsdb_standalone_crawl.py
python3 -m pytest -q backend/tests/test_ctgoodjobs_standalone_crawl.py
python3 -m pytest -q backend/tests/test_offertoday_standalone_crawl.py
python3 -m pytest -q backend/tests/test_cross_source_crawl_logging.py
```

Full checks:

```bash
python3 -m pytest --collect-only -q backend/tests
python3 -m pytest -q backend/tests
python3 -m ruff check backend/app backend/scripts backend/tests
python3 -m compileall -q backend/app backend/scripts
alembic -c backend/alembic.ini history
docker compose run --rm db-bootstrap
git diff --check
```

Opt-in staging smoke (intentionally deferred; not a deterministic completion gate):

- [ ] JobsDB one classification/page; final URL includes `classification`.
- [ ] CTgoodjobs one headed category/page; manual-action path verified.
- [ ] OfferToday one warmup + one category POST; body includes `jobFunctionCodes`.
- [ ] Logs contain bounded evidence and no secrets/bodies/target lists.

## Rollback

- Before runtime switch, drop/revert only new unused catalog code/schema as normal.
- After runtime switch, reactivate the prior immutable revision through the service.
- If no valid revision exists, block dispatch rather than restoring live/fallback behavior.
- Do not publish an initial production revision or begin the destructive control-data cutover until child 2 provides real impact and the parent rollout gate is approved.
