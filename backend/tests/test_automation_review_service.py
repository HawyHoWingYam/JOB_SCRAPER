from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from app.crawl_control.automation_contracts import AutomationConfigurationV1
from app.crawl_control.automation_review_contracts import AutomationReviewRequestV1
from app.crawl_control.automation_review_service import AutomationReviewService
from app.crawl_control.contracts import (
    AuthoredCrawlScopeV1,
    CrawlScopePreviewV1,
    DetailSettingsV1,
    ListingSettingsV1,
    ListingWorkloadPreviewV1,
    QueryTargetSnapshotV1,
    ResolvedRunScopeV1,
    SelectedClassificationSnapshotV1,
)
from app.crawl_control.detail_runtime import DetailBacklogPreview
from app.source_classifications.domain import SourceQueryTarget, payload_fingerprint


NOW = datetime(2026, 7, 21, 3, 0, tzinfo=UTC)


class NoWriteSession:
    def add(self, *_args, **_kwargs):
        raise AssertionError("Automation review must not add rows")

    def flush(self, *_args, **_kwargs):
        raise AssertionError("Automation review must not flush")

    def commit(self, *_args, **_kwargs):
        raise AssertionError("Automation review must not commit")


def _scope_and_resolved():
    scope = AuthoredCrawlScopeV1(
        source_site="jobsdb",
        mode="selected",
        classification_ids=("jobsdb:6281",),
    )
    selected = SelectedClassificationSnapshotV1(
        node_key="jobsdb:6281",
        classification_id="jobsdb:6281",
        native_label="Information Technology",
        native_path=("Information Technology",),
        query_semantics_hash="a" * 64,
    )
    target = QueryTargetSnapshotV1.from_source_target(
        SourceQueryTarget(
            adapter="jobsdb.classification",
            classification_id="jobsdb:6281",
            payload={"native_id": 6281},
        )
    )
    expansion_hash = payload_fingerprint(
        [
            {
                "node_key": selected.node_key,
                "classification_id": selected.classification_id,
                "query_semantics_hash": selected.query_semantics_hash,
            }
        ]
    )
    resolved = ResolvedRunScopeV1(
        source_site="jobsdb",
        authored_scope=scope,
        selected_classifications=(selected,),
        classification_expansion_hash=expansion_hash,
        query_targets=(target,),
        query_target_count=1,
    )
    return scope, resolved


class StubScopeService:
    def __init__(self, resolved):
        self.resolved = resolved

    def preview(
        self,
        scope,
        *,
        listing_settings=None,
        enforce_listing_workload=True,
    ):
        workload = None
        if listing_settings is not None:
            estimated_max_pages = listing_settings.page_depth
            workload = ListingWorkloadPreviewV1(
                query_target_count=1,
                page_depth=listing_settings.page_depth,
                estimated_max_pages=estimated_max_pages,
                run_page_cap=listing_settings.run_page_cap,
                system_run_page_cap=1000,
                within_operator_cap=(
                    estimated_max_pages <= listing_settings.run_page_cap
                ),
                within_system_cap=estimated_max_pages <= 1000,
            )
        return CrawlScopePreviewV1(
            resolved_scope=self.resolved,
            listing_workload=workload,
        )


class StubDetailBuilder:
    def __init__(self, *, eligible=23, selected=10):
        self.preview_value = DetailBacklogPreview(
            eligible_target_count=eligible,
            selected_target_count=selected,
            absolute_safety_cap=100_000,
        )
        self.calls = []

    def preview(self, db, *, content, eligible_at_or_before):
        self.calls.append((db, content, eligible_at_or_before))
        return self.preview_value


def _listing_configuration(scope):
    return AutomationConfigurationV1(
        name="JobsDB listing",
        cron_expression="0 4 * * *",
        timezone="Asia/Hong_Kong",
        scope=scope,
        listing_settings=ListingSettingsV1(
            crawl_mode="headless",
            page_depth=2,
            run_page_cap=20,
        ),
    )


def _detail_configuration(scope):
    return AutomationConfigurationV1(
        name="JobsDB detail",
        cron_expression="0 9 * * 1-5",
        timezone="Asia/Hong_Kong",
        scope=scope,
        detail_settings=DetailSettingsV1.model_validate(
            {
                "crawl_mode": "headless",
                "backlog_scope": {"kind": "crawl_scope", "scope": scope},
                "limit": {"kind": "stop_after", "detail_run_cap": 10},
            }
        ),
    )


def test_listing_review_is_read_only_and_fingerprinted():
    scope, resolved = _scope_and_resolved()
    db = NoWriteSession()
    service = AutomationReviewService(
        db,
        scope_service=StubScopeService(resolved),
        automation_service=SimpleNamespace(),
        runtime_readiness_check=lambda **_kwargs: None,
        clock=lambda: NOW,
    )
    request = AutomationReviewRequestV1(
        configuration=_listing_configuration(scope)
    )

    first = service.review(request)
    second = service.review(request)

    assert first.input_fingerprint == second.input_fingerprint
    assert first.authored_scope == scope
    assert first.listing_workload is not None
    assert first.listing_workload.estimated_max_pages == 2
    assert first.detail_preview is None
    assert first.readiness.status == "ready"
    assert first.schedule_summary.timezone == "Asia/Hong_Kong"
    assert first.schedule_summary.next_run_at.utcoffset() is not None


def test_listing_review_retains_under_budget_configuration_as_blocked():
    scope, resolved = _scope_and_resolved()
    configuration = _listing_configuration(scope).model_copy(
        update={
            "listing_settings": ListingSettingsV1(
                crawl_mode="headless",
                page_depth=21,
                run_page_cap=20,
            )
        }
    )
    review = AutomationReviewService(
        NoWriteSession(),
        scope_service=StubScopeService(resolved),
        automation_service=SimpleNamespace(),
        runtime_readiness_check=lambda **_kwargs: None,
        clock=lambda: NOW,
    ).review(AutomationReviewRequestV1(configuration=configuration))

    assert review.listing_workload is not None
    assert review.listing_workload.dispatchable is False
    assert review.readiness.status == "blocked"
    assert [error.code for error in review.readiness.blocking_errors] == [
        "WORKLOAD_CAP_EXCEEDED"
    ]


def test_detail_review_counts_without_freezing_membership():
    scope, resolved = _scope_and_resolved()
    db = NoWriteSession()
    builder = StubDetailBuilder()
    service = AutomationReviewService(
        db,
        scope_service=StubScopeService(resolved),
        automation_service=SimpleNamespace(),
        detail_backlog_builder=builder,
        runtime_readiness_check=lambda **_kwargs: None,
        clock=lambda: NOW,
    )

    review = service.review(
        AutomationReviewRequestV1(configuration=_detail_configuration(scope))
    )

    assert review.listing_workload is None
    assert review.detail_preview is not None
    assert review.detail_preview.eligible_now_count == 23
    assert review.detail_preview.selected_now_count == 10
    assert review.detail_preview.snapshot_frozen is False
    assert review.detail_preview.detail_run_cap == 10
    assert builder.calls[0][1].detail_settings.backlog_snapshot is None


def test_edit_binding_uses_current_automation_id_without_revision():
    scope, _resolved = _scope_and_resolved()
    automation_id = uuid4()

    request = AutomationReviewRequestV1(
        configuration=_listing_configuration(scope),
        automation_id=automation_id,
    )

    assert request.automation_id == automation_id
