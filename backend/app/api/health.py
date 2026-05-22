from fastapi import APIRouter

from app.ai.llm_client import refresh_llm_status
from app.services import operator_health_service

router = APIRouter(tags=["health"])


def build_operator_health_summary() -> dict:
    return operator_health_service.build_operator_health_summary()


@router.get("/health")
async def health_check():
    """Health check endpoint for container orchestration."""
    job_llm_status = refresh_llm_status()
    company_llm_status = refresh_llm_status("companies")
    operator_status = build_operator_health_summary()
    degraded_issues = []

    if job_llm_status["is_degraded"]:
        degraded_issues.append(f"Job LLM: {job_llm_status['degradation_reason']}")
    if company_llm_status["is_degraded"]:
        degraded_issues.append(f"Company LLM: {company_llm_status['degradation_reason']}")
    if operator_status["status"] != "healthy":
        degraded_issues.extend(operator_status.get("issues") or [])

    if degraded_issues:
        return {
            "status": "degraded",
            "service": "backend-api",
            "issues": degraded_issues,
            "operator": operator_status,
        }

    return {"status": "healthy", "service": "backend-api", "operator": operator_status}
