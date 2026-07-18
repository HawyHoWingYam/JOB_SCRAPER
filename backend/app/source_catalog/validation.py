from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta
import logging
from typing import Any

from sqlalchemy.orm import Session

from app.repositories.source_catalog_repository import (
    SourceCatalogConcurrentChangeError,
    SourceCatalogRepository,
    SourceCatalogStateError,
)
from app.source_catalog.domain import DiscoveredCatalog, validate_compiled_catalog
from app.scraper.log_events import build_scrape_log_event


logger = logging.getLogger(__name__)


_SAFE_EVIDENCE_FIELDS = frozenset(
    {
        "attempt",
        "catalog_hash_prefix",
        "category_count",
        "classification",
        "code",
        "constraint",
        "content_length",
        "content_type",
        "crawl_mode",
        "error_type",
        "http_status",
        "node_count",
        "reason",
        "stage",
        "status",
        "target_count",
        "target_hash_prefix",
        "warmup",
    }
)


def _bounded_evidence(value: Any) -> dict[str, Any]:
    """Persist only an explicit scalar evidence vocabulary, never opaque data."""

    if not isinstance(value, Mapping):
        return {"error_type": type(value).__name__}
    bounded: dict[str, Any] = {}
    for raw_key, item in value.items():
        key = str(raw_key)
        if key not in _SAFE_EVIDENCE_FIELDS:
            continue
        if item is None or isinstance(item, (bool, int, float)):
            bounded[key] = item
        elif isinstance(item, str):
            bounded[key] = item[:256]
        else:
            bounded[key] = type(item).__name__
    return bounded


class CatalogValidationCoordinator:
    """Durable offline/live-smoke validation without publication side effects."""

    def __init__(
        self,
        db: Session,
        *,
        repository: SourceCatalogRepository | None = None,
        adapters: Mapping[str, Any],
        stale_after: timedelta = timedelta(minutes=10),
    ) -> None:
        self.db = db
        self.repository = repository or SourceCatalogRepository()
        self.adapters = dict(adapters)
        self.stale_after = stale_after

    def _candidate_catalog(self, candidate) -> DiscoveredCatalog:
        return DiscoveredCatalog.from_payloads(
            normalized_payload=candidate.normalized_payload,
            source_payload=candidate.source_payload,
            provenance=candidate.provenance,
        )

    def start(self, candidate_id):
        candidate = self.repository.get_candidate_for_update(self.db, candidate_id)
        if candidate is None:
            raise SourceCatalogStateError("Source Catalog candidate was not found")
        if candidate.state == "published":
            raise SourceCatalogStateError("Published candidate cannot be revalidated")
        catalog = self._candidate_catalog(candidate)
        adapter = self.adapters.get(catalog.source_site)
        if adapter is None:
            raise SourceCatalogStateError("Source Catalog adapter is unavailable")

        from app.utils.time import utc_now

        self.repository.fail_stale_validation_runs(
            self.db,
            candidate_id=candidate.id,
            stale_before=utc_now() - self.stale_after,
            auto_commit=False,
        )

        existing = self.repository.list_validation_runs(
            self.db, candidate_id=candidate.id
        )
        passed_keys = {
            (run.validation_kind, run.expected_target_hash)
            for run in existing
            if run.status == "passed"
        }
        active_keys = {
            (run.validation_kind, run.expected_target_hash)
            for run in existing
            if run.status in {"pending", "running"}
        }
        max_attempt = {
            (run.validation_kind, run.expected_target_hash): max(
                run.attempt,
                max(
                    (
                        other.attempt
                        for other in existing
                        if other.validation_kind == run.validation_kind
                        and other.expected_target_hash == run.expected_target_hash
                    ),
                    default=0,
                ),
            )
            for run in existing
        }

        desired: list[tuple[str, str, str | None, str | None]] = [
            ("offline", candidate.fingerprint, None, None)
        ]
        changed_classifications = {
            str(item.get("classification_id"))
            for key in ("added", "query_semantics_changed")
            for item in (candidate.diff or {}).get(key, [])
            if item.get("classification_id")
        }
        for node in catalog.nodes:
            if not node.queryable or node.classification_id not in changed_classifications:
                continue
            for target in adapter.compile(node):
                desired.append(
                    (
                        "live_smoke",
                        target.fingerprint,
                        node.node_key,
                        node.classification_id,
                    )
                )

        for validation_kind, target_hash, node_key, classification_id in desired:
            key = (validation_kind, target_hash)
            if key in passed_keys or key in active_keys:
                continue
            self.repository.create_validation_run(
                self.db,
                candidate_id=candidate.id,
                validation_kind=validation_kind,
                expected_target_hash=target_hash,
                node_key=node_key,
                classification_id=classification_id,
                attempt=max_attempt.get(key, 0) + 1,
                auto_commit=False,
            )
        candidate.state = "validating"
        self.db.commit()
        runs = self.repository.list_validation_runs(
            self.db, candidate_id=candidate.id
        )
        logger.info(
            build_scrape_log_event(
                "SOURCE_CATALOG_VALIDATION_QUEUED",
                source=candidate.source_site,
                candidate_id=str(candidate.id),
                fingerprint=candidate.fingerprint[:12],
                node_count=len(catalog.nodes),
                validation_runs=len(runs),
            )
        )
        return runs

    async def run_pending(self, candidate_id, *, worker_id: str) -> None:
        while True:
            run = self.repository.claim_next_validation_run(
                self.db,
                candidate_id=candidate_id,
                worker_id=worker_id,
            )
            if run is None:
                break
            candidate = self.repository.get_candidate(self.db, candidate_id)
            if candidate is None:
                raise SourceCatalogStateError("Source Catalog candidate was not found")
            catalog = self._candidate_catalog(candidate)
            adapter = self.adapters[catalog.source_site]
            try:
                if run.validation_kind == "offline":
                    report = validate_compiled_catalog(catalog, adapter)
                    status = "passed"
                    evidence = {
                        "node_count": report.node_count,
                        "target_count": report.target_count,
                        "catalog_hash_prefix": candidate.fingerprint[:12],
                    }
                    manual_action = None
                    error = None
                else:
                    node = next(
                        (
                            item
                            for item in catalog.nodes
                            if item.node_key == run.node_key
                            and item.classification_id == run.classification_id
                        ),
                        None,
                    )
                    if node is None:
                        raise SourceCatalogStateError(
                            "Validation target is no longer present in candidate"
                        )
                    targets = adapter.compile(node)
                    target = next(
                        (
                            item
                            for item in targets
                            if item.fingerprint == run.expected_target_hash
                        ),
                        None,
                    )
                    if target is None:
                        raise SourceCatalogStateError(
                            "Validation target hash no longer matches candidate"
                        )
                    result = _bounded_evidence(await adapter.smoke(target))
                    status = str(result.get("status") or "failed")
                    if status not in {"passed", "failed", "manual_action_required"}:
                        status = "failed"
                    evidence = result if status == "passed" else {
                        key: value
                        for key, value in result.items()
                        if key not in {"error", "manual_action"}
                    }
                    manual_action = result if status == "manual_action_required" else None
                    error = result if status == "failed" else None
            except Exception as exc:
                status = "failed"
                evidence = {"error_type": type(exc).__name__}
                error = {"error_type": type(exc).__name__}
                manual_action = None
            try:
                self.repository.complete_validation_run(
                    self.db,
                    run=run,
                    worker_id=worker_id,
                    status=status,
                    evidence=evidence,
                    error=error,
                    manual_action=manual_action,
                )
            except SourceCatalogConcurrentChangeError:
                self.db.rollback()
                logger.warning(
                    build_scrape_log_event(
                        "SOURCE_CATALOG_VALIDATION_STALE_CLAIM",
                        source=candidate.source_site,
                        candidate_id=str(candidate.id),
                        validation_kind=run.validation_kind,
                        target_hash=run.expected_target_hash[:12],
                    )
                )
                continue
            logger.info(
                build_scrape_log_event(
                    "SOURCE_CATALOG_VALIDATION_RESULT",
                    source=candidate.source_site,
                    candidate_id=str(candidate.id),
                    validation_kind=run.validation_kind,
                    status=status,
                    target_hash=run.expected_target_hash[:12],
                    attempt=run.attempt,
                )
            )
        self._finalize_candidate(candidate_id)

    def _finalize_candidate(self, candidate_id) -> None:
        candidate = self.repository.get_candidate_for_update(self.db, candidate_id)
        if candidate is None:
            raise SourceCatalogStateError("Source Catalog candidate was not found")
        runs = self.repository.list_validation_runs(
            self.db, candidate_id=candidate.id
        )
        latest_by_key = {}
        for run in runs:
            key = (run.validation_kind, run.expected_target_hash)
            if key not in latest_by_key or run.attempt > latest_by_key[key].attempt:
                latest_by_key[key] = run
        statuses = {run.status for run in latest_by_key.values()}
        if statuses & {"pending", "running"}:
            candidate.state = "validating"
        elif "manual_action_required" in statuses:
            candidate.state = "manual_action_required"
        elif "failed" in statuses or not statuses:
            candidate.state = "validation_failed"
        else:
            candidate.state = "validated"
            from app.utils.time import utc_now

            candidate.validated_at = utc_now()
        candidate.validation_summary = {
            "status": candidate.state,
            "run_count": len(runs),
            "passed": sum(run.status == "passed" for run in runs),
            "failed": sum(run.status == "failed" for run in runs),
            "manual_action_required": sum(
                run.status == "manual_action_required" for run in runs
            ),
        }
        self.db.commit()
