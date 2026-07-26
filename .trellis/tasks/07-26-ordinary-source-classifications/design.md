# Technical design

Implement the `SourceClassificationRegistry` interface defined in the parent
`design.md`. Use an ordinary current table keyed by `(source_site,
classification_id)`, retain captured Job path snapshots without catalog revision
FKs, and keep Source query compilation behind adapter seams. A complete sync may
mark missing roots inactive; partial/failed sync may not. Temporary legacy reads
are permitted only inside a tested transition adapter deleted before completion.
