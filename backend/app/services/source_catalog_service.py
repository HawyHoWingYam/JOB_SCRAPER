from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
import logging
import re
import secrets
from typing import Any

from sqlalchemy.orm import Session

from app.repositories.source_catalog_repository import SourceCatalogRepository
from app.source_catalog.adapters import (
    CTgoodjobsSourceCatalogAdapter,
    JobsDBSourceCatalogAdapter,
    OfferTodaySourceCatalogAdapter,
)
from app.source_catalog.domain import (
    DiscoveredCatalog,
    diff_catalogs,
    expand_catalog_scope,
    validate_compiled_catalog,
)
from app.source_catalog.errors import SourceCatalogError
from app.source_catalog.impact import CatalogImpactEvaluator
from app.utils.time import utc_now
from app.scraper.log_events import build_scrape_log_event


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PublishedSourceCatalog:
    revision: Any
    catalog: DiscoveredCatalog


@dataclass(frozen=True)
class CatalogChangeReviewGrant:
    review_id: Any
    review_token: str
    expires_at: datetime
    impact: dict[str, Any]


def build_production_source_catalog_adapters() -> dict[str, Any]:
    adapters = (
        JobsDBSourceCatalogAdapter(),
        CTgoodjobsSourceCatalogAdapter(),
        OfferTodaySourceCatalogAdapter(),
    )
    return {adapter.source_site: adapter for adapter in adapters}


class SourceCatalogService:
    """The only executable interface to discovered and published Source Catalogs."""

    def __init__(
        self,
        db: Session,
        *,
        repository: SourceCatalogRepository | None = None,
        adapters: Mapping[str, Any] | None = None,
        impact_evaluator: CatalogImpactEvaluator | None = None,
    ) -> None:
        self.db = db
        self.repository = repository or SourceCatalogRepository()
        self.adapters = dict(adapters or build_production_source_catalog_adapters())
        self.impact_evaluator = impact_evaluator

    def _adapter(self, source_site: str):
        normalized = str(source_site or "").strip().lower()
        adapter = self.adapters.get(normalized)
        if adapter is None:
            raise ValueError(f"Unsupported source_site: {normalized}")
        return adapter

    def discover(self, source_site: str):
        adapter = self._adapter(source_site)
        catalog = adapter.discover()
        validate_compiled_catalog(catalog, adapter)
        active_revision = self.repository.get_active_revision(
            self.db, source_site=catalog.source_site
        )
        previous = None
        if active_revision is not None:
            previous = DiscoveredCatalog.from_payloads(
                normalized_payload=active_revision.normalized_payload,
                source_payload=active_revision.source_payload,
                provenance=active_revision.provenance,
            )
        diff = diff_catalogs(previous, catalog)
        return self.repository.create_or_get_candidate(
            self.db,
            source_site=catalog.source_site,
            base_revision_id=(active_revision.id if active_revision is not None else None),
            fingerprint=catalog.fingerprint,
            normalized_payload=catalog.normalized_payload(),
            source_payload=deepcopy(dict(catalog.source_payload)),
            provenance=deepcopy(dict(catalog.provenance)),
            diff=diff.to_payload(),
        )

    def get_published(self, source_site: str) -> PublishedSourceCatalog:
        adapter = self._adapter(source_site)
        revision = self.repository.get_active_revision(
            self.db, source_site=adapter.source_site
        )
        if revision is None:
            raise SourceCatalogError(
                "CATALOG_NOT_PUBLISHED",
                f"No Source Catalog revision is published for {adapter.source_site}",
                context={"source_site": adapter.source_site},
            )
        catalog = DiscoveredCatalog.from_payloads(
            normalized_payload=revision.normalized_payload,
            source_payload=revision.source_payload,
            provenance=revision.provenance,
        )
        validate_compiled_catalog(catalog, adapter)
        return PublishedSourceCatalog(revision=revision, catalog=catalog)

    @staticmethod
    def _legacy_slug(label: str) -> str:
        return re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")

    def get_legacy_categories(self, source_site: str) -> list[dict[str, Any]]:
        published = self.get_published(source_site)
        categories: list[dict[str, Any]] = []
        for node in published.catalog.nodes:
            if not node.selectable or node.classification_id is None:
                continue
            categories.append(
                {
                    "id": (
                        node.classification_id
                        if published.catalog.source_site == "ctgoodjobs"
                        else node.native_id
                    ),
                    "name": node.native_label,
                    "slug": str(
                        node.source_metadata.get("slug")
                        or self._legacy_slug(node.native_label)
                    ),
                    "source_site": published.catalog.source_site,
                }
            )
        return categories

    @staticmethod
    def _qualify_classification_id(source_site: str, value: Any) -> str:
        text = str(value or "").strip()
        if text.startswith(f"{source_site}:"):
            return text
        if source_site == "ctgoodjobs":
            raise SourceCatalogError(
                "SOURCE_CLASSIFICATION_UNKNOWN",
                "CTgoodjobs requires a published source-qualified classification ID",
            )
        if not text:
            raise SourceCatalogError(
                "SOURCE_CLASSIFICATION_UNKNOWN", "Source Classification ID is empty"
            )
        return f"{source_site}:{text}"

    def validate_classifications(
        self,
        source_site: str,
        classification_ids,
    ):
        published = self.get_published(source_site)
        by_classification = {
            node.classification_id: node
            for node in published.catalog.nodes
            if node.classification_id is not None
        }
        selected = []
        seen: set[str] = set()
        for raw_id in classification_ids or ():
            classification_id = self._qualify_classification_id(
                published.catalog.source_site, raw_id
            )
            if classification_id in seen:
                continue
            node = by_classification.get(classification_id)
            if node is None:
                raise SourceCatalogError(
                    "SOURCE_CLASSIFICATION_UNKNOWN",
                    f"Unknown Source Classification {classification_id!r}",
                )
            if not node.selectable or not node.queryable:
                raise SourceCatalogError(
                    "SOURCE_CLASSIFICATION_NOT_EXECUTABLE",
                    f"Source Classification {classification_id!r} is not executable",
                )
            selected.append(node)
            seen.add(classification_id)
        return published, tuple(selected)

    def compile_classifications(
        self,
        source_site: str,
        classification_ids,
    ):
        published, nodes = self.validate_classifications(
            source_site, classification_ids
        )
        return tuple(
            target for _node, target in self.compile_nodes(published, nodes)
        )

    def compile_nodes(self, published: PublishedSourceCatalog, nodes):
        adapter = self._adapter(published.catalog.source_site)
        return tuple(
            (node, target) for node in nodes for target in adapter.compile(node)
        )

    def resolve_scope(
        self,
        source_site: str,
        *,
        mode: str,
        classification_ids=(),
    ):
        published = self.get_published(source_site)
        qualified = tuple(
            self._qualify_classification_id(published.catalog.source_site, item)
            for item in classification_ids or ()
        )
        try:
            nodes = expand_catalog_scope(
                published.catalog,
                mode=mode,
                classification_ids=qualified,
            )
        except ValueError as exc:
            code = getattr(exc, "code", "SOURCE_CLASSIFICATION_NOT_EXECUTABLE")
            raise SourceCatalogError(code, str(exc)) from exc
        targets = tuple(
            target for _node, target in self.compile_nodes(published, nodes)
        )
        return published, nodes, targets

    def _impact(
        self,
        *,
        operation: str,
        source_site: str,
        candidate_fingerprint: str | None,
        target_revision_id,
        base_active_revision_id,
    ):
        if self.impact_evaluator is None:
            raise SourceCatalogError(
                "CATALOG_IMPACT_STALE",
                "Catalog impact evaluation is unavailable until versioned Crawl Scope is integrated",
            )
        assessment = self.impact_evaluator.evaluate(
            operation=operation,
            source_site=source_site,
            candidate_fingerprint=candidate_fingerprint,
            target_revision_id=(str(target_revision_id) if target_revision_id else None),
            base_active_revision_id=(
                str(base_active_revision_id) if base_active_revision_id else None
            ),
        )
        if not assessment.allowed:
            raise SourceCatalogError(
                "CATALOG_IMPACT_STALE",
                "Catalog change is blocked by its Automation impact assessment",
            )
        if base_active_revision_id is None and assessment.versioned_automation_count != 0:
            raise SourceCatalogError(
                "CATALOG_IMPACT_STALE",
                "Initial publication requires proof that no versioned Automations exist",
            )
        return assessment

    @staticmethod
    def _token_hash(review_token: str) -> str:
        return hashlib.sha256(review_token.encode("utf-8")).hexdigest()

    @staticmethod
    def _is_expired(expires_at: datetime) -> bool:
        if expires_at.tzinfo is None:
            return expires_at <= utc_now().replace(tzinfo=None)
        return expires_at <= utc_now()

    def review_publication(
        self,
        candidate_id,
        *,
        actor: str,
        expected_source_site: str | None = None,
        ttl: timedelta = timedelta(minutes=10),
    ) -> CatalogChangeReviewGrant:
        candidate = self.repository.get_candidate(self.db, candidate_id)
        if candidate is None:
            raise SourceCatalogError("CATALOG_CANDIDATE_STALE", "Catalog candidate was not found")
        if expected_source_site is not None and candidate.source_site != expected_source_site:
            raise SourceCatalogError(
                "CATALOG_CANDIDATE_STALE",
                "Catalog candidate does not belong to the requested Source",
            )
        if candidate.state != "validated":
            raise SourceCatalogError(
                "CATALOG_VALIDATION_REQUIRED",
                "Catalog candidate must pass validation before publication review",
            )
        active = self.repository.get_active_revision(
            self.db, source_site=candidate.source_site
        )
        active_id = active.id if active is not None else None
        if active_id != candidate.base_revision_id:
            raise SourceCatalogError(
                "CATALOG_CANDIDATE_STALE",
                "Catalog candidate was discovered against an older active revision",
            )
        assessment = self._impact(
            operation="publish",
            source_site=candidate.source_site,
            candidate_fingerprint=candidate.fingerprint,
            target_revision_id=None,
            base_active_revision_id=active_id,
        )
        review_token = secrets.token_urlsafe(32)
        expires_at = utc_now() + ttl
        review = self.repository.create_change_review(
            self.db,
            token_hash=self._token_hash(review_token),
            operation="publish",
            source_site=candidate.source_site,
            candidate_id=candidate.id,
            candidate_fingerprint=candidate.fingerprint,
            base_active_revision_id=active_id,
            automation_impact_digest=assessment.digest,
            automation_impact=deepcopy(assessment.summary),
            actor=actor,
            expires_at=expires_at,
        )
        return CatalogChangeReviewGrant(
            review_id=review.id,
            review_token=review_token,
            expires_at=review.expires_at,
            impact=deepcopy(review.automation_impact),
        )

    def _validate_review(
        self,
        *,
        review,
        operation: str,
        source_site: str,
        actor: str,
    ) -> None:
        if (
            review is None
            or review.operation != operation
            or review.source_site != source_site
            or review.actor != actor
            or review.consumed_at is not None
            or self._is_expired(review.expires_at)
        ):
            raise SourceCatalogError(
                "CATALOG_IMPACT_STALE",
                "Catalog review token is invalid, expired, stale, or already consumed",
            )

    def publish(
        self,
        candidate_id,
        *,
        review_token: str,
        actor: str,
        expected_source_site: str | None = None,
    ):
        preview = self.repository.get_candidate(self.db, candidate_id)
        if (
            preview is not None
            and expected_source_site is not None
            and preview.source_site != expected_source_site
        ):
            raise SourceCatalogError(
                "CATALOG_CANDIDATE_STALE",
                "Catalog candidate does not belong to the requested Source",
            )
        try:
            self.repository.lock_source_publication(
                self.db,
                source_site=(
                    expected_source_site
                    or (preview.source_site if preview is not None else "")
                ),
            )
            review = self.repository.get_change_review_by_token_hash_for_update(
                self.db, token_hash=self._token_hash(review_token)
            )
            if review is None:
                raise SourceCatalogError(
                    "CATALOG_IMPACT_STALE", "Catalog review token was not found"
                )
            self._validate_review(
                review=review,
                operation="publish",
                source_site=review.source_site,
                actor=actor,
            )
            candidate = self.repository.get_candidate_for_update(self.db, candidate_id)
            if candidate is None or candidate.state != "validated":
                raise SourceCatalogError(
                    "CATALOG_CANDIDATE_STALE",
                    "Catalog candidate is missing or no longer publishable",
                )
            if (
                review.candidate_id != candidate.id
                or review.candidate_fingerprint != candidate.fingerprint
            ):
                raise SourceCatalogError(
                    "CATALOG_CANDIDATE_STALE", "Catalog review no longer matches candidate"
                )
            pointer = self.repository.get_active_pointer_for_update(
                self.db, source_site=candidate.source_site
            )
            active_id = pointer.revision_id if pointer is not None else None
            if active_id != review.base_active_revision_id or active_id != candidate.base_revision_id:
                raise SourceCatalogError(
                    "CATALOG_IMPACT_STALE",
                    "Active Source Catalog revision changed after impact review",
                )
            current_impact = self._impact(
                operation="publish",
                source_site=candidate.source_site,
                candidate_fingerprint=candidate.fingerprint,
                target_revision_id=None,
                base_active_revision_id=active_id,
            )
            if current_impact.digest != review.automation_impact_digest:
                raise SourceCatalogError(
                    "CATALOG_IMPACT_STALE",
                    "Automation impact changed after catalog review",
                )
            revision = self.repository.create_revision(
                self.db,
                candidate=candidate,
                published_by=actor,
                publication_metadata={
                    "review_id": str(review.id),
                    "impact_digest": review.automation_impact_digest,
                },
                auto_commit=False,
            )
            self.repository.set_active_revision(
                self.db,
                source_site=candidate.source_site,
                revision_id=revision.id,
                expected_revision_id=active_id,
                updated_by=actor,
                auto_commit=False,
            )
            self.repository.append_publication(
                self.db,
                source_site=candidate.source_site,
                operation="publish",
                revision_id=revision.id,
                previous_revision_id=active_id,
                candidate_id=candidate.id,
                review_id=review.id,
                actor=actor,
                auto_commit=False,
            )
            candidate.state = "published"
            candidate.published_at = utc_now()
            review.consumed_at = utc_now()
            self.db.commit()
            self.db.refresh(revision)
            logger.info(
                build_scrape_log_event(
                    "SOURCE_CATALOG_PUBLISHED",
                    source=candidate.source_site,
                    candidate_id=str(candidate.id),
                    revision_id=str(revision.id),
                    sequence=revision.sequence,
                    fingerprint=revision.fingerprint[:12],
                )
            )
            return revision
        except Exception:
            self.db.rollback()
            raise

    def review_rollback(
        self,
        revision_id,
        *,
        actor: str,
        expected_source_site: str | None = None,
        ttl: timedelta = timedelta(minutes=10),
    ) -> CatalogChangeReviewGrant:
        target = self.repository.get_revision(self.db, revision_id)
        if target is None:
            raise SourceCatalogError("CATALOG_CANDIDATE_STALE", "Rollback revision was not found")
        if expected_source_site is not None and target.source_site != expected_source_site:
            raise SourceCatalogError(
                "CATALOG_CANDIDATE_STALE",
                "Rollback revision does not belong to the requested Source",
            )
        active = self.repository.get_active_revision(
            self.db, source_site=target.source_site
        )
        if active is None or active.id == target.id:
            raise SourceCatalogError(
                "CATALOG_IMPACT_STALE", "Rollback target is already active or no active revision exists"
            )
        assessment = self._impact(
            operation="rollback",
            source_site=target.source_site,
            candidate_fingerprint=target.fingerprint,
            target_revision_id=target.id,
            base_active_revision_id=active.id,
        )
        review_token = secrets.token_urlsafe(32)
        expires_at = utc_now() + ttl
        review = self.repository.create_change_review(
            self.db,
            token_hash=self._token_hash(review_token),
            operation="rollback",
            source_site=target.source_site,
            target_revision_id=target.id,
            candidate_fingerprint=target.fingerprint,
            base_active_revision_id=active.id,
            automation_impact_digest=assessment.digest,
            automation_impact=deepcopy(assessment.summary),
            actor=actor,
            expires_at=expires_at,
        )
        return CatalogChangeReviewGrant(
            review_id=review.id,
            review_token=review_token,
            expires_at=review.expires_at,
            impact=deepcopy(review.automation_impact),
        )

    def rollback(
        self,
        revision_id,
        *,
        review_token: str,
        actor: str,
        expected_source_site: str | None = None,
    ):
        preview = self.repository.get_revision(self.db, revision_id)
        if (
            preview is not None
            and expected_source_site is not None
            and preview.source_site != expected_source_site
        ):
            raise SourceCatalogError(
                "CATALOG_CANDIDATE_STALE",
                "Rollback revision does not belong to the requested Source",
            )
        try:
            self.repository.lock_source_publication(
                self.db,
                source_site=(
                    expected_source_site
                    or (preview.source_site if preview is not None else "")
                ),
            )
            target = self.repository.get_revision_for_update(self.db, revision_id)
            if target is None:
                raise SourceCatalogError(
                    "CATALOG_CANDIDATE_STALE", "Rollback revision was not found"
                )
            review = self.repository.get_change_review_by_token_hash_for_update(
                self.db, token_hash=self._token_hash(review_token)
            )
            self._validate_review(
                review=review,
                operation="rollback",
                source_site=target.source_site,
                actor=actor,
            )
            if (
                review.target_revision_id != target.id
                or review.candidate_fingerprint != target.fingerprint
            ):
                raise SourceCatalogError(
                    "CATALOG_IMPACT_STALE", "Rollback review no longer matches revision"
                )
            pointer = self.repository.get_active_pointer_for_update(
                self.db, source_site=target.source_site
            )
            active_id = pointer.revision_id if pointer is not None else None
            if active_id != review.base_active_revision_id:
                raise SourceCatalogError(
                    "CATALOG_IMPACT_STALE",
                    "Active Source Catalog revision changed after rollback review",
                )
            current_impact = self._impact(
                operation="rollback",
                source_site=target.source_site,
                candidate_fingerprint=target.fingerprint,
                target_revision_id=target.id,
                base_active_revision_id=active_id,
            )
            if current_impact.digest != review.automation_impact_digest:
                raise SourceCatalogError(
                    "CATALOG_IMPACT_STALE",
                    "Automation impact changed after rollback review",
                )
            self.repository.set_active_revision(
                self.db,
                source_site=target.source_site,
                revision_id=target.id,
                expected_revision_id=active_id,
                updated_by=actor,
                auto_commit=False,
            )
            self.repository.append_publication(
                self.db,
                source_site=target.source_site,
                operation="rollback",
                revision_id=target.id,
                previous_revision_id=active_id,
                review_id=review.id,
                actor=actor,
                auto_commit=False,
            )
            review.consumed_at = utc_now()
            self.db.commit()
            self.db.refresh(target)
            logger.info(
                build_scrape_log_event(
                    "SOURCE_CATALOG_ROLLED_BACK",
                    source=target.source_site,
                    revision_id=str(target.id),
                    previous_revision_id=(str(active_id) if active_id else None),
                    fingerprint=target.fingerprint[:12],
                )
            )
            return target
        except Exception:
            self.db.rollback()
            raise
