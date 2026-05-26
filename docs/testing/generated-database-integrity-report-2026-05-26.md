# Database Integrity Report

- Generated at: 2026-05-26T04:47:58.277938+00:00
- Status: degraded
- Expected tables: 25
- Observed tables: 25
- Missing expected tables: 0
- Advisory schema findings: 5

## Issues

- crawl_job_listings has 5436 staged rows without published_job_id
- crawl_job_listings detail_status pending has 5386 rows
- embeddings missing for 1024 current jobs

## Schema Drift

| Metric | Value |
| --- | ---: |
| Expected tables | 25 |
| Observed tables | 25 |
| Missing expected tables | 0 |
| Timezone-aware timestamp columns | 14 |
| Timezone-naive timestamp columns | 53 |

## Operational Metrics

- Staged unpublished rows: 5436
- Outbox retrying rows: 0
- Missing current embeddings: 1024

| Metric | Value |
| --- | ---: |
| Total staged rows | 5436 |
| Staged published rows | 0 |
| Staged unpublished rows | 5436 |
| Published jobs | 1375 |
| Staged-to-published ratio | 3.95 |
| Outbox retrying rows | 0 |
| Oldest outbox pending age seconds | 0 |
| Taxonomy seed tables empty | False |
| Missing current embeddings | 1024 |
| Vector index present | False |
| Visible taxonomy nodes without distinct-job count | 0 |
| Schedule executions missing request snapshots | 0 |

## Detail Status Counts

- `completed`: 50
- `pending`: 5386

## Outbox Status Counts

- `published`: 3092

## Advisory Findings

- `crawl_job_listings_crawl_job_id_fk`: crawl_job_listings.crawl_job_id is not enforced as a database foreign key
- `crawl_job_listings_last_detail_crawl_job_id_fk`: crawl_job_listings.last_detail_crawl_job_id is not enforced as a database foreign key
- `crawl_job_listings_published_job_id_fk`: crawl_job_listings.published_job_id is not enforced as a database foreign key
- `event_outbox_domain_event_unique_key`: event_outbox has no database uniqueness guard for duplicate domain events
- `job_embeddings_embedding_ann_index`: job_embeddings.embedding has no ANN vector index
