"""AI helpers for company-level enrichment."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.ai.llm_client import get_llm_client
from app.models import Job


class CompanyEnrichmentService:
    """Generate concise AI descriptions for companies."""

    def __init__(self):
        self.llm = get_llm_client()

    async def enrich_company_description(self, company, db: Session, force: bool = False) -> dict:
        """Generate and persist a concise AI description for a company."""
        if self._has_ai_description(company) and not force:
            return {
                "company_id": str(company.id),
                "ai_description": company.ai_description,
            }

        company.ai_description = await self._generate_company_description(company, db)
        db.commit()
        db.refresh(company)
        return {
            "company_id": str(company.id),
            "ai_description": company.ai_description,
        }

    async def enrich_company_descriptions(self, companies, db: Session, force: bool = False) -> dict:
        """Generate and persist concise AI descriptions for a batch of companies."""
        enriched_companies = []
        for company in companies:
            if self._has_ai_description(company) and not force:
                continue
            company.ai_description = await self._generate_company_description(company, db)
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

    async def _generate_company_description(self, company, db: Session) -> str:
        """Generate company description text from recent hiring signals."""
        jobs = (
            db.query(Job)
            .filter(
                Job.company_id == company.id,
                Job.is_deleted == False,
            )
            .order_by(Job.posted_date.desc(), Job.created_at.desc())
            .limit(5)
            .all()
        )

        return await self.llm.generate(
            self._build_company_prompt(company, jobs),
            web_search=True,
        )

    def _build_company_prompt(self, company, jobs: list[Job]) -> str:
        """Build a concise prompt from company metadata and recent jobs."""
        job_lines = []
        for job in jobs:
            description = (job.description or "").strip()
            if len(description) > 280:
                description = f"{description[:280]}..."
            job_lines.append(
                f"- {job.title} | category: {job.ai_category or 'Unknown'} | {description or 'No description'}"
            )

        jobs_context = "\n".join(job_lines) if job_lines else "- No recent jobs available"
        return (
            "Write a short factual company description in 2-4 sentences.\n"
            "Search the web first for current public information about the company.\n"
            "Use the provided company metadata and recent hiring signals as supporting context.\n"
            "If search results are sparse, stay conservative and only state what is supported.\n"
            "Do not invent facts.\n\n"
            f"Company name: {company.name}\n"
            f"Industry: {company.industry or 'Unknown'}\n"
            f"Location: {company.location or 'Unknown'}\n"
            f"Recent jobs:\n{jobs_context}\n"
        )
