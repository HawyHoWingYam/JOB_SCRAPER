from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.orm import Session

from app.job_intelligence.current_taxonomies.read_model import (
    CurrentJobSkillStateView,
    CurrentTaxonomyReader,
)
from app.job_intelligence.source_attributes import (
    SourceJobAttributes,
    SourceJobAttributesView,
)
from app.models.source_job_attributes import (
    EmploymentType,
    JobEmploymentType,
    JobSourceAttributeProjection,
)


def _current_skill_state_payload(
    state: CurrentJobSkillStateView | None,
) -> dict[str, object] | None:
    if state is None:
        return None
    return {
        "job_id": str(state.job_id),
        "skills": [
            {
                "code": skill.code,
                "name": skill.name,
                "source": skill.source,
                "confidence": skill.confidence,
                "provenance": dict(skill.provenance),
                "mention_count": skill.mention_count,
            }
            for skill in state.skills
        ],
    }


@dataclass(frozen=True)
class JobIntelligenceDomainAvailabilityView:
    available: bool
    unavailable_code: str | None

    def to_payload(self) -> dict[str, object]:
        return {
            "available": self.available,
            "unavailable_code": self.unavailable_code,
        }


@dataclass(frozen=True)
class JobIntelligenceJobDetailView:
    source_attributes: SourceJobAttributesView | None
    source_attributes_availability: JobIntelligenceDomainAvailabilityView
    skill_state: CurrentJobSkillStateView | None
    skill_availability: JobIntelligenceDomainAvailabilityView

    def to_payload(self) -> dict[str, object]:
        source_payload = self._source_attributes_payload()
        skill_payload = _current_skill_state_payload(self.skill_state)
        return {
            **source_payload,
            "skill_state": skill_payload,
            "skills": (
                [skill.name for skill in self.skill_state.skills]
                if self.skill_state is not None
                else []
            ),
            "job_intelligence_availability": {
                "source_attributes": (self.source_attributes_availability.to_payload()),
                "skills": self.skill_availability.to_payload(),
            },
        }

    def _source_attributes_payload(self) -> dict[str, object]:
        view = self.source_attributes
        if view is None:
            return {
                "source_classification_paths": [],
                "employment_types": [],
                "source_employment_labels": [],
            }
        return {
            "source_classification_paths": [
                {
                    "id": str(path.id),
                    "source_site": view.source_site,
                    "source_order": path.source_order,
                    "nodes": [
                        {
                            "source_position": node.source_position,
                            "native_depth": node.native_depth,
                            "source_classification_id": (node.source_classification_id),
                            "native_id": node.native_id,
                            "label": node.label,
                        }
                        for node in path.nodes
                    ],
                    "is_primary": path.is_primary,
                    "primary_basis": path.primary_basis,
                    "provenance": dict(path.provenance),
                }
                for path in view.source_classification_paths
            ],
            "employment_types": [
                {
                    "code": item.code,
                    "label": item.label,
                    "sort_order": item.sort_order,
                }
                for item in view.employment_types
            ],
            "source_employment_labels": [
                {
                    "id": str(item.id),
                    "source_site": view.source_site,
                    "source_order": item.source_order,
                    "raw_code": item.raw_code,
                    "raw_label": item.raw_label,
                    "normalized_lookup_key": item.normalized_lookup_key,
                    "mapped_type_code": item.mapped_type_code,
                    "mapping_id": item.mapping_id,
                    "provenance": dict(item.provenance),
                }
                for item in view.source_employment_labels
            ],
        }


class JobIntelligenceProductReadModel:
    """Compose current taxonomy state for read-only product surfaces."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def get_job_detail(
        self,
        *,
        job_id: UUID,
        company_id: UUID,
    ) -> JobIntelligenceJobDetailView:
        del company_id
        source_attributes, source_availability = self._source_attributes(job_id)
        skill_state, skill_availability = self._skill_job_state(job_id)
        return JobIntelligenceJobDetailView(
            source_attributes=source_attributes,
            source_attributes_availability=source_availability,
            skill_state=skill_state,
            skill_availability=skill_availability,
        )

    def get_company_detail(self, company_id: UUID) -> dict[str, object]:
        return self.get_company_details((company_id,))[company_id]

    def get_company_details(
        self,
        company_ids: tuple[UUID, ...] | list[UUID],
    ) -> dict[UUID, dict[str, object]]:
        ordered_ids = tuple(dict.fromkeys(company_ids))
        if not ordered_ids:
            return {}
        return {company_id: {} for company_id in ordered_ids}

    def get_employment_type_states(
        self,
        job_ids: tuple[UUID, ...] | list[UUID],
    ) -> dict[UUID, dict[str, object]]:
        ordered_ids = tuple(dict.fromkeys(job_ids))
        if not ordered_ids:
            return {}

        projected_job_ids = {
            job_id
            for (job_id,) in self.db.query(JobSourceAttributeProjection.job_id)
            .filter(JobSourceAttributeProjection.job_id.in_(ordered_ids))
            .all()
        }
        employment_types_by_job: dict[UUID, list[dict[str, object]]] = defaultdict(list)
        rows = (
            self.db.query(JobEmploymentType.job_id, EmploymentType)
            .join(
                EmploymentType,
                EmploymentType.code == JobEmploymentType.employment_type_code,
            )
            .filter(JobEmploymentType.job_id.in_(ordered_ids))
            .order_by(
                JobEmploymentType.job_id,
                EmploymentType.sort_order,
                EmploymentType.code,
            )
            .all()
        )
        for job_id, employment_type in rows:
            employment_types_by_job[job_id].append(
                {
                    "code": employment_type.code,
                    "label": employment_type.label,
                    "sort_order": employment_type.sort_order,
                }
            )

        return {
            job_id: {
                "employment_types": employment_types_by_job.get(job_id, []),
                "source_attributes_availability": (
                    JobIntelligenceDomainAvailabilityView(
                        available=True,
                        unavailable_code=None,
                    ).to_payload()
                    if job_id in projected_job_ids
                    else JobIntelligenceDomainAvailabilityView(
                        available=False,
                        unavailable_code="SOURCE_JOB_ATTRIBUTES_NOT_PROJECTED",
                    ).to_payload()
                ),
            }
            for job_id in ordered_ids
        }

    def get_governed_skill_name_states(
        self,
        job_ids: tuple[UUID, ...] | list[UUID],
    ) -> dict[UUID, dict[str, object]]:
        ordered_ids = tuple(dict.fromkeys(job_ids))
        if not ordered_ids:
            return {}

        states = CurrentTaxonomyReader(self.db).get_job_skill_states(ordered_ids)
        available = JobIntelligenceDomainAvailabilityView(
            available=True,
            unavailable_code=None,
        ).to_payload()
        return {
            job_id: {
                "governed_skill_names": [skill.name for skill in states[job_id].skills],
                "skills_availability": available,
            }
            for job_id in ordered_ids
        }

    def _source_attributes(
        self,
        job_id: UUID,
    ) -> tuple[SourceJobAttributesView | None, JobIntelligenceDomainAvailabilityView,]:
        try:
            view = SourceJobAttributes(self.db).get(job_id)
        except ValueError:
            return None, JobIntelligenceDomainAvailabilityView(
                available=False,
                unavailable_code="SOURCE_JOB_ATTRIBUTES_NOT_PROJECTED",
            )
        return view, JobIntelligenceDomainAvailabilityView(
            available=True,
            unavailable_code=None,
        )

    def _skill_job_state(
        self,
        job_id: UUID,
    ) -> tuple[CurrentJobSkillStateView | None, JobIntelligenceDomainAvailabilityView,]:
        view = CurrentTaxonomyReader(self.db).get_job_skills(job_id)
        return view, JobIntelligenceDomainAvailabilityView(
            available=True,
            unavailable_code=None,
        )


__all__ = [
    "JobIntelligenceDomainAvailabilityView",
    "JobIntelligenceJobDetailView",
    "JobIntelligenceProductReadModel",
]
