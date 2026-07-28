# Treat the Dashboard as an operational corpus snapshot

Status: accepted

The Dashboard is an internal Operations Dashboard, not a labor-market analytics product. Its Job Taxonomy and Skill metrics describe the retained Published Job Corpus: all non-deleted acquired Jobs, including source listings that may have expired. “Current” refers to current canonical state, not an active job opening.

This boundary keeps overview, assignment coverage, and enrichment operations on one explicit population and avoids silently presenting crawler retention data as current market demand. Active-listing, date-range, geography, source, and market-trend analysis require a separate explicit analytics contract rather than changing the operational denominator.
