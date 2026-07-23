"""AI helpers for company-level enrichment."""

from __future__ import annotations

import re

from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import NoResultFound

from app.ai.llm_client import get_llm_client
from app.database import SessionLocal
from app.models import Company, Job

_PROCESS_NARRATION_PREFIXES = (
    "searching ",
    "looking up ",
    "looking for ",
    "checking ",
    "verifying ",
    "i am checking ",
    "i am verifying ",
    "i am searching ",
    "i am looking up ",
    "i'm checking ",
    "i'm verifying ",
    "i'm searching ",
    "i'm looking up ",
)
_PROCESS_NARRATION_RE = re.compile(r"\bthen i(?:'| a)?ll\b|\bcondense\b|\bdistill\b")
_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")


def normalize_company_description(text: str) -> str:
    """Reject process narration and normalize final company description text."""
    normalized = " ".join(str(text or "").split()).strip()
    normalized = _MARKDOWN_LINK_RE.sub(r"\1", normalized)
    if not normalized:
        raise ValueError("LLM returned an empty company description")

    lowered = normalized.lower()
    if lowered.startswith(_PROCESS_NARRATION_PREFIXES) and _PROCESS_NARRATION_RE.search(lowered):
        raise ValueError(
            "LLM returned process narration instead of a final company description"
        )

    return normalized


class CompanyEnrichmentService:
    """Generate concise AI descriptions for companies."""

    def __init__(self, llm=None):
        self.llm = llm or get_llm_client("companies")

    async def enrich_company_description(
        self,
        company,
        db: Session,
        force: bool = False,
        web_search_enabled: bool = False,
    ) -> dict:
        """Generate and persist a concise AI description for a company."""
        if self._has_ai_description(company) and not force:
            return {
                "company_id": str(company.id),
                "ai_description": company.ai_description,
            }

        company.ai_description = await self._generate_company_description(
            company,
            db,
            web_search_enabled=web_search_enabled,
        )
        db.commit()
        db.refresh(company)
        return {
            "company_id": str(company.id),
            "ai_description": company.ai_description,
        }

    async def enrich_company_id(
        self,
        company_id,
        force: bool = False,
        web_search_enabled: bool = False,
    ) -> dict:
        """Generate a company description using an isolated DB session."""
        db = SessionLocal()
        try:
            company = (
                db.query(Company)
                .filter(
                    Company.id == company_id,
                    Company.is_deleted.is_(False),
                )
                .first()
            )
            if company is None:
                raise NoResultFound(f"Company not found for enrichment: {company_id}")
            return await self.enrich_company_description(
                company,
                db,
                force=force,
                web_search_enabled=web_search_enabled,
            )
        finally:
            db.close()

    async def enrich_company_descriptions(
        self,
        companies,
        db: Session,
        force: bool = False,
        web_search_enabled: bool = False,
    ) -> dict:
        """Generate and persist concise AI descriptions for a batch of companies."""
        enriched_companies = []
        for company in companies:
            if self._has_ai_description(company) and not force:
                continue
            company.ai_description = await self._generate_company_description(
                company,
                db,
                web_search_enabled=web_search_enabled,
            )
            enriched_companies.append(company)

        if enriched_companies:
            db.commit()
        for company in enriched_companies:
            db.refresh(company)

        return {
            "processed_count": len(enriched_companies),
            "companies": [
                {
                    "company_id": str(company.id),
                    "ai_description": company.ai_description,
                }
                for company in enriched_companies
            ],
        }

    def _has_ai_description(self, company) -> bool:
        """Return whether the company already has a usable AI description."""
        return bool((company.ai_description or "").strip())

    async def _generate_company_description(
        self,
        company,
        db: Session,
        *,
        web_search_enabled: bool = False,
    ) -> str:
        """Generate company description text from recent hiring signals."""
        jobs = (
            db.query(Job)
            .filter(
                Job.company_id == company.id,
                Job.is_deleted.is_(False),
            )
            .order_by(Job.posted_date.desc(), Job.created_at.desc())
            .limit(5)
            .all()
        )

        description = await self.llm.generate(
            self._build_company_prompt(
                company,
                jobs,
                allow_web_search=web_search_enabled,
            ),
            web_search=web_search_enabled,
        )
        return normalize_company_description(description)

    def _build_company_prompt(self, company, jobs: list[Job], *, allow_web_search: bool) -> str:
        """Build a concise prompt from company metadata and recent jobs."""
        job_lines = []
        for job in jobs:
            description = (job.description or "").strip()
            if len(description) > 280:
                description = f"{description[:280]}..."
            taxonomy_path = job.job_taxonomy_path or job.source_classification_name or "Unknown"
            job_lines.append(
                f"- {job.title} | taxonomy: {taxonomy_path} | {description or 'No description'}"
            )

        jobs_context = "\n".join(job_lines) if job_lines else "- No recent jobs available"
        search_guidance = (
            "Search the web first for current public information about the company.\n"
            if allow_web_search
            else "Use only the provided company metadata and recent hiring signals.\n"
        )
        return (
            "Write a short factual company description in 2-4 sentences.\n"
            f"{search_guidance}"
            "Return only the final company description.\n"
            "Do not describe your search process or say that you are checking sources.\n"
            "Use the provided company metadata and recent hiring signals as supporting context.\n"
            "If search results are sparse, stay conservative and only state what is supported.\n"
            "Do not invent facts.\n\n"
            f"Company name: {company.name}\n"
            f"Industry: {company.industry or 'Unknown'}\n"
            f"Location: {company.location or 'Unknown'}\n"
            f"Recent jobs:\n{jobs_context}\n"
        )
