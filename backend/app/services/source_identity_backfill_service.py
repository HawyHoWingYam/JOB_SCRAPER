from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass

from sqlalchemy.orm import Session, undefer

from app.models import Company, Job
from app.utils.source_identity import (
    build_compat_company_id,
    build_compat_job_id,
    derive_source_company_id_from_compat,
    derive_source_company_id_from_raw_data,
    derive_source_job_id,
    normalize_source_site,
)


@dataclass(frozen=True)
class SourceCompanyGroup:
    source_site: str
    source_company_id: str
    jobs: list[Job]


class SourceIdentityBackfillService:
    """Backfill source-owned identity fields for jobs and companies."""

    def backfill_source_identity(self, db: Session) -> None:
        self._backfill_jobs(db)
        self._backfill_companies(db)
        db.flush()

    def _backfill_jobs(self, db: Session) -> None:
        jobs = (
            db.query(Job)
            .options(
                undefer(Job.source_site),
                undefer(Job.source_job_id),
            )
            .all()
        )
        for job in jobs:
            job.source_site = normalize_source_site(job.source_site)
            job.source_job_id = derive_source_job_id(job.source_site, job.job_id)
            job.job_id = build_compat_job_id(job.source_site, job.source_job_id)

    def _backfill_companies(self, db: Session) -> None:
        companies = (
            db.query(Company)
            .options(
                undefer(Company.source_site),
                undefer(Company.source_company_id),
            )
            .all()
        )

        for company in companies:
            grouped_jobs = self._group_jobs_for_company(company)
            if not grouped_jobs:
                source_site = normalize_source_site(company.source_site)
                source_company_id = (
                    company.source_company_id
                    or derive_source_company_id_from_compat(source_site, company.company_id)
                )
                if not source_company_id:
                    raise ValueError(f"Unable to derive source company identity for company {company.id}")
                company.source_site = source_site
                company.source_company_id = source_company_id
                company.company_id = build_compat_company_id(source_site, source_company_id)
                continue

            primary_group = self._choose_primary_group(company, grouped_jobs)
            self._apply_group_to_company(company, primary_group)

            for group in grouped_jobs:
                if group == primary_group:
                    continue
                target_company = self._find_reusable_company(db, company, group)
                if target_company is None:
                    target_company = Company(
                        company_id=build_compat_company_id(group.source_site, group.source_company_id),
                        source_site=group.source_site,
                        source_company_id=group.source_company_id,
                        name=company.name,
                        industry=company.industry,
                        location=company.location,
                        ai_description=company.ai_description,
                        extra_data=company.extra_data,
                        is_deleted=company.is_deleted,
                    )
                    db.add(target_company)
                    db.flush()
                else:
                    self._apply_group_to_company(target_company, group)

                for job in group.jobs:
                    job.company_id = target_company.id

    def _group_jobs_for_company(self, company: Company) -> list[SourceCompanyGroup]:
        grouped: "OrderedDict[tuple[str, str], list[Job]]" = OrderedDict()

        for job in company.jobs:
            source_site = normalize_source_site(job.source_site)
            source_company_id = derive_source_company_id_from_raw_data(source_site, job.raw_data)
            if not source_company_id:
                source_company_id = derive_source_company_id_from_compat(source_site, company.company_id)
            if not source_company_id:
                raise ValueError(
                    f"Unable to derive source company id for company {company.id} from job {job.id}"
                )
            key = (source_site, source_company_id)
            grouped.setdefault(key, []).append(job)

        return [
            SourceCompanyGroup(source_site=source_site, source_company_id=source_company_id, jobs=jobs)
            for (source_site, source_company_id), jobs in grouped.items()
        ]

    def _choose_primary_group(
        self,
        company: Company,
        groups: list[SourceCompanyGroup],
    ) -> SourceCompanyGroup:
        compat_company_id = str(company.company_id or "").strip()

        for group in groups:
            if compat_company_id == build_compat_company_id(group.source_site, group.source_company_id):
                return group

        for group in groups:
            if group.source_site == "jobsdb":
                return group

        return groups[0]

    def _apply_group_to_company(self, company: Company, group: SourceCompanyGroup) -> None:
        company.source_site = group.source_site
        company.source_company_id = group.source_company_id
        company.company_id = build_compat_company_id(group.source_site, group.source_company_id)

    def _find_reusable_company(
        self,
        db: Session,
        current_company: Company,
        group: SourceCompanyGroup,
    ) -> Company | None:
        compat_company_id = build_compat_company_id(group.source_site, group.source_company_id)
        return (
            db.query(Company)
            .filter(
                Company.id != current_company.id,
                Company.company_id == compat_company_id,
            )
            .one_or_none()
        )
