from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from sqlalchemy.orm import Session

from app.crawl_control.automation_contracts import AutomationSnapshotV1
from app.crawl_control.automation_repository import AutomationRepository
from app.crawl_control.contracts import CrawlScopeErrorPayloadV1
from app.crawl_control.scope_service import CrawlScopeService
from app.repositories.source_catalog_repository import SourceCatalogRepository
from app.services.source_catalog_service import (
    PublishedSourceCatalog,
    SourceCatalogService,
    build_production_source_catalog_adapters,
)
from app.source_catalog.domain import DiscoveredCatalog
from app.source_catalog.errors import SourceCatalogError
from app.source_catalog.impact import CatalogImpactAssessment
from app.utils.time import utc_now


class AutomationCatalogImpactEvaluator:
    """Assess and atomically apply Source Catalog effects to Automations."""

    def __init__(
        self,
        db: Session,
        *,
        source_catalog_repository: SourceCatalogRepository | None = None,
        automation_repository: AutomationRepository | None = None,
        adapters: Mapping[str, Any] | None = None,
    ) -> None:
        self.db = db
        self.source_catalog_repository = (
            source_catalog_repository or SourceCatalogRepository()
        )
        self.automation_repository = (
            automation_repository or AutomationRepository()
        )
        self.adapters = dict(
            adapters or build_production_source_catalog_adapters()
        )
        self.catalogs = SourceCatalogService(
            db,
            repository=self.source_catalog_repository,
            adapters=self.adapters,
        )
        self.scopes = CrawlScopeService(self.catalogs)

    @staticmethod
    def _published(record) -> PublishedSourceCatalog:
        return PublishedSourceCatalog(
            revision=record,
            catalog=DiscoveredCatalog.from_payloads(
                normalized_payload=record.normalized_payload,
                source_payload=record.source_payload,
                provenance=record.provenance,
            ),
        )

    def _load_change_catalogs(
        self,
        *,
        operation: str,
        source_site: str,
        candidate_fingerprint: str | None,
        target_revision_id: str | None,
        base_active_revision_id: str | None,
    ) -> tuple[PublishedSourceCatalog | None, PublishedSourceCatalog]:
        before = None
        if base_active_revision_id is not None:
            before_record = self.source_catalog_repository.get_revision(
                self.db,
                base_active_revision_id,
            )
            if before_record is None or before_record.source_site != source_site:
                raise SourceCatalogError(
                    "CATALOG_IMPACT_STALE",
                    "Automation impact base Source Catalog is unavailable",
                )
            before = self._published(before_record)

        if operation == "publish":
            if not candidate_fingerprint:
                raise SourceCatalogError(
                    "CATALOG_IMPACT_STALE",
                    "Publication impact requires a validated candidate fingerprint",
                )
            target_record = (
                self.source_catalog_repository.get_validated_candidate_by_fingerprint(
                    self.db,
                    source_site=source_site,
                    fingerprint=candidate_fingerprint,
                )
            )
        elif operation == "rollback":
            target_record = self.source_catalog_repository.get_revision(
                self.db,
                target_revision_id,
            )
            if (
                target_record is not None
                and candidate_fingerprint is not None
                and target_record.fingerprint != candidate_fingerprint
            ):
                target_record = None
        else:
            raise SourceCatalogError(
                "CATALOG_IMPACT_STALE",
                "Unsupported Source Catalog impact operation",
            )
        if target_record is None or target_record.source_site != source_site:
            raise SourceCatalogError(
                "CATALOG_IMPACT_STALE",
                "Automation impact target Source Catalog is unavailable",
            )
        return before, self._published(target_record)

    def evaluate(
        self,
        *,
        operation: str,
        source_site: str,
        candidate_fingerprint: str | None,
        target_revision_id: str | None,
        base_active_revision_id: str | None,
    ) -> CatalogImpactAssessment:
        before, after = self._load_change_catalogs(
            operation=operation,
            source_site=source_site,
            candidate_fingerprint=candidate_fingerprint,
            target_revision_id=target_revision_id,
            base_active_revision_id=base_active_revision_id,
        )
        rows = self.automation_repository.list_for_catalog_impact(
            self.db,
            source_site=source_site,
        )
        legacy_automation_count = (
            self.automation_repository.count_legacy_for_catalog_impact(
                self.db,
                source_site=source_site,
            )
        )
        warnings = (
            [
                {
                    "code": "LEGACY_CRAWL_CONTROL_RESET_REQUIRED",
                    "message": (
                        "Legacy Crawl Control rows require the approved "
                        "maintenance cutover before versioned dispatch"
                    ),
                    "count": legacy_automation_count,
                }
            ]
            if before is None and legacy_automation_count
            else []
        )
        if before is None and rows:
            return CatalogImpactAssessment(
                allowed=False,
                versioned_automation_count=len(rows),
                summary={
                    "version": 1,
                    "operation": operation,
                    "source_site": source_site,
                    "versioned_automation_count": len(rows),
                    "legacy_automation_count": legacy_automation_count,
                    "compatible_count": 0,
                    "scope_review_required_count": len(rows),
                    "will_mark_scope_review_required_count": 0,
                    "automations": [],
                    "warnings": warnings,
                    "blocking_reason": "initial_catalog_has_automations",
                },
            )

        effects: list[dict[str, Any]] = []
        for automation, revision in rows:
            snapshot = AutomationSnapshotV1.model_validate(revision.snapshot)
            configuration = snapshot.configuration
            execution_settings = (
                configuration.listing_settings
                or configuration.detail_settings
            )
            assert execution_settings is not None
            assert before is not None
            impact = self.scopes.assess_catalog_change(
                configuration.scope,
                before=before,
                after=after,
                execution_settings=execution_settings,
            )
            will_mark = (
                impact.status == "scope_review_required"
                and snapshot.lifecycle_state != "archived"
            )
            effects.append(
                {
                    "automation_id": str(automation.id),
                    "expected_revision": automation.revision,
                    "snapshot_fingerprint": revision.snapshot_fingerprint,
                    "lifecycle_state": snapshot.lifecycle_state,
                    "crawl_phase": configuration.crawl_phase,
                    "status": impact.status,
                    "will_mark_scope_review_required": will_mark,
                    "impact": impact.model_dump(mode="json"),
                }
            )

        compatible_count = sum(
            effect["status"] == "compatible" for effect in effects
        )
        review_required_count = len(effects) - compatible_count
        will_mark_count = sum(
            bool(effect["will_mark_scope_review_required"])
            for effect in effects
        )
        summary = {
            "version": 1,
            "operation": operation,
            "source_site": source_site,
            "base_active_revision_id": base_active_revision_id,
            "target_revision_id": target_revision_id,
            "target_catalog_fingerprint": candidate_fingerprint,
            "versioned_automation_count": len(effects),
            "legacy_automation_count": legacy_automation_count,
            "compatible_count": compatible_count,
            "scope_review_required_count": review_required_count,
            "will_mark_scope_review_required_count": will_mark_count,
            "automations": deepcopy(effects),
            "warnings": warnings,
        }
        return CatalogImpactAssessment(
            allowed=True,
            versioned_automation_count=len(effects),
            summary=summary,
            effects=tuple(effects),
        )

    def apply(
        self,
        *,
        assessment: CatalogImpactAssessment,
        actor: str,
    ) -> None:
        if not str(actor or "").strip():
            raise ValueError("Catalog impact actor is required")
        source_site = str(assessment.summary.get("source_site") or "")
        self.automation_repository.lock_catalog_impact_set(self.db)
        rows = self.automation_repository.list_for_catalog_impact(
            self.db,
            source_site=source_site,
            for_update=True,
        )
        effects = {
            str(effect["automation_id"]): effect
            for effect in assessment.effects
        }
        if len(rows) != len(effects):
            raise SourceCatalogError(
                "CATALOG_IMPACT_STALE",
                "Automation set changed while applying catalog impact",
            )

        now = utc_now()
        for automation, revision in rows:
            effect = effects.get(str(automation.id))
            snapshot = AutomationSnapshotV1.model_validate(revision.snapshot)
            if (
                effect is None
                or automation.revision != effect["expected_revision"]
                or revision.snapshot_fingerprint
                != effect["snapshot_fingerprint"]
                or snapshot.lifecycle_state != effect["lifecycle_state"]
            ):
                raise SourceCatalogError(
                    "CATALOG_IMPACT_STALE",
                    "Automation revision changed while applying catalog impact",
                )
            if not effect["will_mark_scope_review_required"]:
                continue

            impact = effect["impact"]
            reason_codes = tuple(impact.get("reason_codes") or ())
            reason = CrawlScopeErrorPayloadV1(
                code="SCOPE_REVIEW_REQUIRED",
                message=(
                    "Automation scope requires review after Source Catalog change"
                ),
                context={
                    "source_site": source_site,
                    "operation": str(
                        assessment.summary.get("operation") or "catalog_change"
                    ),
                    "reason_codes": ",".join(str(code) for code in reason_codes),
                    "target_catalog_fingerprint": str(
                        assessment.summary.get("target_catalog_fingerprint")
                        or ""
                    ),
                },
            )
            automation.lifecycle_state = "scope_review_required"
            automation.is_active = False
            automation.next_run_at = None
            automation.scope_review_reason = reason.model_dump(mode="json")
            automation.revision += 1
            automation.updated_at = now
            updated_snapshot = AutomationSnapshotV1(
                automation_id=automation.id,
                revision=automation.revision,
                lifecycle_state="scope_review_required",
                configuration=snapshot.configuration,
                scope_review_reason=reason,
                archived_at=None,
            )
            self.automation_repository.append_revision(
                self.db,
                automation_id=automation.id,
                revision=automation.revision,
                snapshot=updated_snapshot.model_dump(mode="json"),
                snapshot_fingerprint=updated_snapshot.fingerprint,
                operation=(
                    f"catalog_{assessment.summary.get('operation')}_"
                    "scope_review_required"
                ),
                actor=actor,
            )
        self.db.flush()
