from fastapi import APIRouter

from app.ai.llm_client import refresh_llm_status

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check():
    """Health check endpoint for container orchestration."""
    job_llm_status = refresh_llm_status()
    company_llm_status = refresh_llm_status("companies")
    degraded_issues = []

    if job_llm_status["is_degraded"]:
        degraded_issues.append(f"Job LLM: {job_llm_status['degradation_reason']}")
    if company_llm_status["is_degraded"]:
        degraded_issues.append(f"Company LLM: {company_llm_status['degradation_reason']}")

    if degraded_issues:
        return {
            "status": "degraded",
            "service": "backend-api",
            "issues": degraded_issues,
        }

    return {"status": "healthy", "service": "backend-api"}
