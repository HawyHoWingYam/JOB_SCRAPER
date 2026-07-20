# CP10 live rollout evidence — 2026-07-20

## Decision

Checkpoint 10 is complete for the approved Crawl Control boundary. The live
`jobsdb` schema is at `20260720_210000`, the fenced Crawl Control reset
preserved the Published Job Corpus and unrelated data, all three initial Source
Catalog Revisions are active, the three bounded smoke plans consumed immutable
authority, and every smoke Crawl Job is terminal with zero active Crawl Jobs.

OfferToday did not bypass its upstream IP block. Its bounded plan reached the
truthful `manual_action_required/ip_blocked` state and was then cancelled
through the acknowledged `cancelling -> cancelled` contract. This proves the
reviewed authority, manual-action, and cancellation paths without retrying,
switching networks, issuing a categoryless query, or starting detail work.

## Release identity and rollback asset

- Approval: `批准执行 CP10 live rollout`, recorded for actor `user` at
  `2026-07-20T16:04:03Z`.
- Application commit: `5585b968c66e8ceb37993426e3c4900c2baa22d1`.
- Compose configuration hash:
  `5292e32eeb92f3cdca09286308097d2773c7cd4c8f539b5196f444278bd2733c`.
- Target/live Alembic revision: `20260720_210000`.
- Backup:
  `runtime/crawl-control-cutover/20260720T144720Z/jobsdb-crawl-control-20260720T144720Z-3a2fd136.dump`.
- Backup SHA-256:
  `1d1b4274c5c4e4f421269e29028e03a2ebb498d9c61d3fa2d7b6f4849a856280`.
- Job Intelligence rebuild, pointer switch, embedding rebuild, and writer
  reopening remained outside this approval and were not performed.

The backup and compatible release identity remain the post-commit rollback
asset and must be retained through the agreed rollback window.

## Initial published Catalogs

| Source | Active revision | Fingerprint | Nodes |
| --- | --- | --- | ---: |
| JobsDB | `3ca91954-0e00-4323-8bf1-f69b84f11d4c` | `73d501a4ff3345204e566662793cba54002b026b77f7074fa8490a7220355fbc` | 25 |
| CTgoodjobs | `587b4f32-4087-4d87-8d0b-ceba4e5c5977` | `19a65eb4907b4beed2aeb2c888adf54d9b85d33c55236fef52a930044201fc37` | 28 |
| OfferToday | `e2f6f849-d696-4141-a14e-429373cb417b` | `26ef414d002013e007308863e201330bd06637144faef815567aea2bf3411e07` | 493 |

The live Source Catalog summary and each published-tree endpoint returned the
same revision IDs, fingerprints, and node counts after service restart.

## Fenced reset

- Ready dry-run payload hash:
  `f2a14311b8fad7b69b7061a1d65528c20f5ce786efe1531e1e1a4bbb59240844`.
- Reviewed report hash:
  `9186c6c57640100aafd9c6dcba60138cfcc97e69111e6d9687fdf09186d2e90a`.
- Execute payload hash:
  `438b1c52e2c79b1e4c1054d747845e7880308798eed0228f6d95c3a635bc1093`.
- Dry-run was `ready=true`, saw all 11 known writers stopped, three active
  Catalogs, zero active Crawl Jobs, and zero pending crawl outbox rows.
- The reset deleted 321 Crawl Jobs, 66,445 Crawl Job events, 165 execution
  rows, 51,523 listing-staging rows, and the remaining approved Crawl Control
  rows. It deleted no `event_outbox` row because no pending crawl command
  remained.
- Preserve assertions retained 17,596 Jobs, 4,657 Companies, 8 enrichment
  runs, 4,042 embeddings, three Source Catalog revisions/pointers, and 10,310
  unrelated/published outbox rows.

The execute artifact carries the same backup ID, report hash, preserved counts,
and outbox count as the reviewed ready report.

## Bounded smoke plans

| Source | Plan / fingerprint | Crawl Job | Scope and cap | Result |
| --- | --- | --- | --- | --- |
| JobsDB | `8eb6ebdf-a6f1-4709-8c01-678cc483e471` / `00d324fddff9c52607d5fd514762f4d0853e8d7296c85a7749095959b10e1585` | `bae9ae01-6e00-49a5-bd28-a09a938c68b1` | exact `jobsdb:6281`; one `jobsdb.classification` target; page depth/run cap `1/1` | `completed`; 32 listing IDs staged; no detail plan or detail execution |
| CTgoodjobs | `36576a50-663d-4837-9c3f-ab0990d446b1` / `45398b99b00bfecf4705d2e28b24eb344f4c2714444d568e193152e36ce678c1` | `0cc6e05e-68d8-4691-97ed-ed9ee22fdd34` | exact `ctgoodjobs:021`; one headed published-path target; page depth/run cap `1/1` | `completed`; one page and 49 listing IDs staged; no detail plan or detail execution |
| OfferToday | `86c9c6c0-b005-4082-bc57-c20765f803e9` / `3cf75ceb14121260d95f3c50ee5d2baca7ee275f1fc79ed41009a24cfc0e81c8` | `7416180f-bd90-49f6-a5dd-ca0c8da98f57` | exact `offertoday:118000`; one `offertoday.category` target with `category_code=118000`, empty keyword; page depth/run cap `1/1` | `manual_action_required/ip_blocked`, then acknowledged `cancelled`; zero pages and no detail work |

All three Dispatch Plans are `consumed` and point to the listed Crawl Job,
fingerprint, active Catalog Revision, one Query Target, and bounded settings.
The compatibility `request_payload` is explicitly non-authoritative in the
recorded events.

Earlier CTgoodjobs profile-lock/display attempts were cancelled and received
terminal acknowledgements before the final headed smoke. The temporary Xvfb API
was stopped, and the standard `backend-api` service was restored.

## Final live verification

At `2026-07-20T16:28:35Z`:

- `GET /health` returned `healthy` for `backend-api`.
- `backend-api`, `scheduler-worker`, `ingest-worker`, `enrichment-worker`,
  `embedding-worker`, and `scrapyd` were running; API and Scrapyd health checks
  were healthy.
- API totals for `queued`, `dispatching`, `running`, `cancelling`, and
  `manual_action_required` Crawl Jobs were each zero.
- SQL independently returned schema `20260720_210000`, Jobs 17,596, Companies
  4,657, enrichment runs 8, embeddings 4,042, active Catalogs 3, outbox rows
  10,310, and active Crawl Jobs 0.
- `crawl_job_listings.crawl_job_id -> crawl_jobs.id` is validated and uses
  `ON DELETE CASCADE`.
- OfferToday cancellation events were appended at
  `2026-07-20T16:24:32.207310Z` (`crawl.cancel_requested`) and
  `2026-07-20T16:24:32.225222Z` (`crawl.cancelled`), with zero released detail
  rows.

## Artifact index

The retained operator artifacts live under
`runtime/crawl-control-cutover/20260720T144720Z/`. The acceptance anchors are:

- `release-identity.json`
- `initial-catalogs-published.json`
- `crawl-control-dry-run-ready.json`
- `crawl-control-reset.json`
- `jobsdb-bounded-smoke-{plan,dispatch,job,events}.json`
- `ctgoodjobs-bounded-smoke-{plan-headed,dispatch-headed,job-headed,events-headed}.json`
- `offertoday-bounded-smoke-{plan,dispatch,job,events}.json`
- `offertoday-bounded-smoke-cancel.json`
- `post-rollout-verification.json`

Secrets, cookies, response bodies, session state, and unbounded ID lists are not
included in this evidence document.
