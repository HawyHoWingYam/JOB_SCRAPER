# Use classification-bound keyword sweeps for OfferToday listing

Status: accepted

OfferToday category browse and keyword search expose materially different jobs.
New OfferToday listing plans therefore replace the empty-keyword category target
with 36 deterministic classification-bound targets (`A`–`Z`, `0`–`9`) for one
selected top-level classification. This preserves truthful classification scope
while accepting a larger, explicit workload: the operator reviews Page Depth,
the `36 × depth` estimate, and a finite Run Page Cap. Only OfferToday is exempt
from the generic 5,000-page system ceiling; JobsDB and CTgoodjobs remain
unchanged. Historical empty-keyword plans stay readable but are never rewritten
or emitted by new compilation.
