from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Job
from app.models.current_taxonomy import (
    CurrentCompanyIndustryAssignment,
    CurrentTaxonomyNodeRecord,
)
from app.models.source_job_attributes import (
    EmploymentType,
    JobEmploymentType,
    JobSourceClassificationPath,
    JobSourceClassificationPathNode,
)
from app.schemas.job_search import (
    JobSearchFacetsSchema,
    JobSearchFacetOptionSchema,
    JobSearchScopeSchema,
)
from app.search.lexical_query import build_lexical_query


_SOURCE_FIELDS = frozenset({"source_site"})
_SOURCE_CLASSIFICATION_FIELDS = frozenset({"source_classification_ids"})
_COMPANY_INDUSTRY_FIELDS = frozenset(
    {
        "company_industry_node_ids",
        "industry",
    }
)
_EMPLOYMENT_TYPE_FIELDS = frozenset(
    {
        "employment_type",
        "employment_type_codes",
    }
)
_SOURCE_OPTIONS = (
    ("jobsdb", "JobsDB"),
    ("ctgoodjobs", "CTGoodJobs"),
    ("offertoday", "OfferToday"),
)


def _scope_without_fields(
    scope: JobSearchScopeSchema,
    field_names: frozenset[str],
) -> JobSearchScopeSchema:
    layers = []
    for layer in scope.layers:
        filters = layer.structured_filters.model_copy(
            update={field_name: None for field_name in field_names}
        )
        layers.append(
            layer.model_copy(update={"structured_filters": filters})
        )
    return scope.model_copy(update={"layers": layers})


class JobSearchFacets:
    def __init__(self, db: Session):
        self.db = db

    def build(self, scope: JobSearchScopeSchema) -> JobSearchFacetsSchema:
        return JobSearchFacetsSchema(
            sources=self._source_options(scope),
            employment_types=self._employment_type_options(scope),
            source_classifications=self._source_classification_options(scope),
            company_industries=self._company_industry_options(scope),
        )

    def _candidate_job_ids(
        self,
        scope: JobSearchScopeSchema,
        *,
        without_fields: frozenset[str],
    ):
        candidate_scope = _scope_without_fields(scope, without_fields)
        return (
            build_lexical_query(self.db, candidate_scope)
            .enable_eagerloads(False)
            .with_entities(Job.id.label("job_id"))
            .order_by(None)
            .subquery()
        )

    def _source_options(
        self,
        scope: JobSearchScopeSchema,
    ) -> list[JobSearchFacetOptionSchema]:
        candidate_jobs = self._candidate_job_ids(
            scope,
            without_fields=_SOURCE_FIELDS,
        )
        count_rows = (
            self.db.query(
                Job.source_site,
                func.count(func.distinct(candidate_jobs.c.job_id)),
            )
            .join(candidate_jobs, candidate_jobs.c.job_id == Job.id)
            .group_by(Job.source_site)
            .all()
        )
        counts = {source_site: count for source_site, count in count_rows}
        return [
            JobSearchFacetOptionSchema(
                id=source_site,
                label=label,
                count=counts.get(source_site, 0),
                order=order,
            )
            for order, (source_site, label) in enumerate(_SOURCE_OPTIONS, start=1)
        ]

    def _employment_type_options(
        self,
        scope: JobSearchScopeSchema,
    ) -> list[JobSearchFacetOptionSchema]:
        candidate_jobs = self._candidate_job_ids(
            scope,
            without_fields=_EMPLOYMENT_TYPE_FIELDS,
        )
        count_rows = (
            self.db.query(
                JobEmploymentType.employment_type_code,
                func.count(func.distinct(candidate_jobs.c.job_id)),
            )
            .join(
                candidate_jobs,
                candidate_jobs.c.job_id == JobEmploymentType.job_id,
            )
            .group_by(JobEmploymentType.employment_type_code)
            .all()
        )
        counts = {code: count for code, count in count_rows}
        catalog = self.db.query(EmploymentType).order_by(EmploymentType.sort_order)
        return [
            JobSearchFacetOptionSchema(
                id=item.code,
                label=item.label,
                count=counts.get(item.code, 0),
                order=item.sort_order,
            )
            for item in catalog
        ]

    def _source_classification_options(
        self,
        scope: JobSearchScopeSchema,
    ) -> list[JobSearchFacetOptionSchema]:
        candidate_jobs = self._candidate_job_ids(
            scope,
            without_fields=_SOURCE_CLASSIFICATION_FIELDS,
        )
        count_rows = (
            self.db.query(
                JobSourceClassificationPathNode.source_classification_id,
                func.count(func.distinct(candidate_jobs.c.job_id)),
            )
            .join(
                JobSourceClassificationPath,
                JobSourceClassificationPath.id
                == JobSourceClassificationPathNode.path_id,
            )
            .join(
                candidate_jobs,
                candidate_jobs.c.job_id == JobSourceClassificationPath.job_id,
            )
            .group_by(JobSourceClassificationPathNode.source_classification_id)
            .all()
        )
        counts = {classification_id: count for classification_id, count in count_rows}
        catalog_rows = (
            self.db.query(
                JobSourceClassificationPath.id,
                JobSourceClassificationPath.source_site,
                JobSourceClassificationPath.source_order,
                JobSourceClassificationPathNode.source_position,
                JobSourceClassificationPathNode.native_depth,
                JobSourceClassificationPathNode.source_classification_id,
                JobSourceClassificationPathNode.label,
            )
            .join(
                JobSourceClassificationPathNode,
                JobSourceClassificationPathNode.path_id
                == JobSourceClassificationPath.id,
            )
            .join(Job, Job.id == JobSourceClassificationPath.job_id)
            .filter(Job.is_deleted.is_(False))
            .order_by(
                JobSourceClassificationPath.source_site,
                JobSourceClassificationPath.source_order,
                JobSourceClassificationPath.id,
                JobSourceClassificationPathNode.source_position,
            )
            .all()
        )

        options: list[JobSearchFacetOptionSchema] = []
        seen_ids: set[str] = set()
        current_path_id = None
        breadcrumb: list[str] = []
        parent_id: str | None = None
        for row in catalog_rows:
            if row.id != current_path_id:
                current_path_id = row.id
                breadcrumb = []
                parent_id = None
            breadcrumb.append(row.label)
            classification_id = row.source_classification_id
            if classification_id not in seen_ids:
                seen_ids.add(classification_id)
                options.append(
                    JobSearchFacetOptionSchema(
                        id=classification_id,
                        label=row.label,
                        count=counts.get(classification_id, 0),
                        order=len(options) + 1,
                        parent_id=parent_id,
                        level=str(row.native_depth),
                        source=row.source_site,
                        path=" / ".join(breadcrumb),
                    )
                )
            parent_id = classification_id
        return options

    def _company_industry_options(
        self,
        scope: JobSearchScopeSchema,
    ) -> list[JobSearchFacetOptionSchema]:
        candidate_jobs = self._candidate_job_ids(
            scope,
            without_fields=_COMPANY_INDUSTRY_FIELDS,
        )
        assignment_rows = (
            self.db.query(
                candidate_jobs.c.job_id,
                CurrentCompanyIndustryAssignment.taxonomy_code,
            )
            .join(Job, Job.id == candidate_jobs.c.job_id)
            .join(
                CurrentCompanyIndustryAssignment,
                CurrentCompanyIndustryAssignment.company_id == Job.company_id,
            )
            .all()
        )
        nodes = (
            self.db.query(CurrentTaxonomyNodeRecord)
            .filter(
                CurrentTaxonomyNodeRecord.taxonomy == "company_industry",
                CurrentTaxonomyNodeRecord.is_active.is_(True),
            )
            .all()
        )
        return self._hierarchy_options(nodes, assignment_rows)

    @staticmethod
    def _hierarchy_options(
        nodes: list[CurrentTaxonomyNodeRecord],
        assignment_rows,
    ) -> list[JobSearchFacetOptionSchema]:
        nodes_by_code = {node.code: node for node in nodes}
        jobs_by_code: dict[str, set] = {node.code: set() for node in nodes}
        for job_id, assigned_code in assignment_rows:
            code = assigned_code
            visited: set[str] = set()
            while code and code not in visited:
                visited.add(code)
                node = nodes_by_code.get(code)
                if node is None:
                    break
                jobs_by_code[code].add(job_id)
                code = node.parent_code

        children_by_parent: dict[str | None, list[CurrentTaxonomyNodeRecord]] = {}
        for node in nodes:
            children_by_parent.setdefault(node.parent_code, []).append(node)
        for children in children_by_parent.values():
            children.sort(key=lambda item: (item.sort_order, item.code))

        ordered_nodes: list[CurrentTaxonomyNodeRecord] = []

        def append_children(parent_code: str | None) -> None:
            for node in children_by_parent.get(parent_code, []):
                ordered_nodes.append(node)
                append_children(node.code)

        append_children(None)

        options = []
        for order, node in enumerate(ordered_nodes, start=1):
            labels = node.labels if isinstance(node.labels, dict) else {}
            label = labels.get("en") or next(
                (value for value in labels.values() if value),
                node.code,
            )
            options.append(
                JobSearchFacetOptionSchema(
                    id=node.code,
                    label=label,
                    count=len(jobs_by_code[node.code]),
                    order=order,
                    parent_id=node.parent_code,
                    level=node.level,
                )
            )
        return options
