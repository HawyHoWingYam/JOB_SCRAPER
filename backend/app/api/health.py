from fastapi import APIRouter

from app.ai.llm_client import refresh_llm_status

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check():
    """Health check endpoint for container orchestration."""
    llm_status = refresh_llm_status()

    if llm_status["is_degraded"]:
        return {
            "status": "degraded",
            "service": "backend-api",
            "issues": [f"LLM: {llm_status['degradation_reason']}"]
        }

    return {"status": "healthy", "service": "backend-api"}
