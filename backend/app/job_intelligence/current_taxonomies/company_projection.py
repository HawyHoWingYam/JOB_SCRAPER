from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.job_intelligence.current_taxonomies.contracts import (
    CurrentCompanyIndustryInput,
    ReplaceCurrentCompanyIndustriesCommand,
)
from app.job_intelligence.current_taxonomies.store import CurrentTaxonomyStore
from app.job_intelligence.foundation import normalized_content_hash
from app.messaging.topics import STREAM_JOB_LIFECYCLE
from app.models.current_taxonomy import (
    CurrentCompanyIndustryAssignment,
    CurrentSourceTaxonomyMapping,
    CurrentTaxonomyNodeRecord,
)
from app.repositories.event_outbox_repository import EventOutboxRepository
from app.utils.time import utc_now


@dataclass(frozen=True)
class CurrentCompanyIndustryProjectionResult:
    company_id: UUID
    state: str
    changed: bool
    taxonomy_codes: tuple[str, ...]


def _field(canonical_job: object, name: str) -> Any:
    if isinstance(canonical_job, Mapping):
        return canonical_job.get(name)
    return getattr(canonical_job, name, None)


def _aware_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _captured_at(canonical_job: object, raw_data: Mapping[str, Any]) -> datetime:
    for value in (
        _field(canonical_job, "captured_at"),
        raw_data.get("captured_at"),
        raw_data.get("scraped_at"),
    ):
        captured_at = _aware_datetime(value)
        if captured_at is not None:
            return captured_at
    return utc_now()


def _display_label(labels: Mapping[str, object]) -> str:
    for key in ("en", "en_HK", "zh_HK", "zh"):
        value = str(labels.get(key) or "").strip()
        if value:
            return value
    return next(
        (str(value).strip() for value in labels.values() if str(value).strip()),
        "",
    )


def project_current_company_industry(
    db: Session,
    company_id: UUID,
    canonical_job: object,
    *,
    outbox_repository: EventOutboxRepository | None = None,
) -> CurrentCompanyIndustryProjectionResult | None:
    source_site = str(_field(canonical_job, "source_site") or "").strip().lower()
    if source_site != "offertoday":
        return None
    raw_data = _field(canonical_job, "raw_data")
    if not isinstance(raw_data, Mapping):
        return None
    label = raw_data.get("company_industry")
    if not isinstance(label, str) or not label.strip():
        industry = raw_data.get("industry")
        label = industry.get("name") if isinstance(industry, Mapping) else None
    if not isinstance(label, str) or not label.strip():
        return None
    raw_label = label.strip()
    normalized_label = " ".join(raw_label.split()).casefold()
    mapping_rows = tuple(
        db.scalars(
            select(CurrentSourceTaxonomyMapping)
            .where(
                CurrentSourceTaxonomyMapping.taxonomy == "company_industry",
                CurrentSourceTaxonomyMapping.source_site == source_site,
                CurrentSourceTaxonomyMapping.source_key
                == f"label:{normalized_label}",
            )
            .order_by(CurrentSourceTaxonomyMapping.target_code)
        )
    )
    if not mapping_rows:
        return CurrentCompanyIndustryProjectionResult(
            company_id=company_id,
            state="unassigned",
            changed=False,
            taxonomy_codes=(),
        )

    nodes = tuple(
        db.scalars(
            select(CurrentTaxonomyNodeRecord).where(
                CurrentTaxonomyNodeRecord.taxonomy == "company_industry",
                CurrentTaxonomyNodeRecord.is_active.is_(True),
            )
        )
    )
    by_code = {node.code: node for node in nodes}
    target_codes = tuple(
        dict.fromkeys(
            row.target_code for row in mapping_rows if row.target_code in by_code
        )
    )
    if not target_codes:
        return CurrentCompanyIndustryProjectionResult(
            company_id=company_id,
            state="unassigned",
            changed=False,
            taxonomy_codes=(),
        )

    captured_at = _captured_at(canonical_job, raw_data)
    source_job_id = str(_field(canonical_job, "source_job_id") or "").strip()
    evidence_hash = normalized_content_hash(
        {
            "company_id": str(company_id),
            "source_site": source_site,
            "source_job_id": source_job_id,
            "raw_label": raw_label,
            "target_codes": target_codes,
        }
    )
    existing = tuple(
        db.scalars(
            select(CurrentCompanyIndustryAssignment)
            .where(CurrentCompanyIndustryAssignment.company_id == company_id)
            .order_by(
                CurrentCompanyIndustryAssignment.is_primary.desc(),
                CurrentCompanyIndustryAssignment.taxonomy_code,
            )
        )
    )
    if tuple(row.taxonomy_code for row in existing) == target_codes and all(
        row.evidence_hash == evidence_hash for row in existing
    ):
        return CurrentCompanyIndustryProjectionResult(
            company_id=company_id,
            state="assigned",
            changed=False,
            taxonomy_codes=target_codes,
        )

    mapping_by_code = {row.target_code: row for row in mapping_rows}
    CurrentTaxonomyStore(db).replace_company_industries(
        ReplaceCurrentCompanyIndustriesCommand(
            company_id=company_id,
            assignments=tuple(
                CurrentCompanyIndustryInput(
                    taxonomy_code=code,
                    method="source_mapping",
                    provenance={
                        "source_site": source_site,
                        "source_job_id": source_job_id,
                        "raw_label": raw_label,
                        "mapping": {
                            "source_key": mapping_by_code[code].source_key,
                            "target_code": code,
                        },
                    },
                    evidence_hash=evidence_hash,
                    breadcrumb=_breadcrumb(by_code[code], by_code),
                    is_primary=index == 0,
                    primary_basis="source_mapping" if index == 0 else None,
                    captured_at=captured_at,
                )
                for index, code in enumerate(target_codes)
            ),
        )
    )
    (outbox_repository or EventOutboxRepository()).enqueue(
        db,
        topic=STREAM_JOB_LIFECYCLE,
        aggregate_type="company",
        aggregate_id=str(company_id),
        event_type="company.industry_changed",
        payload={
            "company_id": str(company_id),
            "taxonomy_codes": list(target_codes),
            "invalidate": ["company-industry-read-model", "job-search"],
        },
        source_service="company-industry-projection",
        auto_commit=False,
    )
    return CurrentCompanyIndustryProjectionResult(
        company_id=company_id,
        state="assigned",
        changed=True,
        taxonomy_codes=target_codes,
    )


def _breadcrumb(
    leaf: CurrentTaxonomyNodeRecord,
    by_code: dict[str, CurrentTaxonomyNodeRecord],
) -> dict[str, object]:
    chain: list[CurrentTaxonomyNodeRecord] = []
    cursor: CurrentTaxonomyNodeRecord | None = leaf
    visited: set[str] = set()
    while cursor is not None and cursor.code not in visited:
        visited.add(cursor.code)
        chain.append(cursor)
        cursor = by_code.get(cursor.parent_code) if cursor.parent_code else None
    return {
        node.level: {
            "code": node.code,
            "label": _display_label(node.labels),
        }
        for node in reversed(chain)
    }


__all__ = [
    "CurrentCompanyIndustryProjectionResult",
    "project_current_company_industry",
]
