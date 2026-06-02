"""Job category normalization service for source-guided taxonomy resolution."""

from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy.orm import Session

from app.models import JobDomain, JobCategory, JobSubcategory
from app.services.job_taxonomy_registry import (
    SourceBoundTaxonomySlice,
    get_job_taxonomy_registry,
)


class JobCategoryNormalizer:
    def __init__(self, db: Session, registry=None):
        self.db = db
        self.registry = registry or get_job_taxonomy_registry()

    def normalize_category(
        self,
        job_title: str,
        job_description: str = "",
        classification: Optional[dict] = None,
        source_classification_id: Optional[str] = None,
        source_classification_name: Optional[str] = None,
        source_subclassification_name: Optional[str] = None,
    ) -> uuid.UUID:
        """Compatibility wrapper for resolving a taxonomy decision."""
        if source_classification_id:
            return self.resolve_taxonomy_decision(
                classification or {},
                source_classification_id=source_classification_id,
                source_classification_name=source_classification_name,
                source_subclassification_name=source_subclassification_name,
            )

        domain_name, category_name, subcategory_name = self._infer_legacy_hierarchy(
            job_title,
            job_description,
        )
        return self._get_or_create_path(
            domain_name,
            category_name,
            subcategory_name,
            allow_create=True,
        )

    def resolve_taxonomy_decision(
        self,
        classification: dict,
        source_classification_id: str,
        source_classification_name: Optional[str] = None,
        source_subclassification_name: Optional[str] = None,
        conservative_mode: bool = False,
        cross_domain_min_confidence: float = 0.9,
        job_title: Optional[str] = None,
        job_description: str = "",
        extracted_skills: Optional[list[dict | str]] = None,
    ) -> uuid.UUID:
        """Resolve an AI taxonomy decision into a concrete subcategory id."""
        source_slice = self.registry.get_allowed_slice(
            source_classification_id=source_classification_id,
            source_classification_name=source_classification_name,
            source_subclassification_name=source_subclassification_name,
        )
        source_decision = (
            classification.get("source_path_decision")
            or classification.get("taxonomy_decision")
            or {}
        )
        final_decision = classification.get("final_taxonomy_decision")

        source_path = self._resolve_path_from_decision(source_decision, source_slice)
        source_fallback_path = (*self.build_default_path(source_slice), False)
        source_path = self._normalize_governed_path(
            source_path,
            fallback_path=source_fallback_path,
            governance_override=bool(classification.get("governance_override")),
        )
        final_path = self._resolve_open_path_from_decision(
            final_decision or self._decision_from_resolved_path(source_path),
            fallback_path=source_path,
        )
        final_path = self._normalize_governed_path(
            final_path,
            fallback_path=source_path,
            governance_override=bool(classification.get("governance_override")),
        )

        domain_name, category_name, subcategory_name, allow_create = (
            self._select_resolved_path(
                classification,
                source_path=source_path,
                final_path=final_path,
                conservative_mode=conservative_mode,
                cross_domain_min_confidence=cross_domain_min_confidence,
            )
        )
        domain_name, category_name, subcategory_name, allow_create = self._prefer_specific_default_over_generic(
            (domain_name, category_name, subcategory_name, allow_create),
            source_slice,
            source_subclassification_name=source_subclassification_name,
            job_title=job_title,
            job_description=job_description,
            extracted_skills=extracted_skills,
            governance_override=bool(classification.get("governance_override")),
        )
        domain_name, category_name, subcategory_name, allow_create = (
            self._prefer_infrastructure_support_for_devops_like_signals(
                (domain_name, category_name, subcategory_name, allow_create),
                source_slice,
                source_subclassification_name=source_subclassification_name,
                job_title=job_title,
                job_description=job_description,
                extracted_skills=extracted_skills,
                governance_override=bool(classification.get("governance_override")),
            )
        )
        domain_name, category_name, subcategory_name, allow_create = (
            self._prefer_backend_development_for_explicit_software_signals(
                (domain_name, category_name, subcategory_name, allow_create),
                source_slice,
                source_subclassification_name=source_subclassification_name,
                job_title=job_title,
                job_description=job_description,
                extracted_skills=extracted_skills,
                governance_override=bool(classification.get("governance_override")),
            )
        )
        resolved_path = (domain_name, category_name, subcategory_name)
        return self._get_or_create_path(
            domain_name,
            category_name,
            subcategory_name,
            allow_create=(
                allow_create
                if classification.get("governance_override")
                else resolved_path == source_fallback_path[:3]
            ),
        )

    def _prefer_specific_default_over_generic(
        self,
        resolved_path: tuple[str, str, str, bool],
        source_slice: SourceBoundTaxonomySlice,
        *,
        source_subclassification_name: Optional[str],
        job_title: Optional[str],
        job_description: str,
        extracted_skills: Optional[list[dict | str]],
        governance_override: bool,
    ) -> tuple[str, str, str, bool]:
        """Prefer a more specific source default when the resolved leaf is generic."""
        if governance_override:
            return resolved_path

        default_domain, default_category, default_subcategory = source_slice.default_path
        if default_subcategory == "General":
            return resolved_path

        _, category_name, subcategory_name, _ = resolved_path
        if category_name != "General" and subcategory_name != "General":
            return resolved_path

        if (
            source_subclassification_name == "Engineering - Software"
            and default_category == "Software Development"
            and default_subcategory == "Backend Development"
            and not self._has_strong_backend_development_signals(
                job_title=job_title,
                job_description=job_description,
                extracted_skills=extracted_skills,
            )
        ):
            return resolved_path

        return (default_domain, default_category, default_subcategory, False)

    def _prefer_infrastructure_support_for_devops_like_signals(
        self,
        resolved_path: tuple[str, str, str, bool],
        source_slice: SourceBoundTaxonomySlice,
        *,
        source_subclassification_name: Optional[str],
        job_title: Optional[str],
        job_description: str,
        extracted_skills: Optional[list[dict | str]],
        governance_override: bool,
    ) -> tuple[str, str, str, bool]:
        """Shift obvious DevOps/infra software roles out of backend development."""
        if governance_override:
            return resolved_path
        if source_subclassification_name != "Engineering - Software":
            return resolved_path

        domain_name, category_name, subcategory_name, allow_create = resolved_path
        if category_name != "Software Development" or subcategory_name != "Backend Development":
            return resolved_path
        if "Infrastructure & Support" not in source_slice.allowed_categories:
            return resolved_path
        if "Systems Administration" not in source_slice.allowed_subcategories:
            return resolved_path

        normalized_text = " ".join(
            str(value or "").strip().lower()
            for value in (job_title, job_description)
        )
        normalized_skill_names = {
            self._normalize_skill_signal_name(skill)
            for skill in (extracted_skills or [])
        }

        title_has_strong_signal = any(
            token in str(job_title or "").lower()
            for token in (
                "devops",
                "site reliability",
                "sre",
                "platform engineer",
                "platform engineering",
                "mlops",
            )
        )
        title_has_explicit_backend_marker = any(
            token in str(job_title or "").lower()
            for token in (
                "backend",
                "microservice",
                "node.js",
                "java developer",
                "golang",
                "go developer",
            )
        )
        infra_signal_hits = {
            signal
            for signal in (
                "ci/cd",
                "continuous integration",
                "continuous delivery",
                "terraform",
                "kubernetes",
                "docker",
                "openshift",
                "ansible",
                "puppet",
                "chef",
                "bash",
                "linux",
                "jenkins",
                "cloud architecture",
                "cloud infrastructure",
                "virtualization",
                "devsecops",
                "gitops",
            )
            if signal in normalized_text or signal in normalized_skill_names
        }
        cloud_platform_hits = {
            signal
            for signal in ("aws", "azure", "alicloud", "gcp")
            if signal in normalized_text or signal in normalized_skill_names
        }
        devtestops_signal_hits = {
            signal
            for signal in (
                "test environment",
                "test environments",
                "environment provisioning",
                "automated test framework",
                "automated test frameworks",
                "ci/cd pipeline",
                "ci/cd pipelines",
                "performance testing",
                "load testing",
                "reliability testing",
            )
            if signal in normalized_text
        }

        if not title_has_strong_signal and len(infra_signal_hits | cloud_platform_hits) < 4:
            if title_has_explicit_backend_marker:
                return resolved_path
            infra_tool_hits = {
                signal
                for signal in ("terraform", "kubernetes", "docker", "ansible", "linux")
                if signal in normalized_text or signal in normalized_skill_names
            }
            if len(devtestops_signal_hits) < 3 or len(infra_tool_hits) < 2:
                return resolved_path

        return (
            domain_name,
            "Infrastructure & Support",
            "Systems Administration",
            allow_create,
        )

    def _normalize_skill_signal_name(self, skill: dict | str) -> str:
        if isinstance(skill, dict):
            return str(
                skill.get("name")
                or skill.get("skill")
                or skill.get("raw_name")
                or skill.get("normalized_name")
                or ""
            ).strip().lower()
        if isinstance(skill, str):
            return skill.strip().lower()
        return ""

    def _has_strong_backend_development_signals(
        self,
        *,
        job_title: Optional[str],
        job_description: str,
        extracted_skills: Optional[list[dict | str]],
    ) -> bool:
        normalized_title = str(job_title or "").lower()
        normalized_text = " ".join(
            str(value or "").strip().lower()
            for value in (job_title, job_description)
        )
        normalized_skill_names = {
            self._normalize_skill_signal_name(skill)
            for skill in (extracted_skills or [])
        }
        explicit_backend_title = any(
            token in normalized_title
            for token in (
                "backend engineer",
                "back end",
                "microservice",
                "api developer",
                "java developer",
            )
        )
        backend_signal_hits = {
            signal
            for signal in (
                "api",
                "apis",
                "restful api",
                "integration layer",
                "backend service",
                "backend services",
                "microservices",
                "node.js",
                "java",
                "golang",
                "go code",
            )
            if signal in normalized_text or signal in normalized_skill_names
        }
        return explicit_backend_title or len(backend_signal_hits) >= 3

    def _prefer_backend_development_for_explicit_software_signals(
        self,
        resolved_path: tuple[str, str, str, bool],
        source_slice: SourceBoundTaxonomySlice,
        *,
        source_subclassification_name: Optional[str],
        job_title: Optional[str],
        job_description: str,
        extracted_skills: Optional[list[dict | str]],
        governance_override: bool,
    ) -> tuple[str, str, str, bool]:
        """Protect explicit backend/microservices software roles from drifting into infra."""
        if governance_override:
            return resolved_path
        if source_subclassification_name != "Engineering - Software":
            return resolved_path

        domain_name, category_name, subcategory_name, allow_create = resolved_path
        if category_name != "Infrastructure & Support" or subcategory_name != "Systems Administration":
            return resolved_path
        if "Software Development" not in source_slice.allowed_categories:
            return resolved_path
        if "Backend Development" not in source_slice.allowed_subcategories:
            return resolved_path

        if not self._has_strong_backend_development_signals(
            job_title=job_title,
            job_description=job_description,
            extracted_skills=extracted_skills,
        ):
            return resolved_path

        return (
            domain_name,
            "Software Development",
            "Backend Development",
            allow_create,
        )

    def get_taxonomy_candidate_slice(
        self,
        job_title: Optional[str] = None,
        job_description: str = "",
        limit: int = 10,
        *,
        source_classification_id: Optional[str] = None,
        source_classification_name: Optional[str] = None,
        source_subclassification_name: Optional[str] = None,
    ) -> dict:
        """Return the candidate slice that should bound job classification."""
        if source_classification_id:
            source_slice = self.registry.get_allowed_slice(
                source_classification_id=source_classification_id,
                source_classification_name=source_classification_name,
                source_subclassification_name=source_subclassification_name,
            )
            return {
                "source_classification_id": source_slice.source_classification_id,
                "source_classification_name": source_slice.source_classification_name,
                "source_subclassification_name": source_slice.source_subclassification_name,
                "allowed_domains": source_slice.allowed_domains[:limit],
                "allowed_categories": source_slice.allowed_categories[:limit],
                "allowed_subcategories": source_slice.allowed_subcategories[:limit],
                "default_path": list(source_slice.default_path),
            }

        domain_name, category_name, subcategory_name = self._infer_legacy_hierarchy(
            job_title or "",
            job_description,
        )
        return {
            "source_classification_id": None,
            "source_classification_name": domain_name,
            "source_subclassification_name": None,
            "allowed_domains": [domain_name],
            "allowed_categories": [category_name, "General"],
            "allowed_subcategories": [subcategory_name, "General"],
            "default_path": [domain_name, "General", "General"],
        }

    def get_category_hierarchy(self, subcategory_id: uuid.UUID) -> dict:
        """Return full hierarchy path for a subcategory."""
        subcategory = self.db.query(JobSubcategory).filter_by(id=subcategory_id).first()
        if not subcategory:
            return {}

        return {
            "subcategory": subcategory.name,
            "category": subcategory.category.name,
            "domain": subcategory.category.domain.name,
        }

    def _resolve_path_from_decision(
        self,
        decision: dict,
        source_slice: SourceBoundTaxonomySlice,
    ) -> tuple[str, str, str, bool]:
        """Clamp a classifier decision into a valid or default taxonomy path."""
        fallback_domain, fallback_category, fallback_subcategory = self.build_default_path(
            source_slice
        )

        domain = decision.get("domain")
        category = decision.get("category")
        subcategory = decision.get("subcategory")
        resolution = decision.get("resolution")

        if domain not in source_slice.allowed_domains:
            return fallback_domain, fallback_category, fallback_subcategory, False

        if category not in source_slice.allowed_categories:
            return fallback_domain, fallback_category, fallback_subcategory, False

        if subcategory in source_slice.allowed_subcategories:
            return domain, category, subcategory, False

        if resolution == "create_new" and subcategory:
            return domain, category, subcategory, True

        return fallback_domain, fallback_category, fallback_subcategory, False

    def build_default_path(
        self, source_slice: SourceBoundTaxonomySlice
    ) -> tuple[str, str, str]:
        """Return the default fallback path for a source slice."""
        return source_slice.default_path

    def _resolve_open_path_from_decision(
        self,
        decision: dict,
        fallback_path: tuple[str, str, str, bool],
    ) -> tuple[str, str, str, bool]:
        """Resolve a final path without constraining it to the source domain."""
        domain = decision.get("domain")
        category = decision.get("category")
        subcategory = decision.get("subcategory")

        if not (domain and category and subcategory):
            return fallback_path

        return (
            domain,
            category,
            subcategory,
            decision.get("resolution") == "create_new",
        )

    def _select_resolved_path(
        self,
        classification: dict,
        source_path: tuple[str, str, str, bool],
        final_path: tuple[str, str, str, bool],
        conservative_mode: bool,
        cross_domain_min_confidence: float,
    ) -> tuple[str, str, str, bool]:
        """Pick the committed taxonomy path from source/final candidates."""
        if not conservative_mode:
            return final_path

        if not self._is_cross_domain(classification, source_path, final_path):
            return final_path

        confidence = self._coerce_confidence(
            classification.get("cross_domain_confidence")
        )
        if confidence >= cross_domain_min_confidence:
            return final_path

        return source_path

    def _is_cross_domain(
        self,
        classification: dict,
        source_path: tuple[str, str, str, bool],
        final_path: tuple[str, str, str, bool],
    ) -> bool:
        """Determine whether the final path crosses the source domain boundary."""
        if source_path[0] and final_path[0]:
            return source_path[0] != final_path[0]
        return bool(classification.get("cross_domain"))

    def _coerce_confidence(self, value: object) -> float:
        """Clamp configured or model confidence into the 0-1 range."""
        try:
            return max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            return 0.0

    def _decision_from_resolved_path(
        self, path: tuple[str, str, str, bool]
    ) -> dict[str, object]:
        """Convert a resolved path tuple back into decision shape."""
        return {
            "domain": path[0],
            "category": path[1],
            "subcategory": path[2],
            "resolution": "create_new" if path[3] else "match_existing",
        }

    def _get_or_create_path(
        self,
        domain_name: str,
        category_name: str,
        subcategory_name: str,
        allow_create: bool = False,
    ) -> uuid.UUID:
        """Resolve a taxonomy path to ids, creating hidden nodes when needed."""
        domain = self._find_domain(domain_name)
        if domain is None:
            if not allow_create:
                raise ValueError(f"Unknown governed domain: {domain_name}")
            domain = self._create_domain(domain_name)

        category = self._find_category(domain.id, category_name)
        if category is None:
            if not allow_create:
                raise ValueError(f"Unknown governed category: {category_name}")
            category = self._create_category(domain.id, category_name)

        subcategory = self._find_subcategory(category.id, subcategory_name)
        if subcategory is None:
            if not allow_create:
                raise ValueError(f"Unknown governed subcategory: {subcategory_name}")
            subcategory = self._create_subcategory(category.id, subcategory_name)

        return subcategory.id

    def _path_exists(
        self,
        domain_name: str,
        category_name: str,
        subcategory_name: str,
    ) -> bool:
        """Return whether the governed taxonomy already contains the full path."""
        domain = self._find_domain(domain_name)
        if domain is None:
            return False

        category = self._find_category(domain.id, category_name)
        if category is None:
            return False

        return self._find_subcategory(category.id, subcategory_name) is not None

    def _normalize_governed_path(
        self,
        path: tuple[str, str, str, bool],
        fallback_path: tuple[str, str, str, bool],
        governance_override: bool,
    ) -> tuple[str, str, str, bool]:
        """Clamp non-override paths to existing governed taxonomy nodes."""
        if governance_override or self._path_exists(*path[:3]):
            return path
        return fallback_path

    def _find_domain(self, name: str) -> Optional[JobDomain]:
        return self.db.query(JobDomain).filter_by(name=name).first()

    def _find_category(self, domain_id: uuid.UUID, name: str) -> Optional[JobCategory]:
        return self.db.query(JobCategory).filter_by(domain_id=domain_id, name=name).first()

    def _find_subcategory(
        self,
        category_id: uuid.UUID,
        name: str,
    ) -> Optional[JobSubcategory]:
        return self.db.query(JobSubcategory).filter_by(
            category_id=category_id,
            name=name,
        ).first()

    def _create_domain(self, name: str) -> JobDomain:
        domain = JobDomain(
            name=name,
            created_by="ai",
            is_auto_created=True,
            is_filter_visible=False,
            usage_count=0,
            distinct_job_count=0,
        )
        self.db.add(domain)
        self.db.flush()
        return domain

    def _create_category(self, domain_id: uuid.UUID, name: str) -> JobCategory:
        category = JobCategory(
            domain_id=domain_id,
            name=name,
            created_by="ai",
            is_auto_created=True,
            is_filter_visible=False,
            usage_count=0,
            distinct_job_count=0,
        )
        self.db.add(category)
        self.db.flush()
        return category

    def _create_subcategory(
        self,
        category_id: uuid.UUID,
        name: str,
    ) -> JobSubcategory:
        subcategory = JobSubcategory(
            category_id=category_id,
            name=name,
            created_by="ai",
            is_auto_created=True,
            is_filter_visible=False,
            usage_count=0,
            distinct_job_count=0,
        )
        self.db.add(subcategory)
        self.db.flush()
        return subcategory

    def _infer_legacy_hierarchy(
        self,
        title: str,
        description: str,
    ) -> tuple[str, str, str]:
        """Legacy fallback for call sites that do not pass source fields yet."""
        keywords = f"{title} {description}".lower()

        if any(token in keywords for token in ["support", "help desk", "system"]):
            return (
                "Information & Communication Technology",
                "Infrastructure & Support",
                "Application Support",
            )
        if any(token in keywords for token in ["backend", "frontend", "developer", "engineer"]):
            return (
                "Information & Communication Technology",
                "Software Development",
                "Backend Development",
            )
        if "design" in keywords:
            return (
                "Design & Architecture",
                "Graphic Design",
                "Brand Design",
            )
        return (
            "Information & Communication Technology",
            "General",
            "General",
        )


_normalizer_instance = None


def get_job_category_normalizer(db: Session) -> JobCategoryNormalizer:
    """Get or create job category normalizer singleton."""
    global _normalizer_instance
    if _normalizer_instance is None:
        _normalizer_instance = JobCategoryNormalizer(db)
    return _normalizer_instance
