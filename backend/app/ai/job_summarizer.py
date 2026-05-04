"""Generate concise human-readable summaries for jobs."""

from __future__ import annotations

from typing import Optional

from app.ai.llm_client import get_llm_client

SUMMARY_PROMPT = """Write a concise 2-3 sentence summary of this job posting.

Focus on:
- the main responsibility of the role
- the likely team or business context
- the clearest requirements or signals from the description

Do not invent facts.

Job title: {title}
Job taxonomy: {job_taxonomy_path}
Job description:
{description}
"""


class JobSummarizer:
    """Create concise summaries from noisy job descriptions."""

    def __init__(self):
        self.llm = get_llm_client()

    async def summarize(
        self,
        *,
        title: str,
        description: str,
        job_taxonomy_path: Optional[str] = None,
    ) -> str:
        prompt = SUMMARY_PROMPT.format(
            title=title,
            job_taxonomy_path=job_taxonomy_path or "Unknown",
            description=description[:2000] if description else "No description provided.",
        )
        return await self.llm.generate(prompt)


_summarizer: Optional[JobSummarizer] = None


def get_job_summarizer() -> JobSummarizer:
    """Get singleton JobSummarizer instance."""
    global _summarizer
    if _summarizer is None:
        _summarizer = JobSummarizer()
    return _summarizer
