# Jev opportunities for JOB_SCRAPER

Research date: 2026-09-23. Task: `09-23-research-jev-use-cases`. Tracking issue: [#62](https://github.com/HawyHoWingYam/JOB_SCRAPER/issues/62).

## Recommendation

Start with **Skill Candidate recommendations and source-grounded enrichment verification** in an offline/shadow experiment. Both have bounded decisions, existing evidence, and observable errors. Evaluate **search ranking fusion** and **cross-source duplicate grouping** separately; their user value is promising, but their retrieval and identity contracts make them larger changes.

Jev should supply uncertain semantic judgments inside the existing application. Exact aliases, source identities, numeric calculations, eligibility, operator authority, crawl scope, cancellation and transaction ownership remain in ordinary code. These are proposed applications, not integrations already made or performance already measured.

## What was examined

The supplied [awesome-jev catalog](https://github.com/heyjunpenn/awesome-jev/tree/24279e3fb0a949ae87abd0d772530c1227cf86a7) has **640 unique entries in 11 categories**. The two links in its separate repository-reference table are not additional entries.

- Every catalog row received a screening disposition in [the 640-entry ledger](catalog-screening.md), also available as [CSV](catalog-screening.csv) and [JSON](catalog-screening.json).
- Root README retrieval succeeded for **630** repositories; **10** failed at the attempted README paths. An unsuccessful root README fetch is not proof that a repository is private or nonexistent.
- Evidence levels are mutually exclusive: **380 README-excerpt screenings**, **233 targeted README skims**, **2 full-README-only reviews**, **15 selected source-call-site reviews**, and **10 unavailable README leads**. A source review may also include the README; it is not a full code audit.
- **26 source repositories were cloned**, with revisions in [source-revisions.json](source-revisions.json). Cloning does not count as code review.
- No upstream programs, live model calls, or benchmark suites were executed. All performance numbers discussed below belong to their authors.
- Two scouts returned terminal research results. An SDK scout left usable partial artifacts before a reported 429 failure; these were inspected and its JSON formatting repaired during integration. Other scouts failed with 429. Main-thread screening covered the remaining entries. [SDK notes](scout-sdk.md), [linkage/evidence notes](scout-linkage.md), and [retrieval synthesis](retrieval-notes.md) preserve the useful findings.

This fulfills a catalog-wide idea screen, not a claim to have deeply audited 640 applications. The catalog itself includes SDKs, local Jev-style models, games, repeated integrations and other directories. They are not 640 independently validated product opportunities. Category and coverage totals are recorded in [coverage.json](coverage.json).

## Current project constraints

The current code matters more than the older broad domain glossary:

1. `SkillClassificationAdapter.process_candidate()` tries deterministic existing-skill and curation paths first. It rejects new-Skill creation without operator confirmation (`backend/app/services/classification_domain_adapters.py:182`, `:261`). Jev cannot silently promote a Skill Candidate.
2. `AIEnrichmentService.enrich_job()` obtains source/origin eligibility before extraction, preserves operator-authored experience bounds, and owns the enrichment transaction (`backend/app/services/ai_enrichment_service.py:37`). Semantic QA must not bypass that boundary.
3. Search already has lexical, semantic and hybrid modes. Hybrid ranking combines semantic, lexical, source classification, governed skills and freshness. A reranker must preserve structured scope, totals, pagination, facets and export consistency (`backend/app/services/retrieval_service.py:51`; `backend/app/search/hybrid_ranker.py:78`).
4. Company Industry is removed from the current product/schema according to `.trellis/spec/backend/ordinary-current-taxonomies.md:8`; the current Company/search models corroborate this. The earlier suggestion to prioritize Company Industry was based on stale `CONTEXT.md` content and is withdrawn.

## Ranked opportunities

The effort estimates below are qualitative research judgments, not delivery estimates. P0 means a recommended first experiment, not a project incident priority.

| Priority | Proposed use | Jev's bounded question | Application action | Effort / primary measure |
|---|---|---|---|---|
| P0 | Skill Candidate recommendation | Which existing path fits, or is evidence generic/rejected/insufficient? | Show an evidence-backed recommendation; retain operator confirmation for new Skills | Small–medium; recommendation precision, abstention and operator time |
| P0 | Enrichment evidence verification | Does the exact source passage support this extracted skill/experience claim? | Flag unsupported or conflicting derived facts; keep raw evidence and current authoritative facts | Small–medium; unsupported-claim recall at an acceptable false-flag rate |
| P1 | Search ranking fusion | How relevant is each retrieved Job to the user's stated intent? | Blend with existing retrieval rank over a bounded candidate set | Medium; candidate recall, NDCG@10, P@5, p95 latency |
| P1 | Cross-source duplicate grouping | Do these two records describe the same opening? | Add a reversible group/suggestion while preserving both source Job IDs | Medium–large; pair precision/recall and cluster false merges |
| P1 | Crawl/content quality triage | Is this real Job content, a login/error page, or incomplete output? | Add an advisory observation; use existing source recovery policy | Medium; missed broken-page rate and false alarms |
| P2 | Company identity suggestions | Do these company records identify the same organization? | Suggest a link with evidence; preserve original company text and identities | Medium; false-link rate, unresolved coverage |
| P2 | Evidence selection for enrichment | Which passages support or contradict the requested fields? | Pass a smaller, source-linked context to the current extractor | Medium; evidence recall, extraction accuracy, token cost |
| P2 | Operational log triage | Which failures warrant deeper investigation? | Group/label failures and prioritize review; retain all error evidence | Small–medium; actionable-error recall and review time |
| P2 | Selective refresh of derived intelligence | Does new source evidence change an existing derived assertion? | Suggest affected fields for re-evaluation after deterministic hash checks | Medium; missed material changes vs avoided recomputation |
| P2 | Enrichment/provider routing | Can a bounded decision path handle this case, or is fallback necessary? | Use approved routes under an explicit cost/latency budget | Medium; total quality and cost including routing/fallback |
| P2 | Offline semantic corpus exploration | Does a Job satisfy an analyst-authored criterion? | Materialize reviewable derived labels from a bounded corpus snapshot | Medium; label quality and reproducible population/denominator |

### 1. Skill taxonomy navigation

[jev-tree](https://github.com/reachjalil/jev-tree/blob/95bff63bd653fee4dc71f33f9431dce0f81e2ca3/src/index.ts#L294) maps local option keys back to existing tree nodes and walks bounded choices. This is a concrete answer to the API's 255-choice limit, and fits Category → Technology → Skill navigation.

For this project, keep exact names and aliases first; give Jev explicit candidate definitions and an insufficient-evidence path. If a parent-level decision is uncertain, stop or inspect alternative branches rather than force a leaf. The source's fallback of missing option probability to `1` and its single-child shortcuts are reasons to borrow the navigation idea rather than import its confidence policy. Its per-step/minimum probability is not an evaluated probability that the entire path is correct.

Example: “Power BI dashboard development” can suggest the existing BI/analytics path. A broad phrase such as “good communication” can remain a generic disposition. Naming/alias generation remains a separate capability; selecting a taxonomy node does not generate new trustworthy text.

### 2. Verify extracted facts against source evidence

[citation-verifier](https://github.com/MarissaFamularo/citation-verifier/blob/f9058642274033e62855d3066988418fefa2e272/src/lib/typesafe.js#L55) asks whether a source passage supports, contradicts or does not address a claim. Its [upstream validation](https://github.com/MarissaFamularo/citation-verifier/blob/f9058642274033e62855d3066988418fefa2e272/src/lib/manuscriptCitations.js#L76) locates proposed quotes before displaying support. This is a useful two-part contract: verify where evidence came from in code, then judge its meaning.

Apply it to extracted experience/skills: “3 years preferred” must not automatically become a mandatory minimum; “Python not required” must not become a required Skill. Jev may judge the relation, but code checks spans, numbers, units and range consistency. Add explicit missing-context/uncertain handling. The upstream `selectPassage()` can accept a supplied quote without locating it, so our future boundary must require a validated span itself instead of relying on caller discipline.

### 3. Search: compare fusion as well as replacement

[llama-index-jev](https://github.com/WiktorB2004/llama-index-jev/blob/72c73dc50bca4b7ea6928ef65ea09f1a7ee4a01e/packages/llama-index-postprocessor-jev/llama_index/postprocessor/jev/base.py#L132) scores query/passage pairs and preserves original retrieval order on failure. [hev/reranker](https://github.com/hev/reranker/blob/1eb47266270b32b2a3667f9fb89646378ca9c9d6/hev_rerank/rerank.py#L86) instead batches candidate documents and asks one independent Noul per document.

Both patterns permit multiple relevant Jobs. One `Choice` over all Jobs would force a single winner and is the wrong interface for ordinary search. Test pairwise-state calls against bounded batching; do not assume batch shape has no quality effect.

The current service offers a seam around hybrid candidate ranking, but it currently loads candidate embedding rows before ranking. A production design must introduce a real candidate bound before model calls, preserve pagination/export behavior and measure candidate recall. Compare original ranking, Jev-only reranking, a local reranker and rank fusion. Tied model scores need a stable secondary order.

### 4. Record linkage without destructive merging

[jlink](https://github.com/keltokhy/jlink/blob/4d7ccb7609a8302271697e63fef4c7c34da6b090/src/jlink/judge.py#L100) initializes candidate pairs as unjudged, keeps IDs, and leaves budget-exhausted pairs unjudged. Its [blocking](https://github.com/keltokhy/jlink/blob/4d7ccb7609a8302271697e63fef4c7c34da6b090/src/jlink/block.py#L230) reduces the number of expensive comparisons.

This fits cross-source postings with similar title/company/location/descriptions. First generate plausible pairs using ordinary normalization, dates and retrieval, then ask a precise identity question. “Same role family” and “same opening” are different labels. Separate company-identity suggestions from Job identity. Preserve each source record and attach a derived group only.

Pair accuracy is not cluster accuracy: a single false match can join two groups. Evaluate cluster-level false merges and provide reviewable edges. Record model/prompt/input versions so changing thresholds does not require re-fetching source Jobs.

### 5. Judge page quality before enrichment

[jev-playwright-mcp](https://github.com/krw82/jev-playwright-mcp/blob/db7762fd2ef66af7b38362c98982692bc81f57b7/src/jev/detectors.ts#L52) classifies observed page text into expected content, login, challenge, error, throttling, empty output and unknown. It creates action hints in code. [doc-router](https://github.com/misbahsy/doc-router/blob/8977d2ba1fd672fbbc85f01e630a2d5de6a406aa/crates/doc-router-jev/src/judge.rs#L151) first detects ambiguous extraction evidence and can use a semantic judge only there.

The transferable idea is to identify suspicious collected content, not to replace stable source adapters with a click agent. Test a shadow check after extraction using page title/URL/content and deterministic parse results. Existing HTTP status, WAF stops, frozen scope, pacing and manual recovery remain authoritative. Do not treat a model's “expired” guess as permission to delete a retained Job.

### 6. Preserve supporting and contradictory passages

[jselect](https://github.com/keltokhy/jselect/blob/dc6b725c85229da5c55b88954da749bf66d89db9/src/jselect/judge.py#L120) explicitly regards counterevidence as relevant and selects passages under a token budget. The project can use this to reduce long descriptions before enrichment while preserving original spans and diversity.

The success measure is downstream field accuracy and evidence recall, not simply fewer tokens. A selected passage without its negation or heading can invert a requirement. Keep the complete raw Job description and ensure numbers/negations survive selection; uncertain filtering should retain evidence.

### 7. Operational triage with explicit fallbacks

[jevlogs](https://github.com/reachjalil/jevlogs/blob/217d2b70bfb327a0038b21851c1c9c143eb80469/src/index.ts#L282) protects error-severity records before model scoring, separates model/budget/unavailable reasons, caches judgments and routes ambiguous results to deeper analysis.

Apply that pattern to repeated scraper errors: group by source and symptom, distinguish transient disconnects from profile/session problems, and rank investigation candidates. Do not delete logs, lower deterministic error severity, or let Jev change retry/cancel state. A model outage must remain an unavailable judgment rather than evidence that an incident is harmless.

### 8. Derived evidence freshness and semantic corpus queries

[invalidate](https://github.com/chopratejas/invalidate/blob/d6ed0ea4e72660408dc175cd20caf6cb8658e9b0/src/invalidate/engine.py#L179) records evidence-triggered judgments and transitions. The relevant adaptation is narrowly marking derived assertions for re-evaluation when new source evidence arrives. Existing `evidence_hash` checks are cheaper and should remain first; never let model judgments rewrite raw source facts.

The SQL/DataFrame projects in ledger IDs 84, 94, 98, 102, 106, 109 and 365 suggest a separate analyst workflow: prefilter Jobs, evaluate explicit semantic criteria, and materialize versioned derived labels. This may support questions such as “roles mentioning production operations rather than classroom exposure.” It does not justify network calls inside ordinary search queries or overwriting source classifications.

## Evaluation lessons that change the design

| Evidence | What it supports | What it does not establish |
|---|---|---|
| [Jev search-rerank evaluation](https://github.com/zhuyansen/jev-search-rerank-eval/blob/c896f14e944182e17a002dd7546f06ba3788d586/README.md#L19) | Compare fusion, strong retrieval baselines and independent labels | Its apparent gains do not transfer automatically to Jobs. Its “hand” adjudication section actually describes Claude adjudication; do not label it a human gold set |
| [OOD calibration study](https://github.com/scienthoon/jev-ood-calibration/blob/914d87ab16517f14e833cff63d73b51235b14bd6/README.md#L33) | Calibration depends on task/primitive; missing policy cannot be inferred reliably | Synthetic hidden rules, label noise and an endpoint-floor correction limit the headline claims; it is not a universal model failure rate |
| [Calibration audit](https://github.com/jujumilk3/jev-calibration-audit/blob/daab9e2c2d5d5683bf07f3482deb653c26856219/README.md#L39) | Include explicit abstention and test Noul/Choice consistency, language and request shape | Its observed absence of option-order bias is specific to its sample |
| [Behavior study](https://github.com/RINNECODER/jev-behavior-study/blob/e4a1d7ec691a91f33d3b5879a780e6f27328f173/README.md#L138) | Wording, answer order, context position and deterministic prerequisites deserve local tests | Arithmetic/games do not directly measure job-language classification |
| [ORDER BY benchmark](https://github.com/yodablocks/jev-orderby-bench/blob/523979540d0fad2786208ba07cc8d0fe2711f9ed/README.md#L11) | Test ranking ties, batching and graded relevance separately from binary accuracy | A useful binary threshold is not proof of a useful search sort key |

These reports sometimes disagree because their tasks, interfaces and labels differ. Preserve that disagreement in the experiment instead of averaging unrelated headline percentages. No published number in this report was independently reproduced here.

Official [confidence documentation](https://docs.typesafe.ai/confidence) describes `confidence` as a statistic derived from the distribution. It is not automatically the probability that a business action is correct. Save raw distributions, derive task-specific policy separately, and evaluate it on held-out data.

## Why several tempting ideas are deferred

- **Replace all LLM enrichment:** Jev's bounded outputs cannot directly replace summary, name or alias generation. Span/option selection is possible, but candidate construction and evidence coverage then become the hard part.
- **Run every decision through a model:** exact aliases, numeric parsing, hash invalidation and source identities already have deterministic answers.
- **Put semantic calls into production SQL:** repeated queries, pagination and retries can multiply cost and produce unstable user-visible results. The offline materialization idea is more compatible initially.
- **Adopt browser-agent demos wholesale:** ongoing click loops introduce new failure modes across already-stable source adapters. Page quality checks are the smaller experiment.
- **Treat “Jev-like” as the same model:** the 18 explicitly categorized replicas, plus some research projects, have independent weights/training/behavior. [open-Jev for job postings](https://github.com/DECRUX9812/openjev/blob/7bcf388dc4789b55ce22b37a6b5ace003913d9bb/README.md) is a useful domain analogy, but it is a local classifier with a small held-out set and a disclosed rare-class problem.
- **Applicant screening, trading, games, character-by-character text generation:** these are outside the current job-corpus product. Their general decision/control separation can be borrowed without adding those products.
- **Assume coding-agent “skills” are Job Skills:** the former are tool/workflow instructions, the latter are governed employment capabilities. Only candidate-selection mechanics transfer.

## Proposed first experiment

Build a 200–500-case development corpus and a separately held-out labeled slice drawn from the project's actual evidence. Include English, Traditional Chinese and mixed descriptions; exact aliases; generic terms; new terms; absent/misleading context; negated skills; preferred versus required experience; and conflicting operator-authored values. Keep examples from the same underlying Job/company or duplicated posting from leaking across splits.

Compare the existing deterministic/LLM path against Jev decisions using the same available evidence. Human adjudication should define the held-out truth; another model may assist triage but cannot be the sole truth source. The [official comparison adapter](https://github.com/typesafe-ai/system-one-adapter-python/blob/e1d4cc938204b22fc5a3c3aca7044072fe3f712d/README.md) can make decision interfaces comparable, while its generated/normalized probability-shaped outputs still require independent calibration checks.

Report per-class precision/recall, false generic/reject rates, unknown handling, coverage versus error, Brier/reliability bins where labels permit, p50/p95 end-to-end latency, tokens, retries and actual billed cost if available. Tune thresholds on development data only. A 200–500-case pilot is a feasibility check, not proof of extremely low failure rates.

Save `source_id`, original evidence hash/span, candidate identities, question/rubric version, requested and resolved model, probabilities, elapsed time, usage, retry/error/abstention reason and final operator label. Shadow output must not write ordinary Skill assignments or change Job facts. Decide whether to proceed only after measuring useful accuracy/coverage at an acceptable total cost.

The corresponding [design](../design.md) and [execution plan](../implement.md) remain proposals. The user has authorized this research/task/issue; production implementation and paid evaluation remain a subsequent scope decision.
