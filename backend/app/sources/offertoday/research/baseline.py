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


_IDENTITY_EVIDENCE_CONFLICT_CLASSIFICATIONS = frozenset(
    {
        "encrypted_job_id_alias_conflict",
        "job_id_alias_conflict",
        "source_job_id_mismatch",
    }
)


def _content_hash(value: dict[str, Any]) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _canonical_nonblank(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    canonical = value.strip()
    return canonical or None


def build_baseline_snapshot(
    *,
    listings: Sequence[StagedListingSnapshot],
    jobs: Sequence[PublishedJobSnapshot],
) -> BaselineSnapshot:
    canonical_staged_ids = [
        _canonical_nonblank(row.source_job_id) for row in listings
    ]
    valid_staged_ids = [
        source_job_id
        for source_job_id in canonical_staged_ids
        if source_job_id is not None
    ]
    staged_ids = set(valid_staged_ids)
    published_ids = {
        source_job_id
        for job in jobs
        if (source_job_id := _canonical_nonblank(job.source_job_id)) is not None
    }
    pending_rows = [row for row in listings if row.detail_status == "pending"]
    pending_ids = {
        source_job_id
        for row in pending_rows
        if (source_job_id := _canonical_nonblank(row.source_job_id)) is not None
    }
    pending_with_job = [
        row
        for row in pending_rows
        if _canonical_nonblank(row.source_job_id) in published_ids
    ]

    encrypted_ids_by_job_id: dict[str, set[str]] = {}
    job_ids_by_encrypted_id: dict[str, set[str]] = {}
    for row in listings:
        source_job_id = _canonical_nonblank(row.source_job_id)
        encrypted_job_id = _canonical_nonblank(row.encrypted_job_id)
        if source_job_id is None or encrypted_job_id is None:
            continue
        encrypted_ids_by_job_id.setdefault(source_job_id, set()).add(
            encrypted_job_id
        )
        job_ids_by_encrypted_id.setdefault(encrypted_job_id, set()).add(
            source_job_id
        )

    status_counts = Counter(row.detail_status for row in listings)
    error_counts = Counter(
        row.detail_error_classification
        for row in listings
        if row.detail_error_classification
    )
    identity_error_counts = Counter(
        row.identity_error_classification
        for row in listings
        if row.identity_error_classification
    )
    identity_evidence_conflict_ids = {
        source_job_id
        for row in listings
        if row.identity_error_classification
        in _IDENTITY_EVIDENCE_CONFLICT_CLASSIFICATIONS
        and (source_job_id := _canonical_nonblank(row.source_job_id)) is not None
    }
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
    identity_mapping_conflict_ids.update(identity_evidence_conflict_ids)

    values = {
        "staged_rows": len(listings),
        "distinct_staged_ids": len(staged_ids),
        "invalid_source_job_id_rows": len(listings) - len(valid_staged_ids),
        "published_jobs": len(jobs),
        "distinct_staged_unpublished_ids": len(staged_ids - published_ids),
        "pending_rows": len(pending_rows),
        "distinct_pending_ids": len(pending_ids),
        "pending_rows_with_published_job": len(pending_with_job),
        "distinct_published_ids_with_pending_rows": len(
            {
                source_job_id
                for row in pending_with_job
                if (
                    source_job_id := _canonical_nonblank(row.source_job_id)
                )
                is not None
            }
        ),
        "published_partial_jobs": sum(not job.is_complete for job in jobs),
        "duplicate_staging_rows": len(valid_staged_ids) - len(staged_ids),
        "missing_encrypted_job_id_rows": sum(
            _canonical_nonblank(row.encrypted_job_id) is None
            for row in listings
        ),
        "identity_mapping_conflict_ids": tuple(
            sorted(identity_mapping_conflict_ids)
        ),
        "identity_evidence_conflict_ids": tuple(
            sorted(identity_evidence_conflict_ids)
        ),
        "identity_error_classifications": dict(
            sorted(identity_error_counts.items())
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
        sorted(
            {
                source_job_id
                for job in jobs
                if (
                    source_job_id := _canonical_nonblank(job.source_job_id)
                )
                is not None
            }
        )
    )
    staged_ids = {
        source_job_id
        for row in listings
        if (source_job_id := _canonical_nonblank(row.source_job_id)) is not None
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
