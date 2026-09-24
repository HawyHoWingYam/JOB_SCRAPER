# Design

First separate ordinary enrichment from Jev: `AIEnrichmentService` sends one
ordinary insight request and always projects extracted Skills with
`source="ai-extraction"`. No Jev service is constructed in that flow.

Current taxonomy reconciliation remains authoritative for mapping known Skills
and retaining unknown mentions. Add only durable projection/version state that
is needed to preserve an AI baseline independently from later Jev and operator
overlays. Reuse existing Job/evidence fingerprints and provenance structures;
do not create a second taxonomy.

Later manual Jev processing writes a correction bound to the same evidence
identity, then rebuilds the effective projection. Operator dispositions remain
highest priority. Reads expose current effective assignments plus traceable
status, while baseline and correction history remain auditable.

Tests use public enrichment service/API seams and current-taxonomy reads. A fake
ordinary extractor counts its request; database assertions prove zero Jev side
effects. Persistence and locking additions use isolated PostgreSQL tests.
