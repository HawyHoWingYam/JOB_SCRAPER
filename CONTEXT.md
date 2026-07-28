# Job Scraper Domain

This context describes how the system scopes work against external job sources and distinguishes source-owned classifications from the project's normalized job language.

## Source taxonomy

**Source**:
An external job platform from which listings and details are collected.
_Avoid_: Site when referring to the domain owner rather than a URL

**Source Taxonomy**:
The current classification hierarchy owned by one Source. Its labels, identifiers, depth, and coverage are independent from every other Source Taxonomy.
_Avoid_: Global taxonomy, shared sector list

**Source Classification**:
One identifiable node in a Source Taxonomy. Its identity is meaningful only together with its Source and must not be inferred from its display name. Registering a newly observed Source Classification does not create or change a Canonical Job Taxonomy node.
_Avoid_: Sector, canonical category

**Source Classification Registry**:
The ordinary current collection of Source Classifications known for one Source. Newly observed classifications are registered directly, top-level classifications may be active or inactive for new crawl authoring, and records are not physically deleted when a Source stops returning them.
_Avoid_: Source Catalog, published catalog, catalog release

**Source Classification Path**:
A Source-provided classification path assigned to a collected Job. A Job may retain zero or more paths, including every classification and subclassification returned by its Source.
_Avoid_: Primary category, canonical path

**Primary Source Classification Path**:
A Source Classification Path that the Source explicitly designates as primary. When the Source makes no such declaration, the Job has no primary path.
_Avoid_: First classification, inferred primary category

**Crawl Scope**:
The explicit Source Classifications, or explicit all-classifications rule, that bound one Automation or One-off Run.
_Avoid_: Selected sectors, category names

**Authored Crawl Scope**:
The operator's persisted crawl intent: one Source and either all active top-level Source Classifications or an explicit set of active top-level Source Classification identities.
_Avoid_: Catalog scope, child-classification scope, resolved query payload

**Resolved Run Scope**:
The Source Classification snapshots and Source-specific Query Targets frozen for one run from an Authored Crawl Scope.
_Avoid_: Current categories, live scope, catalog revision

**Query Target**:
An executable Source-specific query produced by resolving a top-level Crawl Scope through the owning Source adapter. An adapter may use a dedicated query or a broader collection-and-filter strategy.
_Avoid_: Selected category, crawl task

**Classification Keyword Sweep**:
A Source-specific deterministic set of hybrid Query Targets that pairs one selected Source Classification with each approved keyword while retaining that classification in every request. It is explicit frozen run scope, not a categoryless keyword search or hidden runner expansion.
_Avoid_: Keyword pack, global keyword crawl, implicit supplement

**Non-Job Listing Card**:
A source-returned row inside a listing cohort that is structurally identifiable as advertisement or interface content rather than a Job. It may be ignored with recorded evidence and is distinct from a job-shaped row with a missing identity.
_Avoid_: Broken Job, identity issue, listing

**Page Depth**:
The maximum listing pages requested for each Query Target in a run.
_Avoid_: Total page limit, max depth

**Run Page Cap**:
The maximum aggregate listing pages that one run may request across all Query Targets.
_Avoid_: Pages per sector, batch size

**Detail Run Cap**:
The maximum distinct job details that one detail run may attempt before completing normally.
_Avoid_: Detail batch size, segment size

**Recovery Segment**:
An internal execution partition used to process part of a detail run without changing its Detail Run Cap.
_Avoid_: Detail run, user batch limit

**Backlog Snapshot**:
The fixed set of items eligible for one detail run at dispatch time. Items becoming eligible later belong to a later run.
_Avoid_: Live backlog, entire database backlog

**Detail Backlog Scope**:
The explicit population from which a detail run may freeze its Backlog Snapshot: the Source backlog, a source-classification Crawl Scope, or one named listing batch.
_Avoid_: Detail category IDs, latest batch

**Canonical Job Taxonomy**:
The ordinary current project-owned hierarchy used to classify collected jobs consistently across Sources. It is structured as Job Domain → Job Category → Job Subcategory and does not determine Crawl Scope.
_Avoid_: AI Category, Classification, Canonical Job Domain when referring to the whole hierarchy

**Job Domain**:
The broadest first-level concept in the Canonical Job Taxonomy.
_Avoid_: Canonical Job Domain, domain taxonomy

**Job Category**:
A second-level concept in the Canonical Job Taxonomy, nested within one Job Domain.
_Avoid_: AI Category, Source Classification

**Job Subcategory**:
The most specific third-level concept in the Canonical Job Taxonomy, nested within one Job Category.
_Avoid_: Source Subclassification, job type

**Canonical Taxonomy Assignment**:
An accepted classification of one Job to an existing Job Subcategory, with recorded method and evidence.
_Avoid_: AI Category, fallback path

**Canonical Assignment Coverage**:
The share of a stated Job population that has an accepted Canonical Taxonomy Assignment. It is a population-health measure, not Source-to-Canonical Job Mapping coverage.
_Avoid_: Mapping coverage, taxonomy coverage

**Source-to-Canonical Job Mapping**:
An optional current mapping from one Source Classification identity to existing Canonical Job Taxonomy targets or one explicit non-mapping disposition. Missing mapping never blocks automated classification and the mapping never changes Crawl Scope.
_Avoid_: Required coverage release, Source category alias, automatic name match

**Source-Bound Canonical Slice**:
The optional deterministic union of existing Job Subcategories permitted by available mappings across one Job's Source Classification Path evidence. When no mapping exists, automated classification may use the full Canonical Job Taxonomy.
_Avoid_: Default category, fallback path

**Unassigned Canonical Taxonomy**:
The explicit state in which a Job has no acceptable Canonical Taxonomy Assignment.
_Avoid_: General fallback, Unknown category

**Classification-Ready Unassigned Job**:
An unassigned Job that retains the source-attribute evidence required to attempt Canonical Job Taxonomy classification. Readiness means the prerequisites are present; it does not guarantee that classification will succeed.
_Avoid_: Unassigned Job, guaranteed classification candidate

**Classification Processing Batch**:
A bounded automated run that assigns current Job Taxonomy, Company Industry, or Skill data, exposes progress and failures, and permits retry without requiring routine per-item human review.
_Avoid_: Governance queue, taxonomy release, manual review backlog

## Job attributes

**Manual Job**:
A Job entered directly by an operator rather than collected from an external Source. It participates in the Published Job Corpus and shared intelligence workflows without making manual intake a Source.
_Avoid_: Manual Source Job, fourth Source

**Operator-Authored Job Fact**:
A Job value explicitly supplied by the operator during manual intake. It is authoritative for that Job and is not silently replaced by automated enrichment.
_Avoid_: AI suggestion, inferred value

**Employment Type**:
One governed value describing the employment relationship offered by a Job. A Job may have zero or more Employment Types from Full-time, Part-time, Permanent, Contract, Temporary, Internship, and Freelance.
_Avoid_: Job Type, role type

**Source Employment Label**:
An employment label or code reported by a Source and retained with its original order as evidence for Employment Type normalization.
_Avoid_: Employment Type, Other

**Work Arrangement**:
The place or mode in which work is performed, such as on-site, remote, or hybrid, independent from Employment Type.
_Avoid_: Employment Type, working days

**Company Industry Taxonomy**:
The ordinary current project-owned classification of business sectors used to describe Companies with stable identities, seeded from the five-level HSIC V2.0 hierarchy.
_Avoid_: Job Taxonomy, Source Classification, free-text industry list

**Company Industry**:
A governed business-sector concept from the Company Industry Taxonomy assigned to a Company from traceable company-level evidence.
_Avoid_: Job Industry, Source Classification, inferring industry from a job's function

**Company Industry Assignment**:
A provenance-bearing association between one Company and the most specific Company Industry supported by its evidence. A Company may have zero or more assignments; ancestor Industries are derived from the taxonomy hierarchy.
_Avoid_: Free-text industry, job classification

**Primary Company Industry**:
A Company Industry Assignment explicitly declared primary by an authoritative company source or confirmed by a Taxonomy Operator.
_Avoid_: First industry, AI-inferred primary

**Source Industry Label**:
An industry label or code reported by a company-owned Source and retained as provenance for Company Industry mapping.
_Avoid_: Company Industry, job classification

**Company Industry Review Item**:
Unresolved company-level industry evidence awaiting a Taxonomy Operator decision before any Company Industry Assignment is created.
_Avoid_: AI-assigned industry, free-text Industry

## Skill taxonomy

**Skill**:
A governed technical capability accepted into the project's Skill Taxonomy. Only Skills participate in ordinary skill search, recommendations, and analytics.
_Avoid_: Provisional Skill, raw extracted term

**Skill Mention**:
One occurrence of a potential skill extracted from a Job. A Skill Mention is evidence that may resolve to a Skill, a Skill Candidate, a generic tag, or rejection.
_Avoid_: Skill, candidate

**Skill Candidate**:
An unresolved potential Skill aggregated from one or more Skill Mentions and awaiting a governance decision.
_Avoid_: Provisional Skill, ungoverned Skill

**Matched Canonical Skill**:
A Skill attached to a Job after extracted evidence resolves to an active governed Skill. It excludes unresolved candidates, generic tags, and rejected mentions.
_Avoid_: Requested Skill, extracted term, provisional Skill

**Canonical Skill Match Coverage**:
The share of successfully enriched Jobs in a stated population that have at least one Matched Canonical Skill. Jobs awaiting enrichment are outside this denominator rather than treated as failed matches.
_Avoid_: Skill demand coverage, all-jobs Skill coverage

**Canonical Skill Prevalence**:
The share of successfully enriched Jobs in a stated population that have one particular Matched Canonical Skill. Because a Job may have multiple Skills, prevalence values are independent and do not form a 100% composition.
_Avoid_: Skill share, market demand share

**Unreviewed Skill Mention**:
A Skill Mention that currently contributes to a Skill Candidate and has not yet received a governance decision.
_Avoid_: Provisional Skill

**Taxonomy Operator**:
A human using the trusted local product for occasional direct correction when automated classification cannot produce an acceptable result.
_Avoid_: Routine queue reviewer, release publisher

## Operations

**Operations Dashboard**:
The internal operator surface for observing collection, enrichment, and canonical-assignment health. Its taxonomy and Skill distributions describe the Published Job Corpus and are not labor-market trend analytics.
_Avoid_: Labor market dashboard, market intelligence dashboard

**Dashboard Corpus Snapshot**:
A current operational summary of the retained Jobs in the Published Job Corpus, including source listings that may have expired. It excludes deleted Jobs and does not claim to represent the active labor market.
_Avoid_: Active jobs, current openings, market sample

**Job Intelligence Projection**:
A rebuildable representation derived from preserved Job or Company evidence for classification, governed attributes, search, analytics, or recommendations.
_Avoid_: Core Job data, Published Job Corpus

**Crawl Control Data**:
Operational definitions and records used to configure, dispatch, stage, and observe crawl work. It can be rebuilt without redefining the identity of already published jobs.
_Avoid_: Job data, all crawler data

**Published Job Corpus**:
The accepted job records and attached business enrichment retained for search and analysis after collection.
_Avoid_: Crawl history, staging backlog

**Automation**:
A recurring crawl definition that creates runs on a schedule.
_Avoid_: Scheduled task, cron job

**Archived Automation**:
An Automation retained for history and possible restoration but prohibited from future dispatch.
_Avoid_: Deleted automation, paused automation

**One-off Run**:
A crawl requested for immediate execution without changing an Automation.
_Avoid_: Direct Override, immediate scrape

**Dispatch Plan**:
A short-lived, single-use server-reviewed plan that freezes the exact Resolved Run Scope, execution limits, readiness evidence, and any Backlog Snapshot that a confirmed run will consume.
_Avoid_: UI preview, mutable request payload
