# OfferToday practical IT production crawl parent design

The parent no longer coordinates research phases. It owns one integration
boundary:

```text
cursor-correct IT listing
  -> bulk incremental target classification
  -> post-listing detail execution
  -> completed/partial observability
```

The old artifact/candidate/denominator/canary/soak architecture is not a
compatibility requirement. Shared cursor, identity, response, staging, and
detail code remains production infrastructure; research-only callers stay
outside the production path and replay machinery remains available for history.
