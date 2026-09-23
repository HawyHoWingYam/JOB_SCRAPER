from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.offertoday_coverage import OfferTodayTaxonomySnapshot
from app.services.source_classification_registry import SourceClassificationRegistry
from app.source_classifications.adapters.offertoday import (
    OfferTodaySourceClassificationAdapter,
)
from app.source_classifications.domain import (
    DiscoveredCatalog,
    validate_executable_catalog,
)
from app.utils.time import utc_now


class OfferTodayTaxonomyUnavailableError(RuntimeError):
    code = "OFFERTODAY_TAXONOMY_UNAVAILABLE"


@dataclass(frozen=True)
class ResolvedOfferTodayTaxonomy:
    catalog: DiscoveredCatalog
    fingerprint: str
    verified_at: datetime
    freshness: Literal["fresh", "verified", "stale"]
    warning: dict[str, str] | None = None


class OfferTodayTaxonomyResolver:
    """Refresh a complete live tree or return the last verified snapshot."""

    def __init__(
        self,
        db: Session,
        *,
        adapter: OfferTodaySourceClassificationAdapter | None = None,
    ) -> None:
        self.db = db
        self.adapter = adapter or OfferTodaySourceClassificationAdapter(
            live_discovery=True
        )

    def refresh_or_last_verified(
        self,
        *,
        refresh: bool = True,
    ) -> ResolvedOfferTodayTaxonomy:
        refresh_error: Exception | None = None
        if refresh:
            try:
                catalog = self.adapter.discover_live()
                validate_executable_catalog(catalog, self.adapter)
                now = utc_now()
                with self.db.begin_nested():
                    SourceClassificationRegistry(self.db).synchronize_catalog(
                        catalog,
                        complete=True,
                        compiler=self.adapter,
                    )
                    snapshot = self.db.scalar(
                        select(OfferTodayTaxonomySnapshot).where(
                            OfferTodayTaxonomySnapshot.fingerprint
                            == catalog.fingerprint
                        )
                    )
                    payload = {
                        "normalized": catalog.normalized_payload(),
                        "source": dict(catalog.source_payload),
                    }
                    if snapshot is None:
                        snapshot = OfferTodayTaxonomySnapshot(
                            fingerprint=catalog.fingerprint,
                            catalog_payload=payload,
                            provenance=dict(catalog.provenance),
                            verified_at=now,
                        )
                        self.db.add(snapshot)
                    else:
                        snapshot.catalog_payload = payload
                        snapshot.provenance = dict(catalog.provenance)
                        snapshot.verified_at = now
                    self.db.flush()
                return ResolvedOfferTodayTaxonomy(
                    catalog=catalog,
                    fingerprint=catalog.fingerprint,
                    verified_at=self._aware_utc(snapshot.verified_at),
                    freshness="fresh",
                )
            except Exception as exc:
                refresh_error = exc

        snapshot = self.db.scalar(
            select(OfferTodayTaxonomySnapshot).order_by(
                OfferTodayTaxonomySnapshot.verified_at.desc(),
                OfferTodayTaxonomySnapshot.id.desc(),
            )
        )
        if snapshot is None:
            raise OfferTodayTaxonomyUnavailableError(
                "OfferToday live taxonomy refresh failed and no verified snapshot exists"
            ) from refresh_error
        payload = dict(snapshot.catalog_payload or {})
        catalog = DiscoveredCatalog.from_payloads(
            normalized_payload=dict(payload["normalized"]),
            source_payload=dict(payload["source"]),
            provenance=dict(snapshot.provenance or {}),
        )
        verified_at = self._aware_utc(snapshot.verified_at)
        if not refresh:
            return ResolvedOfferTodayTaxonomy(
                catalog=catalog,
                fingerprint=snapshot.fingerprint,
                verified_at=verified_at,
                freshness="verified",
            )
        return ResolvedOfferTodayTaxonomy(
            catalog=catalog,
            fingerprint=snapshot.fingerprint,
            verified_at=verified_at,
            freshness="stale",
            warning={
                "code": "OFFERTODAY_TAXONOMY_STALE",
                "message": "Live OfferToday taxonomy refresh failed; using the last verified snapshot",
                "verified_at": verified_at.isoformat(),
                "snapshot_fingerprint": snapshot.fingerprint,
                "refresh_error_type": (
                    type(refresh_error).__name__ if refresh_error is not None else "refresh_skipped"
                ),
            },
        )

    @staticmethod
    def _aware_utc(value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


__all__ = [
    "OfferTodayTaxonomyResolver",
    "OfferTodayTaxonomyUnavailableError",
    "ResolvedOfferTodayTaxonomy",
]
