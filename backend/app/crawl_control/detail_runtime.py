from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterator
from uuid import UUID

from sqlalchemy.orm import Session

from app.crawl_control.contracts import (
    DetailBacklogSnapshotV1,
    DetailSettingsV1,
)
from app.crawl_control.dispatch_plan_contracts import (
    DispatchPlanContentV1,
    DispatchPlanTargetRowV1,
    DispatchPlanTargetV1,
    ExecutionAuthorityV1,
    ExecutionResumeContextV1,
)
from app.crawl_control.errors import (
    BacklogSafetyCapExceededError,
    DispatchPlanStaleError,
)
from app.models.crawl_job_listing import CrawlJobListing
from app.repositories.crawl_job_listing_repository import (
    CrawlJobListingRepository,
)
from app.source_catalog.domain import payload_fingerprint


DEFAULT_DETAIL_BACKLOG_SAFETY_CAP = 100_000


@dataclass(frozen=True, slots=True)
class FrozenDetailBacklog:
    content: DispatchPlanContentV1
    targets: tuple[DispatchPlanTargetV1, ...]


@dataclass(frozen=True, slots=True)
class DetailBacklogPreview:
    eligible_target_count: int
    selected_target_count: int
    absolute_safety_cap: int


@dataclass(frozen=True, slots=True)
class DetailRuntimeTarget:
    source_job_id: str
    selection_order: int
    listing_ids: tuple[UUID, ...]
    eligibility_statuses: tuple[str, ...]
    eligibility_fingerprints: tuple[str, ...]
    runtime_identity_fingerprints: tuple[str, ...]

    def __post_init__(self) -> None:
        row_count = len(self.listing_ids)
        if not row_count or any(
            len(values) != row_count
            for values in (
                self.eligibility_statuses,
                self.eligibility_fingerprints,
                self.runtime_identity_fingerprints,
            )
        ):
            raise ValueError("Detail runtime row authority is inconsistent")
        if any(
            len(fingerprint) != 64
            or any(character not in "0123456789abcdef" for character in fingerprint)
            for fingerprints in (
                self.eligibility_fingerprints,
                self.runtime_identity_fingerprints,
            )
            for fingerprint in fingerprints
        ):
            raise ValueError("Detail runtime row fingerprint is invalid")


@dataclass(frozen=True, slots=True)
class DetailRuntimePlan:
    crawl_job_id: UUID
    dispatch_plan_id: UUID
    dispatch_plan_fingerprint: str
    source_site: str
    catalog_revision_id: UUID
    catalog_revision_fingerprint: str
    crawl_mode: str
    backlog_scope_kind: str
    source_listing_crawl_job_id: UUID | None
    classification_ids: tuple[str, ...]
    snapshot_cutoff_at: datetime
    eligible_target_count: int
    selected_target_count: int
    selected_row_count: int
    complete_run_cap: int
    membership_fingerprint: str
    targets: tuple[DetailRuntimeTarget, ...]
    resume_context: ExecutionResumeContextV1 | None = None

    def __post_init__(self) -> None:
        if self.selected_target_count != len(self.targets):
            raise ValueError("Detail runtime target count is inconsistent")
        if self.selected_row_count != sum(
            len(target.listing_ids) for target in self.targets
        ):
            raise ValueError("Detail runtime row membership count is inconsistent")
        if self.selected_target_count > self.complete_run_cap:
            raise ValueError("Detail runtime exceeds its complete-run cap")

    def iter_segments(
        self,
        segment_size: int,
    ) -> Iterator[tuple[DetailRuntimeTarget, ...]]:
        size = int(segment_size)
        if size < 1:
            raise ValueError("Detail Recovery Segment size must be positive")
        for offset in range(0, len(self.targets), size):
            yield self.targets[offset : offset + size]

    @property
    def resume_statuses(self) -> tuple[str, ...]:
        if self.resume_context is None:
            return ()
        return self.resume_context.detail_statuses

    def audit_payload(self) -> dict[str, object]:
        return {
            "dispatch_plan_id": str(self.dispatch_plan_id),
            "dispatch_plan_fingerprint": self.dispatch_plan_fingerprint,
            "catalog_revision_id": str(self.catalog_revision_id),
            "catalog_revision_fingerprint": self.catalog_revision_fingerprint,
            "detail_backlog_scope": self.backlog_scope_kind,
            "detail_snapshot_cutoff_at": self.snapshot_cutoff_at.isoformat(),
            "detail_snapshot_eligible_target_count": self.eligible_target_count,
            "detail_snapshot_selected_target_count": self.selected_target_count,
            "detail_snapshot_selected_row_count": self.selected_row_count,
            "detail_run_cap": self.complete_run_cap,
            "request_payload_authoritative": False,
        }


class DetailBacklogSnapshotBuilder:
    """Freeze deterministic detail eligibility without mutating staging rows."""

    def __init__(
        self,
        *,
        repository: CrawlJobListingRepository | None = None,
        absolute_safety_cap: int = DEFAULT_DETAIL_BACKLOG_SAFETY_CAP,
    ) -> None:
        self.repository = repository or CrawlJobListingRepository()
        self.absolute_safety_cap = max(int(absolute_safety_cap), 1)

    def freeze(
        self,
        db: Session,
        *,
        content: DispatchPlanContentV1,
        cutoff_at: datetime,
    ) -> FrozenDetailBacklog:
        settings = content.detail_settings
        if content.crawl_phase != "detail" or settings is None:
            raise ValueError("Only detail Dispatch Plans have backlog membership")
        if settings.backlog_snapshot is not None:
            raise ValueError("Detail Dispatch Plan backlog is already frozen")

        query_args = self._query_args(content)
        rows = self.repository.list_detail_candidates(
            db,
            source_site=content.source_site,
            statuses=None,
            eligible_at_or_before=cutoff_at,
            limit=None,
            **query_args,
        )
        grouped_rows = self._group_rows(rows)
        eligible_target_count = len(grouped_rows)
        if settings.limit.kind == "entire_snapshot":
            selected_target_count = eligible_target_count
        else:
            selected_target_count = min(
                eligible_target_count,
                settings.limit.detail_run_cap,
            )
        if selected_target_count > self.absolute_safety_cap:
            raise BacklogSafetyCapExceededError(
                eligible_target_count=eligible_target_count,
                selected_target_count=selected_target_count,
                absolute_safety_cap=self.absolute_safety_cap,
            )

        selected_groups = tuple(grouped_rows.items())[:selected_target_count]
        targets = tuple(
            self._target(
                content.source_site,
                source_job_id=source_job_id,
                rows=target_rows,
                selection_order=selection_order,
            )
            for selection_order, (source_job_id, target_rows) in enumerate(
                selected_groups
            )
        )
        membership_fingerprint = detail_membership_fingerprint(targets)
        snapshot = DetailBacklogSnapshotV1(
            cutoff_at=cutoff_at,
            eligible_target_count=eligible_target_count,
            selected_target_count=len(targets),
            selected_row_count=sum(len(target.rows) for target in targets),
            absolute_safety_cap=self.absolute_safety_cap,
            membership_fingerprint=membership_fingerprint,
        )
        frozen_settings = DetailSettingsV1.model_validate(
            {
                **settings.model_dump(mode="json"),
                "backlog_snapshot": snapshot.model_dump(mode="json"),
            }
        )
        frozen_content = DispatchPlanContentV1.model_validate(
            {
                **content.model_dump(mode="json"),
                "detail_settings": frozen_settings.model_dump(mode="json"),
            }
        )
        return FrozenDetailBacklog(content=frozen_content, targets=targets)

    def preview(
        self,
        db: Session,
        *,
        content: DispatchPlanContentV1,
        eligible_at_or_before: datetime,
    ) -> DetailBacklogPreview:
        """Count current eligibility without freezing membership or writing rows."""
        settings = content.detail_settings
        if content.crawl_phase != "detail" or settings is None:
            raise ValueError("Only detail configurations have a backlog preview")
        if settings.backlog_snapshot is not None:
            raise ValueError("Automation review cannot consume a frozen snapshot")
        rows = self.repository.list_detail_candidates(
            db,
            source_site=content.source_site,
            statuses=None,
            eligible_at_or_before=eligible_at_or_before,
            limit=None,
            **self._query_args(content),
        )
        eligible_target_count = len(self._group_rows(rows))
        selected_target_count = (
            eligible_target_count
            if settings.limit.kind == "entire_snapshot"
            else min(eligible_target_count, settings.limit.detail_run_cap)
        )
        return DetailBacklogPreview(
            eligible_target_count=eligible_target_count,
            selected_target_count=selected_target_count,
            absolute_safety_cap=self.absolute_safety_cap,
        )

    @staticmethod
    def _query_args(content: DispatchPlanContentV1) -> dict[str, Any]:
        settings = content.detail_settings
        assert settings is not None
        backlog_scope = settings.backlog_scope
        if backlog_scope.kind == "source_backlog":
            return {
                "source_listing_crawl_job_id": None,
                "detail_scope": (
                    "global" if content.source_site == "offertoday" else None
                ),
                "category_ids": (),
            }
        if backlog_scope.kind == "listing_batch":
            return {
                "source_listing_crawl_job_id": (
                    backlog_scope.source_listing_crawl_job_id
                ),
                "detail_scope": (
                    "listing_batch"
                    if content.source_site == "offertoday"
                    else None
                ),
                "category_ids": (),
            }
        return {
            "source_listing_crawl_job_id": None,
            "detail_scope": None,
            "category_ids": tuple(
                selected.classification_id
                for selected in content.resolved_scope.selected_classifications
            ),
        }

    @staticmethod
    def _group_rows(
        rows: list[CrawlJobListing],
    ) -> dict[str, tuple[CrawlJobListing, ...]]:
        groups: dict[str, list[CrawlJobListing]] = {}
        for row in rows:
            source_job_id = str(row.source_job_id or "").strip()
            if source_job_id:
                groups.setdefault(source_job_id, []).append(row)
        return {
            source_job_id: tuple(group)
            for source_job_id, group in groups.items()
        }

    @staticmethod
    def _target(
        source_site: str,
        *,
        source_job_id: str,
        rows: tuple[CrawlJobListing, ...],
        selection_order: int,
    ) -> DispatchPlanTargetV1:
        frozen_rows = tuple(
            DispatchPlanTargetRowV1(
                crawl_job_listing_id=row.id,
                row_order=row_order,
                eligibility_fingerprint=detail_row_eligibility_fingerprint(row),
                eligibility_status=str(row.detail_status),
                status_metadata=_row_status_metadata(row),
            )
            for row_order, row in enumerate(rows)
        )
        target_kind = str(
            dict(rows[0].listing_payload or {}).get("detail_target_kind") or ""
        ).strip()
        return DispatchPlanTargetV1(
            source_site=source_site,
            source_job_id=source_job_id,
            selection_order=selection_order,
            eligibility_fingerprint=payload_fingerprint(
                {
                    "version": 1,
                    "source_site": source_site,
                    "source_job_id": source_job_id,
                    "rows": [
                        row.eligibility_fingerprint for row in frozen_rows
                    ],
                }
            ),
            eligibility_status=frozen_rows[0].eligibility_status,
            status_metadata={
                "row_count": len(frozen_rows),
                "detail_target_kind": target_kind or None,
            },
            rows=frozen_rows,
        )


def detail_membership_fingerprint(
    targets: tuple[DispatchPlanTargetV1, ...],
) -> str:
    return payload_fingerprint(
        [target.model_dump(mode="json") for target in targets]
    )


def build_detail_runtime_plan(
    authority: ExecutionAuthorityV1,
    *,
    expected_source_site: str,
    resume_context: ExecutionResumeContextV1 | None = None,
) -> DetailRuntimePlan:
    snapshot = authority.dispatch_plan
    content = snapshot.content
    expected_source = str(expected_source_site or "").strip().lower()
    if content.source_site != expected_source:
        raise DispatchPlanStaleError(
            "Dispatch Plan source does not match the selected worker",
            plan_id=snapshot.plan_id,
            reason="worker_source_mismatch",
        )
    settings = content.detail_settings
    if content.crawl_phase != "detail" or settings is None:
        raise DispatchPlanStaleError(
            "Dispatch Plan is not a detail execution authority",
            plan_id=snapshot.plan_id,
            reason="runtime_authority_adapter_required",
        )
    backlog_snapshot = settings.backlog_snapshot
    if backlog_snapshot is None:
        raise DispatchPlanStaleError(
            "Dispatch Plan has no finite detail backlog snapshot",
            plan_id=snapshot.plan_id,
            reason="detail_backlog_snapshot_missing",
        )
    if (
        backlog_snapshot.selected_target_count != len(snapshot.targets)
        or backlog_snapshot.selected_row_count
        != sum(len(target.rows) for target in snapshot.targets)
        or backlog_snapshot.membership_fingerprint
        != detail_membership_fingerprint(snapshot.targets)
    ):
        raise DispatchPlanStaleError(
            "Dispatch Plan detail membership does not match its snapshot",
            plan_id=snapshot.plan_id,
            reason="detail_backlog_snapshot_mismatch",
        )

    source_listing_crawl_job_id = None
    if settings.backlog_scope.kind == "listing_batch":
        source_listing_crawl_job_id = (
            settings.backlog_scope.source_listing_crawl_job_id
        )
    complete_run_cap = (
        backlog_snapshot.selected_target_count
        if settings.limit.kind == "entire_snapshot"
        else settings.limit.detail_run_cap
    )
    return DetailRuntimePlan(
        crawl_job_id=authority.crawl_job_id,
        dispatch_plan_id=snapshot.plan_id,
        dispatch_plan_fingerprint=snapshot.plan_fingerprint,
        source_site=content.source_site,
        catalog_revision_id=content.catalog_revision_id,
        catalog_revision_fingerprint=content.resolved_scope.catalog_revision_fingerprint,
        crawl_mode=settings.crawl_mode,
        backlog_scope_kind=settings.backlog_scope.kind,
        source_listing_crawl_job_id=source_listing_crawl_job_id,
        classification_ids=(
            tuple(
                selected.classification_id
                for selected in content.resolved_scope.selected_classifications
            )
            if settings.backlog_scope.kind == "crawl_scope"
            else ()
        ),
        snapshot_cutoff_at=backlog_snapshot.cutoff_at,
        eligible_target_count=backlog_snapshot.eligible_target_count,
        selected_target_count=backlog_snapshot.selected_target_count,
        selected_row_count=backlog_snapshot.selected_row_count,
        complete_run_cap=complete_run_cap,
        membership_fingerprint=backlog_snapshot.membership_fingerprint,
        targets=tuple(
            DetailRuntimeTarget(
                source_job_id=target.source_job_id,
                selection_order=target.selection_order,
                listing_ids=tuple(
                    row.crawl_job_listing_id for row in target.rows
                ),
                eligibility_statuses=tuple(
                    row.eligibility_status for row in target.rows
                ),
                eligibility_fingerprints=tuple(
                    row.eligibility_fingerprint for row in target.rows
                ),
                runtime_identity_fingerprints=tuple(
                    str(
                        row.status_metadata.get(
                            "runtime_identity_fingerprint"
                        )
                        or ""
                    )
                    for row in target.rows
                ),
            )
            for target in snapshot.targets
        ),
        resume_context=resume_context,
    )


def detail_row_eligibility_fingerprint(row: CrawlJobListing) -> str:
    return payload_fingerprint(
        {
            "version": 1,
            "crawl_job_listing_id": str(row.id),
            "source_listing_crawl_job_id": str(row.crawl_job_id),
            "source_site": str(row.source_site),
            "source_job_id": str(row.source_job_id),
            "source_classification_id": row.source_classification_id,
            "detail_status": str(row.detail_status),
            "detail_attempts": int(row.detail_attempts or 0),
            "last_detail_crawl_job_id": (
                str(row.last_detail_crawl_job_id)
                if row.last_detail_crawl_job_id is not None
                else None
            ),
            "published_job_id": (
                str(row.published_job_id)
                if row.published_job_id is not None
                else None
            ),
            "created_at": _instant_text(row.created_at),
            "updated_at": _instant_text(row.updated_at),
        }
    )


def detail_row_runtime_identity_fingerprint(row: CrawlJobListing) -> str:
    """Hash frozen source inputs while excluding mutable detail outcome state."""

    return payload_fingerprint(
        {
            "version": 1,
            "crawl_job_listing_id": str(row.id),
            "source_listing_crawl_job_id": str(row.crawl_job_id),
            "source_site": str(row.source_site),
            "source_job_id": str(row.source_job_id),
            "source_url": str(row.source_url),
            "source_classification_id": row.source_classification_id,
            "source_classification_name": row.source_classification_name,
            "listing_page": row.listing_page,
            "listing_rank": row.listing_rank,
            "listing_payload": dict(row.listing_payload or {}),
            "created_at": _instant_text(row.created_at),
        }
    )


def _row_status_metadata(row: CrawlJobListing) -> dict[str, Any]:
    return {
        "source_listing_crawl_job_id": str(row.crawl_job_id),
        "source_classification_id": row.source_classification_id,
        "detail_attempts": int(row.detail_attempts or 0),
        "last_detail_crawl_job_id": (
            str(row.last_detail_crawl_job_id)
            if row.last_detail_crawl_job_id is not None
            else None
        ),
        "created_at": _instant_text(row.created_at),
        "updated_at": _instant_text(row.updated_at),
        "runtime_identity_fingerprint": (
            detail_row_runtime_identity_fingerprint(row)
        ),
    }


def _instant_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)
