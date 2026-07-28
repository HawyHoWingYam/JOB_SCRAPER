from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Literal
import uuid

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models.company import Company
from app.models.job import Job
from app.models.manual_job import ManualJobEvidence, ManualJobMutationReceipt
from app.models.source_job_attributes import EmploymentType, JobEmploymentType
from app.schemas.job import ManualJobCreateSchema, NewCompanyChoiceSchema


class ManualJobIntakeError(RuntimeError):
    code = "manual_job_intake_error"
    status_code = 400

    def __init__(self, message: str, *, detail: dict[str, Any] | None = None):
        super().__init__(message)
        self.detail = {"code": self.code, "message": message, **(detail or {})}


class ManualJobDuplicateCandidatesError(ManualJobIntakeError):
    code = "duplicate_candidates"
    status_code = 409


class ManualJobIdempotencyConflictError(ManualJobIntakeError):
    code = "idempotency_key_conflict"
    status_code = 409


class ManualJobNotFoundError(ManualJobIntakeError):
    code = "manual_job_not_found"
    status_code = 404


class ManualJobNotEditableError(ManualJobIntakeError):
    code = "job_not_manual_editable"
    status_code = 409


class ManualJobRegistryError(ManualJobIntakeError):
    code = "employment_type_registry_incomplete"
    status_code = 409


@dataclass(frozen=True)
class ManualJobMutationResult:
    job: Job
    company: Company
    replayed: bool = False


class ManualJobIntake:
    """Own atomic Manual Job creation and editing behind one interface."""

    def __init__(self, db: Session):
        self._db = db

    def create(
        self,
        command: ManualJobCreateSchema,
        *,
        idempotency_key: str,
    ) -> ManualJobMutationResult:
        key = self._normalize_idempotency_key(idempotency_key)
        command_hash = self._command_hash(command, command_kind="create")
        replay = self._replay(key, command_hash)
        if replay is not None:
            return replay

        employment_codes = self._validate_employment_types(
            command.employment_type_codes
        )
        company, company_candidates = self._resolve_company_choice(command)
        job_candidates = self._job_candidates(command, company) if company else []
        self._require_duplicate_confirmation(
            command,
            command_hash=command_hash,
            company_candidates=company_candidates,
            job_candidates=job_candidates,
        )

        if company is None:
            company = self._create_company(command.company)

        manual_job_id = f"manual:{uuid.uuid4()}"
        job = Job(
            job_id=manual_job_id,
            source_site="manual",
            source_job_id=manual_job_id,
            company_id=company.id,
            title=command.title,
            description=command.description,
            salary_range=None,
            salary_min=command.salary_min,
            salary_max=command.salary_max,
            salary_currency=command.salary_currency,
            location=command.location,
            employment_type=None,
            posted_date=command.posted_date,
            experience_min_years=command.experience_min_years,
            experience_max_years=command.experience_max_years,
        )
        self._db.add(job)
        self._db.flush()
        self._replace_employment_types(job, employment_codes)
        self._db.add(self._build_evidence(job, command, company))
        self._db.add(
            ManualJobMutationReceipt(
                idempotency_key=key,
                command_hash=command_hash,
                command_kind="create",
                job_id=job.id,
                company_id=company.id,
            )
        )
        self._db.flush()
        return ManualJobMutationResult(job=job, company=company)

    def update(
        self,
        job_id,
        command: ManualJobCreateSchema,
        *,
        idempotency_key: str,
    ) -> ManualJobMutationResult:
        key = self._normalize_idempotency_key(idempotency_key)
        command_hash = self._command_hash(
            command,
            command_kind="update",
            job_id=str(job_id),
        )
        replay = self._replay(key, command_hash)
        if replay is not None:
            return replay

        job = (
            self._db.query(Job)
            .filter(Job.id == job_id, Job.is_deleted.is_(False))
            .with_for_update()
            .first()
        )
        if job is None:
            raise ManualJobNotFoundError("Manual Job was not found")
        if str(job.source_site or "").lower() != "manual":
            raise ManualJobNotEditableError(
                "Collected Source Jobs cannot be edited through Manual Job intake"
            )

        employment_codes = self._validate_employment_types(
            command.employment_type_codes
        )
        company, company_candidates = self._resolve_company_choice(command)
        job_candidates = (
            self._job_candidates(command, company, exclude_job_id=job.id)
            if company
            else []
        )
        self._require_duplicate_confirmation(
            command,
            command_hash=command_hash,
            company_candidates=company_candidates,
            job_candidates=job_candidates,
        )
        if company is None:
            company = self._create_company(command.company)

        job.company_id = company.id
        job.title = command.title
        job.description = command.description
        job.salary_range = None
        job.salary_min = command.salary_min
        job.salary_max = command.salary_max
        job.salary_currency = command.salary_currency
        job.location = command.location
        job.employment_type = None
        job.posted_date = command.posted_date
        job.experience_min_years = command.experience_min_years
        job.experience_max_years = command.experience_max_years
        self._replace_employment_types(job, employment_codes)

        evidence = (
            self._db.query(ManualJobEvidence)
            .filter(ManualJobEvidence.job_id == job.id)
            .first()
        )
        evidence_hash = self._evidence_hash(command, company)
        authored_fields = self._operator_authored_fields(command)
        if evidence is None:
            evidence = ManualJobEvidence(
                job_id=job.id,
                evidence_hash=evidence_hash,
                operator_authored_fields=authored_fields,
            )
            self._db.add(evidence)
        else:
            evidence.evidence_hash = evidence_hash
            evidence.operator_authored_fields = authored_fields

        self._db.add(
            ManualJobMutationReceipt(
                idempotency_key=key,
                command_hash=command_hash,
                command_kind="update",
                job_id=job.id,
                company_id=company.id,
            )
        )
        self._db.flush()
        return ManualJobMutationResult(job=job, company=company)

    def replay(
        self,
        command: ManualJobCreateSchema,
        *,
        idempotency_key: str,
        command_kind: Literal["create", "update"],
        job_id: str | None = None,
    ) -> ManualJobMutationResult | None:
        return self._replay(
            self._normalize_idempotency_key(idempotency_key),
            self._command_hash(command, command_kind=command_kind, job_id=job_id),
        )

    def _resolve_company_choice(
        self,
        command: ManualJobCreateSchema,
    ) -> tuple[Company | None, list[Company]]:
        choice = command.company
        if choice.mode == "existing":
            company = (
                self._db.query(Company)
                .filter(
                    Company.id == choice.company_id,
                    Company.is_deleted.is_(False),
                )
                .first()
            )
            if company is None:
                raise ManualJobIntakeError(
                    "Company was not found",
                    detail={"company_id": str(choice.company_id)},
                )
            return company, []

        normalized_name = choice.name.casefold()
        candidates = (
            self._db.query(Company)
            .filter(
                Company.is_deleted.is_(False),
                or_(
                    func.lower(func.trim(Company.name)) == normalized_name,
                    func.lower(Company.name).contains(normalized_name),
                    func.lower(choice.name).contains(func.lower(Company.name)),
                ),
            )
            .order_by(Company.created_at.asc(), Company.id.asc())
            .limit(10)
            .all()
        )
        return None, list(candidates)

    def _create_company(self, choice: NewCompanyChoiceSchema) -> Company:
        manual_company_id = f"manual:{uuid.uuid4()}"
        company = Company(
            company_id=manual_company_id,
            source_site="manual",
            source_company_id=manual_company_id,
            name=choice.name,
            website=choice.website,
            industry=choice.industry,
            location=choice.location,
        )
        self._db.add(company)
        self._db.flush()
        return company

    def _job_candidates(
        self,
        command: ManualJobCreateSchema,
        company: Company | None,
        *,
        exclude_job_id=None,
    ) -> list[Job]:
        if company is None:
            return []
        query = self._db.query(Job).filter(
            Job.company_id == company.id,
            Job.is_deleted.is_(False),
            func.lower(func.trim(Job.title)) == command.title.casefold(),
        )
        if exclude_job_id is not None:
            query = query.filter(Job.id != exclude_job_id)
        if command.location:
            query = query.filter(
                func.lower(func.trim(Job.location)) == command.location.casefold()
            )
        if command.posted_date:
            query = query.filter(Job.posted_date == command.posted_date)
        return list(query.order_by(Job.created_at.asc(), Job.id.asc()).limit(10).all())

    def _require_duplicate_confirmation(
        self,
        command: ManualJobCreateSchema,
        *,
        command_hash: str,
        company_candidates: list[Company],
        job_candidates: list[Job],
    ) -> None:
        if not company_candidates and not job_candidates:
            return
        company_ids = sorted(str(item.id) for item in company_candidates)
        job_ids = sorted(str(item.id) for item in job_candidates)
        confirmation = self._hash_payload(
            {
                "command_hash": command_hash,
                "company_candidate_ids": company_ids,
                "job_candidate_ids": job_ids,
            }
        )
        if command.duplicate_confirmation == confirmation:
            return
        raise ManualJobDuplicateCandidatesError(
            "Possible duplicate Companies or Jobs require an explicit decision",
            detail={
                "confirmation": confirmation,
                "company_candidates": [
                    {
                        "id": str(item.id),
                        "name": item.name,
                        "website": item.website,
                        "location": item.location,
                    }
                    for item in company_candidates
                ],
                "job_candidates": [
                    {
                        "id": str(item.id),
                        "title": item.title,
                        "location": item.location,
                        "posted_date": (
                            item.posted_date.isoformat() if item.posted_date else None
                        ),
                    }
                    for item in job_candidates
                ],
            },
        )

    def _validate_employment_types(self, requested: list[str]) -> list[str]:
        codes = list(dict.fromkeys(requested))
        if not codes:
            return []
        rows = (
            self._db.query(EmploymentType)
            .filter(EmploymentType.code.in_(codes))
            .all()
        )
        known = {row.code for row in rows}
        missing = [code for code in codes if code not in known]
        if missing:
            raise ManualJobRegistryError(
                "Employment Type registry is incomplete",
                detail={"missing_codes": missing},
            )
        return codes

    def _replace_employment_types(self, job: Job, codes: list[str]) -> None:
        if job.id is not None:
            (
                self._db.query(JobEmploymentType)
                .filter(JobEmploymentType.job_id == job.id)
                .delete(synchronize_session=False)
            )
        for code in codes:
            self._db.add(
                JobEmploymentType(
                    job_id=job.id,
                    employment_type_code=code,
                    evidence_label_ids=[],
                    provenance={
                        "method": "manual_operator_selection",
                        "actor": "local-operator",
                        "source": "add-job",
                    },
                )
            )

    def _build_evidence(
        self,
        job: Job,
        command: ManualJobCreateSchema,
        company: Company,
    ) -> ManualJobEvidence:
        return ManualJobEvidence(
            job_id=job.id,
            evidence_hash=self._evidence_hash(command, company),
            operator_authored_fields=self._operator_authored_fields(command),
        )

    def _evidence_hash(
        self,
        command: ManualJobCreateSchema,
        company: Company,
    ) -> str:
        payload = command.model_dump(mode="json", exclude={"duplicate_confirmation"})
        payload["company"] = {"company_id": str(company.id)}
        return self._hash_payload(payload)

    @staticmethod
    def _operator_authored_fields(command: ManualJobCreateSchema) -> list[str]:
        fields = ["title", "company_id"]
        for field in (
            "description",
            "salary_min",
            "salary_max",
            "location",
            "posted_date",
            "experience_min_years",
            "experience_max_years",
        ):
            if getattr(command, field) is not None:
                fields.append(field)
        if command.salary_min is not None or command.salary_max is not None:
            fields.append("salary_currency")
        if command.employment_type_codes:
            fields.append("employment_type_codes")
        return fields

    def _replay(
        self,
        idempotency_key: str,
        command_hash: str,
    ) -> ManualJobMutationResult | None:
        receipt = (
            self._db.query(ManualJobMutationReceipt)
            .filter(ManualJobMutationReceipt.idempotency_key == idempotency_key)
            .first()
        )
        if receipt is None:
            return None
        if receipt.command_hash != command_hash:
            raise ManualJobIdempotencyConflictError(
                "Idempotency key was already used for a different command"
            )
        job = self._db.query(Job).filter(Job.id == receipt.job_id).first()
        company = self._db.query(Company).filter(Company.id == receipt.company_id).first()
        if job is None or company is None:
            raise ManualJobIntakeError(
                "Stored Manual Job idempotency result is no longer available"
            )
        return ManualJobMutationResult(job=job, company=company, replayed=True)

    @staticmethod
    def _normalize_idempotency_key(value: str) -> str:
        normalized = str(value or "").strip()
        if not normalized or len(normalized) > 255:
            raise ManualJobIntakeError(
                "Idempotency-Key must contain between 1 and 255 characters"
            )
        return normalized

    def _command_hash(
        self,
        command: ManualJobCreateSchema,
        *,
        command_kind: str,
        job_id: str | None = None,
    ) -> str:
        return self._hash_payload(
            {
                "command_kind": command_kind,
                "job_id": job_id,
                "command": command.model_dump(
                    mode="json",
                    exclude={"duplicate_confirmation"},
                ),
            }
        )

    @staticmethod
    def _hash_payload(payload: Any) -> str:
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "ManualJobDuplicateCandidatesError",
    "ManualJobIdempotencyConflictError",
    "ManualJobIntake",
    "ManualJobIntakeError",
    "ManualJobMutationResult",
    "ManualJobNotEditableError",
    "ManualJobNotFoundError",
    "ManualJobRegistryError",
]
