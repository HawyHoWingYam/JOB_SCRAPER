# Source Catalog runtime correctness

## Goal

Establish one authoritative, published, source-native executable catalog for JobsDB, CTgoodjobs, and OfferToday, and prove that every selected Source Classification materially constrains its actual upstream listing request.

## Background

- The current category API is a flat in-memory registry. CTgoodjobs may be fetched live while the headed runtime resolves a static registry, so validation and execution can disagree (`backend/app/services/source_category_registry.py:68-163`; `backend/scripts/ctgoodjobs_standalone_crawl.py:120-136`).
- JobsDB's production standalone path sends `classification=<id>`, but its Scrapy path currently sends a fixed URL and carries category only as callback metadata (`backend/app/scraper/category_scraper.py:46-71`; `backend/scrapy_project/job_scraper_spiders/spiders/jobsdb.py:66-78`).
- OfferToday has an immutable two-level catalog, 31 same-code child aliases that are not independent query leaves, 431 unique query leaves, parent expansion, and category/keyword/hybrid query families (`backend/app/scraper/offertoday/category_registry.py:52-168`; `backend/app/sources/offertoday/search_space.py:223-403`).
- Existing source capability metadata is separate from taxonomy and query compilation (`backend/app/services/source_catalog.py:7-59`).
- The independent `07-18-offertoday-taxonomy-mapping` and `07-18-job-intelligence-taxonomy-governance` tasks own post-collection canonical mapping, not pre-dispatch scope.

## Requirements

- Persist immutable Catalog Candidates and published Source Catalog Revisions with source, fingerprint, provenance, normalized node envelope, source-native payload, and validation evidence.
- Maintain one atomic active-revision pointer per Source. Candidates are never readable through executable category validation or runtime paths.
- Every normalized node preserves a revision-stable node key, source-qualified Source Classification identity when selectable, native ID/label/path/parent/depth, exact/subtree/query capabilities, alias relationship, and query-semantics fingerprint.
- Every published revision declares catalog-level `supports_all_scope`, the root node set used to resolve it, and a non-authoritative recommended authored scope. JobsDB and CTgoodjobs support all classifications; OfferToday also supports explicit all-source scope, while its wizard recommendation remains the visible `offertoday:118000` IT subtree.
- OfferToday same-code child aliases remain visible/auditable but cannot create duplicate independent scope rules or Query Targets.
- Implement one real SourceCatalogAdapter seam with exactly three production adapters. It owns discovery, compilation of page-independent non-secret Query Targets, and bounded live smoke; shared catalog validation owns generic tree/identity/diff checks.
- JobsDB Query Targets compile to the same `classification` request constraint in standalone and Scrapy execution paths.
- CTgoodjobs Query Targets resolve only through the published revision. Unknown IDs fail before any request; the current raw-ID/slug fallback is removed. CTgoodjobs remains headed-only.
- OfferToday category targets compile to bounded `jobFunctionCodes` requests with explicit endpoint/strategy metadata. A classification-only scope cannot silently add categoryless keyword targets; keyword-only discovery is outside Crawl Scope v1.
- Candidate validation runs offline checks for every node and compiles every selectable action. Added or query-semantics-changed targets receive a durable, bounded live-smoke run through the Source's supported mode.
- Live smoke is limited to one target/page (plus required OfferToday warmup), excludes details and staging, persists bounded evidence, and never logs cookies, auth, bodies, or unbounded IDs.
- Validation may end in passed, failed, or manual-action-required state and is retryable without changing the active revision.
- Publication and rollback require explicit operator commands, fresh candidate/revision fingerprints, and an impact-review token. No first-version path auto-publishes.
- The published catalog API returns hierarchy/capabilities for new consumers. The legacy `/categories` shape becomes a compatibility projection of the published revision and never performs live discovery.
- Provide an explicit operator bootstrap path for initial discovery/validation/publication; migrations or application startup must not silently publish.
- Normal tests are deterministic and network-free; live-smoke tests are separately marked/opt-in.

## Acceptance criteria

- [x] Catalog Candidate, validation evidence, immutable revision, active pointer, publication history, and rollback persistence are covered.
- [x] Candidate and unpublished node IDs fail executable validation and dispatch.
- [x] JobsDB tests prove distinct Source Classifications change the `classification` request parameter in every retained runtime path.
- [x] CTgoodjobs tests prove distinct IDs resolve distinct published URLs and unknown IDs cannot fall through to a guessed URL.
- [x] OfferToday tests cover root exact, subtree expansion, unique leaves, same-code alias deduplication, request `jobFunctionCodes`, and absence of categoryless supplemental queries for classification-only scope.
- [x] Full-catalog offline validation and changed-target live-smoke selection are deterministic; bounded evidence is safe to log/store.
- [x] CTgoodjobs live-smoke/manual-action execution remains headed-only.
- [x] Publication/rollback atomically changes all executable consumers and preserves immutable prior revisions.
- [x] Legacy flat category consumers receive a published-revision compatibility projection rather than live/fallback data.
- [x] Initial publication requires an explicit operator action.
- [x] Post-collection canonical taxonomy/enrichment behavior is unchanged.

## Dependency and scope

- This is the first implementation child. It provides the published catalog and adapter interfaces consumed by `07-18-versioned-crawl-scope`.
- Automation persistence, Crawl Scope, destructive cutover, and frontend governance/wizard implementation are out of scope.
- If Automation impact cannot yet be evaluated, the catalog module exposes a typed impact interface but publication in production remains gated until child 2 integrates the real evaluator; do not add a speculative pass-through implementation.
