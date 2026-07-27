# Technical design

Implement `CurrentTaxonomyStore` from the parent design. Convert composite
revision-scoped identities to stable ordinary node IDs, keep hierarchy and
assignment integrity, and treat mapping absence as `None` rather than a blocker.
Delete unresolved per-item review rows; future work selection derives from
missing/current assignment and batch state. Preserve Candidate/Mention evidence
for Skills without revision columns.
