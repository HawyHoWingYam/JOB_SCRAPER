from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Sequence
from typing import Any

from app.sources.offertoday.research.contracts import (
    BaselineSnapshot,
    PublishedJobSnapshot,
    ResearchRunStartInventory,
    StagedListingSnapshot,
)


def _content_hash(value: dict[str, Any]) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_baseline_snapshot(
    *,
    listings: Sequence[StagedListingSnapshot],
    jobs: Sequence[PublishedJobSnapshot],
) -> BaselineSnapshot:
    staged_ids = {row.source_job_id for row in listings if row.source_job_id}
    published_ids = {job.source_job_id for job in jobs if job.source_job_id}
    pending_rows = [row for row in listings if row.detail_status == "pending"]
    pending_ids = {
        row.source_job_id for row in pending_rows if row.source_job_id
    }
    pending_with_job = [
        row for row in pending_rows if row.source_job_id in published_ids
    ]

    encrypted_ids_by_job_id: dict[str, set[str]] = {}
    job_ids_by_encrypted_id: dict[str, set[str]] = {}
    for row in listings:
        if not row.source_job_id or not row.encrypted_job_id:
            continue
        encrypted_ids_by_job_id.setdefault(row.source_job_id, set()).add(
            row.encrypted_job_id
        )
        job_ids_by_encrypted_id.setdefault(row.encrypted_job_id, set()).add(
            row.source_job_id
        )

    status_counts = Counter(row.detail_status for row in listings)
    error_counts = Counter(
        row.detail_error_classification
        for row in listings
        if row.detail_error_classification
    )
    identity_mapping_conflict_ids = {
        job_id
        for job_id, encrypted_ids in encrypted_ids_by_job_id.items()
        if len(encrypted_ids) > 1
    }
    identity_mapping_conflict_ids.update(
        job_id
        for job_ids in job_ids_by_encrypted_id.values()
        if len(job_ids) > 1
        for job_id in job_ids
    )

    values = {
        "staged_rows": len(listings),
        "distinct_staged_ids": len(staged_ids),
        "published_jobs": len(jobs),
        "distinct_staged_unpublished_ids": len(staged_ids - published_ids),
        "pending_rows": len(pending_rows),
        "distinct_pending_ids": len(pending_ids),
        "pending_rows_with_published_job": len(pending_with_job),
        "distinct_published_ids_with_pending_rows": len(
            {row.source_job_id for row in pending_with_job}
        ),
        "published_partial_jobs": sum(not job.is_complete for job in jobs),
        "duplicate_staging_rows": len(listings) - len(staged_ids),
        "missing_encrypted_job_id_rows": sum(
            not row.encrypted_job_id for row in listings
        ),
        "identity_mapping_conflict_ids": tuple(
            sorted(identity_mapping_conflict_ids)
        ),
        "detail_status_rows": dict(sorted(status_counts.items())),
        "detail_error_classifications": dict(sorted(error_counts.items())),
    }
    return BaselineSnapshot(**values, data_hash=_content_hash(values))


def build_run_start_inventory(
    *,
    listings: Sequence[StagedListingSnapshot],
    jobs: Sequence[PublishedJobSnapshot],
) -> ResearchRunStartInventory:
    published_ids = tuple(
        sorted({job.source_job_id for job in jobs if job.source_job_id})
    )
    staged_ids = {
        row.source_job_id for row in listings if row.source_job_id
    }
    staged_unpublished_ids = tuple(sorted(staged_ids - set(published_ids)))
    values = {
        "published_job_ids": list(published_ids),
        "staged_unpublished_job_ids": list(staged_unpublished_ids),
    }
    return ResearchRunStartInventory(
        published_job_ids=published_ids,
        staged_unpublished_job_ids=staged_unpublished_ids,
        data_hash=_content_hash(values),
    )
