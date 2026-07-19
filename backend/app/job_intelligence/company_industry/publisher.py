from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
import re
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.job_intelligence.company_industry.seed import seed_content_hash
from app.job_intelligence.foundation import (
    RevisionManifest,
    RevisionRef,
    RevisionStore,
    SeedIssue,
    SeedValidator,
    ValidationReport,
)
from app.models.company_industry import (
    CompanyIndustryActiveRevision,
    CompanyIndustryCrosswalkEdge,
    CompanyIndustryTaxonomyNode,
    CompanyIndustryTaxonomyRelease,
)
from app.models.governance import GovernanceRevision
from app.utils.time import utc_now


_LEVELS = ("section", "division", "group", "class", "subclass")
_PARENT_LEVEL = {
    "division": "section",
    "group": "division",
    "class": "group",
    "subclass": "class",
}
_CODE_PATTERNS = {
    "section": re.compile(r"[A-U]"),
    "division": re.compile(r"[0-9]{2}"),
    "group": re.compile(r"[0-9]{3}"),
    "class": re.compile(r"[0-9]{4}"),
    "subclass": re.compile(r"[0-9]{6}"),
}


@dataclass(frozen=True)
class CompanyIndustryActivationRef:
    revision_id: UUID
    content_hash: str
    lock_version: int
    activated_at: datetime


def _document_issues(document: Mapping[str, Any]) -> Iterable[SeedIssue]:
    required_scalars = {
        "standard": "HSIC",
        "release": "V2.0",
    }
    for field, expected in required_scalars.items():
        if document.get(field) != expected:
            yield SeedIssue(
                json_path=f"$.{field}",
                code="company_industry_release_invalid",
                message=f"{field} must be {expected!r}",
            )
    source = document.get("source")
    if not isinstance(source, Mapping):
        yield SeedIssue(
            json_path="$.source",
            code="company_industry_source_missing",
            message="HSIC source metadata is required",
        )
        return
    for field in (
        "publisher",
        "rights_owner",
        "overview_url",
        "hierarchy_url",
        "terms_url",
        "retrieved_at",
        "raw_sha256",
        "modifications",
    ):
        value = source.get(field)
        if value is None or value == "" or value == []:
            yield SeedIssue(
                json_path=f"$.source.{field}",
                code="company_industry_source_metadata_missing",
                message=f"HSIC source metadata field {field!r} is required",
            )


def _node_issues(document: Mapping[str, Any]) -> Iterable[SeedIssue]:
    raw_nodes = document.get("nodes")
    if not isinstance(raw_nodes, list):
        yield SeedIssue(
            json_path="$.nodes",
            code="company_industry_nodes_missing",
            message="HSIC nodes must be an array",
        )
        return

    nodes = [node for node in raw_nodes if isinstance(node, Mapping)]
    if len(nodes) != len(raw_nodes):
        yield SeedIssue(
            json_path="$.nodes",
            code="company_industry_node_invalid",
            message="Every HSIC node must be an object",
        )
    by_code: dict[str, Mapping[str, Any]] = {}
    seen_orders: set[int] = set()
    for index, node in enumerate(nodes):
        path = f"$.nodes[{index}]"
        code = str(node.get("code") or "").strip()
        level = str(node.get("level") or "").strip()
        pattern = _CODE_PATTERNS.get(level)
        if pattern is None:
            yield SeedIssue(
                json_path=f"{path}.level",
                code="company_industry_level_invalid",
                message=f"Unsupported HSIC level {level!r}",
                related_id=code or None,
            )
        elif pattern.fullmatch(code) is None:
            yield SeedIssue(
                json_path=f"{path}.code",
                code="company_industry_code_invalid",
                message=f"Code {code!r} is invalid for {level}",
                related_id=code or None,
            )
        if code in by_code:
            yield SeedIssue(
                json_path=f"{path}.code",
                code="company_industry_code_duplicate",
                message=f"HSIC code {code!r} is duplicated",
                related_id=code or None,
            )
        elif code:
            by_code[code] = node
        labels = node.get("labels")
        for language in ("en", "zh_hant", "zh_hans"):
            label = labels.get(language) if isinstance(labels, Mapping) else None
            if not isinstance(label, str) or not label.strip():
                yield SeedIssue(
                    json_path=f"{path}.labels.{language}",
                    code="company_industry_label_missing",
                    message=f"HSIC {language} label is required",
                    related_id=code or None,
                )
        source_order = node.get("source_order")
        if (
            not isinstance(source_order, int)
            or source_order <= 0
            or source_order in seen_orders
        ):
            yield SeedIssue(
                json_path=f"{path}.source_order",
                code="company_industry_source_order_invalid",
                message="HSIC source order must be a unique positive integer",
                related_id=code or None,
            )
        elif isinstance(source_order, int):
            seen_orders.add(source_order)

    counts = Counter(str(node.get("level") or "") for node in nodes)
    expected_counts = document.get("expected_counts")
    if not isinstance(expected_counts, Mapping):
        yield SeedIssue(
            json_path="$.expected_counts",
            code="company_industry_expected_counts_missing",
            message="HSIC expected counts are required",
        )
    else:
        for level in _LEVELS:
            expected = expected_counts.get(level)
            if (
                not isinstance(expected, int)
                or expected < 0
                or counts[level] != expected
            ):
                yield SeedIssue(
                    json_path=f"$.expected_counts.{level}",
                    code="company_industry_count_mismatch",
                    message=(
                        f"Expected {expected!r} {level} nodes but found {counts[level]}"
                    ),
                    related_id=level,
                )

    for index, node in enumerate(nodes):
        code = str(node.get("code") or "").strip()
        level = str(node.get("level") or "").strip()
        parent_code = node.get("parent_code")
        path = f"$.nodes[{index}].parent_code"
        if level == "section":
            if parent_code is not None:
                yield SeedIssue(
                    json_path=path,
                    code="company_industry_section_parent_forbidden",
                    message="An HSIC Section cannot have a parent",
                    related_id=code or None,
                )
            continue
        parent = by_code.get(str(parent_code or ""))
        if parent is None:
            yield SeedIssue(
                json_path=path,
                code="company_industry_parent_missing",
                message=f"Parent {parent_code!r} does not exist",
                related_id=code or None,
            )
            continue
        visited = {code}
        cursor: Mapping[str, Any] | None = parent
        while cursor is not None:
            cursor_code = str(cursor.get("code") or "")
            if cursor_code in visited:
                yield SeedIssue(
                    json_path=path,
                    code="company_industry_cycle",
                    message=f"HSIC hierarchy cycle detected at {cursor_code!r}",
                    related_id=code or None,
                )
                break
            visited.add(cursor_code)
            next_parent = cursor.get("parent_code")
            cursor = by_code.get(str(next_parent)) if next_parent is not None else None
        expected_parent_level = _PARENT_LEVEL.get(level)
        if parent.get("level") != expected_parent_level:
            yield SeedIssue(
                json_path=path,
                code="company_industry_parent_level_invalid",
                message=(
                    f"{level} parent must be {expected_parent_level}, not "
                    f"{parent.get('level')!r}"
                ),
                related_id=code or None,
            )
        elif level != "division":
            prefix_length = {"group": 2, "class": 3, "subclass": 4}.get(level)
            if prefix_length is not None and code[:prefix_length] != parent_code:
                yield SeedIssue(
                    json_path=path,
                    code="company_industry_parent_code_mismatch",
                    message=f"HSIC code {code!r} does not belong under {parent_code!r}",
                    related_id=code or None,
                )


def _content_hash_issues(document: Mapping[str, Any]) -> Iterable[SeedIssue]:
    content_hash = document.get("content_hash")
    try:
        actual = seed_content_hash(document)
    except (KeyError, TypeError, ValueError):
        return
    if content_hash != actual:
        yield SeedIssue(
            json_path="$.content_hash",
            code="company_industry_content_hash_mismatch",
            message="HSIC seed content hash does not match its governed content",
        )


def _crosswalk_issues(document: Mapping[str, Any]) -> Iterable[SeedIssue]:
    raw_crosswalks = document.get("crosswalks")
    if not isinstance(raw_crosswalks, list):
        yield SeedIssue(
            json_path="$.crosswalks",
            code="company_industry_crosswalks_invalid",
            message="Company Industry crosswalks must be an array",
        )
        return
    node_codes = {
        str(node.get("code") or "")
        for node in document.get("nodes", ())
        if isinstance(node, Mapping)
    }
    seen: set[tuple[str, str, str, str]] = set()
    allowed_cardinality = {
        "one_to_one",
        "one_to_many",
        "many_to_one",
        "many_to_many",
    }
    for index, edge in enumerate(raw_crosswalks):
        path = f"$.crosswalks[{index}]"
        if not isinstance(edge, Mapping):
            yield SeedIssue(
                json_path=path,
                code="company_industry_crosswalk_invalid",
                message="Each Company Industry crosswalk must be an object",
            )
            continue
        hsic_code = str(edge.get("hsic_code") or "").strip()
        if hsic_code not in node_codes:
            yield SeedIssue(
                json_path=path,
                code="company_industry_crosswalk_hsic_unknown",
                message=f"Crosswalk HSIC code {hsic_code!r} does not exist",
                related_id=hsic_code or None,
            )
        target = (
            str(edge.get("target_standard") or "").strip(),
            str(edge.get("target_release") or "").strip(),
            str(edge.get("target_code") or "").strip(),
        )
        if not all(target):
            yield SeedIssue(
                json_path=path,
                code="company_industry_crosswalk_target_missing",
                message="Crosswalk target standard, release, and code are required",
                related_id=hsic_code or None,
            )
        method = str(edge.get("method") or "")
        if method not in {"official", "project_validated"}:
            yield SeedIssue(
                json_path=path,
                code="company_industry_crosswalk_method_invalid",
                message="Crosswalk method must be official or project_validated",
                related_id=hsic_code or None,
            )
        if edge.get("cardinality") not in allowed_cardinality:
            yield SeedIssue(
                json_path=path,
                code="company_industry_crosswalk_cardinality_invalid",
                message="Crosswalk cardinality is invalid",
                related_id=hsic_code or None,
            )
        provenance = edge.get("provenance")
        if not isinstance(provenance, Mapping) or not provenance:
            yield SeedIssue(
                json_path=path,
                code="company_industry_crosswalk_provenance_missing",
                message="Crosswalk provenance is required",
                related_id=hsic_code or None,
            )
        confidence = edge.get("confidence")
        if confidence is not None and (
            not isinstance(confidence, (int, float)) or not 0 <= float(confidence) <= 1
        ):
            yield SeedIssue(
                json_path=path,
                code="company_industry_crosswalk_confidence_invalid",
                message="Crosswalk confidence must be between zero and one",
                related_id=hsic_code or None,
            )
        identity = (hsic_code, *target)
        if identity in seen:
            yield SeedIssue(
                json_path=path,
                code="company_industry_crosswalk_duplicate",
                message="Company Industry crosswalk edge is duplicated",
                related_id=hsic_code or None,
            )
        seen.add(identity)


class CompanyIndustryPublisher:
    """Validate and publish immutable Company Industry taxonomy revisions."""

    domain = "company-industry"

    def __init__(self, db: Session | None = None) -> None:
        self.db = db

    @staticmethod
    def validate(document: Mapping[str, Any]) -> ValidationReport:
        return SeedValidator.validate(
            document,
            (
                _document_issues,
                _node_issues,
                _crosswalk_issues,
                _content_hash_issues,
            ),
        )

    def _require_db(self) -> Session:
        if self.db is None:
            raise RuntimeError("CompanyIndustryPublisher requires a database Session")
        return self.db

    def materialize(self, document: Mapping[str, Any]) -> RevisionRef:
        report = self.validate(document)
        if not report.valid:
            raise ValueError("Company Industry seed validation failed")
        db = self._require_db()
        content_hash = str(document["content_hash"])
        expected_counts = dict(document["expected_counts"])
        manifest = RevisionManifest(
            domain=self.domain,
            release_key=str(document["release_key"]),
            content_hash=content_hash,
            source_metadata={
                **dict(document["source"]),
                "standard": str(document["standard"]),
                "release": str(document["release"]),
                "expected_counts": expected_counts,
            },
        )
        revision = RevisionStore(db).publish(manifest)
        existing = db.get(CompanyIndustryTaxonomyRelease, revision.revision_id)
        if existing is not None:
            if (
                existing.status == "ready"
                and existing.content_hash == revision.content_hash
                and existing.expected_counts == expected_counts
                and existing.materialized_counts == expected_counts
            ):
                db.commit()
                return revision
            db.rollback()
            raise ValueError("Company Industry release is incomplete or inconsistent")

        try:
            release = CompanyIndustryTaxonomyRelease(
                revision_id=revision.revision_id,
                standard=str(document["standard"]),
                release=str(document["release"]),
                content_hash=content_hash,
                source_metadata=dict(document["source"]),
                expected_counts=expected_counts,
                materialized_counts={level: 0 for level in _LEVELS},
                expected_total=sum(expected_counts.values()),
                materialized_total=0,
                status="materializing",
            )
            db.add(release)
            db.flush()
            nodes_by_code: dict[str, CompanyIndustryTaxonomyNode] = {}
            materialized_counts: Counter[str] = Counter()
            for item in document["nodes"]:
                parent_code = item.get("parent_code")
                parent = (
                    nodes_by_code.get(str(parent_code))
                    if parent_code is not None
                    else None
                )
                node = CompanyIndustryTaxonomyNode(
                    revision_id=revision.revision_id,
                    code=str(item["code"]),
                    parent_id=parent.id if parent is not None else None,
                    level=str(item["level"]),
                    label_en=str(item["labels"]["en"]),
                    label_zh_hant=str(item["labels"]["zh_hant"]),
                    label_zh_hans=str(item["labels"]["zh_hans"]),
                    source_order=int(item["source_order"]),
                    is_assignable=True,
                    source_metadata={"official_code": str(item["code"])},
                )
                db.add(node)
                db.flush()
                nodes_by_code[node.code] = node
                materialized_counts[node.level] += 1
            for order, edge in enumerate(document.get("crosswalks", ()), start=1):
                hsic_node = nodes_by_code[str(edge["hsic_code"])]
                db.add(
                    CompanyIndustryCrosswalkEdge(
                        taxonomy_revision_id=revision.revision_id,
                        hsic_node_id=hsic_node.id,
                        target_standard=str(edge["target_standard"]),
                        target_release=str(edge["target_release"]),
                        target_code=str(edge["target_code"]),
                        cardinality=str(edge["cardinality"]),
                        method=str(edge["method"]),
                        confidence=edge.get("confidence"),
                        provenance=dict(edge["provenance"]),
                        source_order=order,
                    )
                )
            release.materialized_counts = {
                level: materialized_counts[level] for level in _LEVELS
            }
            release.materialized_total = sum(materialized_counts.values())
            if release.materialized_counts != expected_counts:
                raise ValueError(
                    "Company Industry materialized counts do not match seed"
                )
            release.status = "ready"
            release.ready_at = utc_now()
            db.commit()
            return revision
        except Exception:
            db.rollback()
            raise

    def activate(
        self,
        revision: RevisionRef,
        *,
        expected_lock_version: int,
    ) -> CompanyIndustryActivationRef:
        db = self._require_db()
        if revision.domain != self.domain:
            raise ValueError("Company Industry revision domain is invalid")
        try:
            release = db.get(CompanyIndustryTaxonomyRelease, revision.revision_id)
            governance = db.get(GovernanceRevision, revision.revision_id)
            if (
                release is None
                or release.status != "ready"
                or governance is None
                or release.content_hash != revision.content_hash
                or governance.content_hash != revision.content_hash
            ):
                raise ValueError("Company Industry revision is not ready")
            active = (
                db.query(CompanyIndustryActiveRevision)
                .filter(CompanyIndustryActiveRevision.singleton_key == self.domain)
                .with_for_update()
                .one_or_none()
            )
            if active is None:
                if expected_lock_version != 0:
                    raise ValueError("Company Industry activation is stale")
                active = CompanyIndustryActiveRevision(
                    singleton_key=self.domain,
                    revision_id=revision.revision_id,
                    content_hash=revision.content_hash,
                    lock_version=1,
                    activated_at=utc_now(),
                )
                db.add(active)
            else:
                if active.lock_version != expected_lock_version:
                    raise ValueError("Company Industry activation is stale")
                active.revision_id = revision.revision_id
                active.content_hash = revision.content_hash
                active.lock_version += 1
                active.activated_at = utc_now()
            db.commit()
            db.refresh(active)
            return CompanyIndustryActivationRef(
                revision_id=active.revision_id,
                content_hash=active.content_hash,
                lock_version=active.lock_version,
                activated_at=active.activated_at,
            )
        except Exception:
            db.rollback()
            raise


__all__ = ["CompanyIndustryActivationRef", "CompanyIndustryPublisher"]
