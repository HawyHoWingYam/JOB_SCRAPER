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
One identifiable node in a Source Taxonomy. Its identity is meaningful only together with its Source and must not be inferred from its display name. Source Classifications remain Source-owned and are never combined into a cross-Source Job hierarchy.
_Avoid_: Sector, global category

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

**Source Classification Keyword Pack**:
An operator-maintained set of supplemental search terms owned by one top-level Source Classification. A run may freeze its approved terms into Query Targets, but the pack does not redefine the operator's authored Crawl Scope.
_Avoid_: Global keyword list, generated keywords, Source Classification

**Non-Job Listing Card**:
A source-returned row inside a listing cohort that is structurally identifiable as advertisement or interface content rather than a Job. It may be ignored with recorded evidence and is distinct from a job-shaped row with a missing identity.
_Avoid_: Broken Job, identity issue, listing

**Page Depth**:
The maximum listing pages requested for each Query Target in a run.
_Avoid_: Total page limit, max depth

**Run Page Cap**:
The maximum aggregate listing pages that one run may request across all Query Targets.
_Avoid_: Pages per sector, batch size

**Evidence-Bounded Coverage**:
The state in which every planned collection route has stopped producing new listing identities under the run's recorded coverage policy. It does not claim knowledge of the Source's absolute inventory.
_Avoid_: All Jobs, absolute completeness, expected job count

**Stalled Query Target**:
A Query Target for which the Source still reports continuation but three consecutive pages contribute no new listing identities. It is degraded rather than exhausted.
_Avoid_: Completed partition, natural exhaustion, duplicate page

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

## Job attributes

**Manual Job**:
A Job entered directly by an operator rather than collected from an external Source. It participates in the Published Job Corpus and shared intelligence workflows without making manual intake a Source.
_Avoid_: Manual Source Job, fourth Source

**Job Origin**:
The route by which a Job entered the Published Job Corpus: collection from a Source or Manual Entry by an operator.
_Avoid_: Source when the value may be Manual Entry

**Operator-Authored Job Fact**:
A Job value explicitly supplied by the operator during manual intake. It is authoritative for that Job and is not silently replaced by automated enrichment.
_Avoid_: AI suggestion, inferred value

**Job Evidence Finding**:
An assessment of whether a retained source passage supports a stated Job attribute. It is review evidence, not a confirmed correction or proof of real-world truth.
_Avoid_: Verified Job fact, automatic correction

**Suspected Duplicate Association**:
A reviewable relationship between separately retained Job records that may describe the same vacancy. It does not establish shared identity or replace either source record.
_Avoid_: Merged Job, confirmed duplicate

**Related Job**:
A separately retained Job recommended because its work or requirements are relevant to another Job. Relatedness does not assert that the two records describe the same vacancy.
_Avoid_: Duplicate Job, same vacancy

**Stale Job Intelligence**:
Previously generated Job Intelligence whose supporting Job facts have since changed. It remains traceable but does not represent the current Job until successful replacement.
_Avoid_: Current enrichment, failed enrichment

**Company Enrichment Run Limit**:
The operator-requested maximum number of eligible Companies frozen into one Company-description run. It controls run scope, not execution concurrency.
_Avoid_: Concurrency, page size, global maximum

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
_Avoid_: Role Classification, Source Classification, free-text industry list

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

**Company Industry Source Mapping**:
A governed association from one Source Industry Label identity to an existing Company Industry or an explicit non-mapping disposition.
_Avoid_: Free-text industry alias, Job Industry mapping, inferred company industry

**Company Industry Review Item**:
Unresolved company-level industry evidence awaiting a Taxonomy Operator decision before any Company Industry Assignment is created.
_Avoid_: AI-assigned industry, free-text Industry

## Skill taxonomy

**AI Skill Projection**:
The complete Skill result produced within one ordinary AI Enrichment execution for a Job. It classifies retained evidence into governed Skill assignments, Unresolved Skill Evidence, Generic Skill Tags, or rejection without a separate correction pass. Existing operator-authored decisions remain authoritative.
_Avoid_: Skill baseline, second-pass correction, separately corrected Skills

**Skill**:
A governed technical capability accepted into the project's Skill Taxonomy. Only Skills participate in ordinary skill search, recommendations, and analytics.
_Avoid_: Provisional Skill, raw extracted term

**Skill Mention**:
One occurrence of a potential skill extracted from a Job. A Skill Mention is evidence that may resolve to a Skill, Unresolved Skill Evidence, a Generic Skill Tag, or rejection.
_Avoid_: Skill, review item

**Generic Skill Tag**:
A governed non-Skill disposition for a broad activity or workplace concept retained as Skill Mention evidence but excluded from the Skill Taxonomy, ordinary skill assignments, and Skill analytics.
_Avoid_: Skill, rejected mention, provisional Skill

**Unresolved Skill Evidence**:
An unknown technical term retained from one or more Skill Mentions when ordinary AI Enrichment cannot map it to an existing governed Skill. It is non-searchable internal evidence, not a review queue and not authority to create a new Skill.
_Avoid_: Skill Candidate, provisional Skill, review item, governed Skill

**Matched Canonical Skill**:
A Skill attached to a Job after extracted evidence resolves to an active governed Skill. It excludes unresolved candidates, generic tags, and rejected mentions.
_Avoid_: Requested Skill, extracted term, provisional Skill

**Canonical Skill Match Coverage**:
The share of successfully enriched Jobs in a stated population that have at least one Matched Canonical Skill. Jobs awaiting enrichment are outside this denominator rather than treated as failed matches.
_Avoid_: Skill demand coverage, all-jobs Skill coverage

**Canonical Skill Prevalence**:
The share of successfully enriched Jobs in a stated population that have one particular Matched Canonical Skill. Because a Job may have multiple Skills, prevalence values are independent and do not form a 100% composition.
_Avoid_: Skill share, market demand share

**Taxonomy Operator**:
A human using the trusted local product for occasional direct correction when automated classification cannot produce an acceptable result.
_Avoid_: Routine queue reviewer, release publisher

## Operations

**Operations Dashboard**:
The internal operator surface for observing collection, enrichment, and governed Skill health. Its Skill distribution describes the Published Job Corpus and is not labor-market trend analytics.
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
