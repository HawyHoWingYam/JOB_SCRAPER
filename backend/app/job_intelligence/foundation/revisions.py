from __future__ import annotations

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.job_intelligence.foundation.contracts import RevisionManifest, RevisionRef
from app.job_intelligence.foundation.errors import RevisionConflictError
from app.models.governance import GovernanceRevision


class RevisionStore:
    """Publish or deterministically replay immutable governance revisions."""

    def __init__(self, db: Session) -> None:
        self.db = db

    @staticmethod
    def _ref(row: GovernanceRevision) -> RevisionRef:
        return RevisionRef(
            domain=row.domain,
            revision_id=row.id,
            release_key=row.release_key,
            content_hash=row.content_hash,
        )

    @staticmethod
    def _matches(row: GovernanceRevision, manifest: RevisionManifest) -> bool:
        return (
            row.release_key == manifest.release_key
            and row.content_hash == manifest.content_hash
            and row.source_metadata == dict(manifest.source_metadata)
        )

    def _existing(self, manifest: RevisionManifest) -> list[GovernanceRevision]:
        return (
            self.db.query(GovernanceRevision)
            .filter(
                GovernanceRevision.domain == manifest.domain,
                or_(
                    GovernanceRevision.release_key == manifest.release_key,
                    GovernanceRevision.content_hash == manifest.content_hash,
                ),
            )
            .all()
        )

    def _exact_replay(
        self,
        manifest: RevisionManifest,
    ) -> GovernanceRevision | None:
        return next(
            (row for row in self._existing(manifest) if self._matches(row, manifest)),
            None,
        )

    def publish(self, manifest: RevisionManifest) -> RevisionRef:
        existing = self._existing(manifest)
        if existing:
            replay = next(
                (row for row in existing if self._matches(row, manifest)),
                None,
            )
            if replay is not None:
                self.db.commit()
                return self._ref(replay)
            self.db.rollback()
            raise RevisionConflictError(
                domain=manifest.domain,
                release_key=manifest.release_key,
            )

        row = GovernanceRevision(
            domain=manifest.domain,
            release_key=manifest.release_key,
            content_hash=manifest.content_hash,
            source_metadata=dict(manifest.source_metadata),
            created_at=manifest.created_at,
        )
        self.db.add(row)
        try:
            self.db.commit()
            self.db.refresh(row)
            return self._ref(row)
        except IntegrityError:
            self.db.rollback()
            replay = self._exact_replay(manifest)
            if replay is not None:
                self.db.commit()
                return self._ref(replay)
            self.db.rollback()
            raise RevisionConflictError(
                domain=manifest.domain,
                release_key=manifest.release_key,
            ) from None
