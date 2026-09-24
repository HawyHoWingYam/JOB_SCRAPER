# Design

Extend the existing governed search-card schema and response builder with raw
experience fields plus provenance when available. A shared frontend formatter
returns compact and detailed labels for both Job Browser and Job Detail.

Keep `_experience_windows_overlap_clause` as the single backend membership
policy. Semantic/hybrid candidates, facets, and export continue to reuse it.
Issue #61 supplies inferred-window provenance; until present, no estimate is
fabricated from level alone.
