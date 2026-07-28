# Design: Dashboard chart Jobs drill-down

## Identity boundary

Extend each concrete taxonomy and Skill stats row, including concrete rows revealed under expanded `Other`, with its stable canonical code. Keep labels, paths, counts, shares, and Dashboard buckets as presentation data only. The aggregate `Other` control has no code because it represents multiple nodes.

## Navigation contract

Define one serializable route-filter representation for canonical Subcategory and Skill IDs. The Dashboard action navigates to the Jobs view with that representation; the application route parser validates it and seeds `JobBrowser` structured filters. The Jobs view must reconstruct the same filter after refresh and preserve the existing unfiltered `#jobs` route.

Prefer the smallest public route shape that round-trips the existing structured-filter contract. Do not pass database labels as lookup keys or keep the filter only in React memory.

## Interaction and compatibility

Render concrete chart rows as semantic actions with accessible names that include the label and Job count. Keep `Other` as a non-action aggregate. Existing FilterPanel editing, search requests, browser navigation, and direct Jobs navigation remain compatible.

## Dependency and rollback

Land after the parent stats response exposes canonical codes and stabilizes its chart contracts. Response identity fields are additive. Route parsing and chart actions can be rolled back without reverting the corrected stats semantics.
