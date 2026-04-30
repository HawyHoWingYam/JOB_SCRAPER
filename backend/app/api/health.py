from fastapi import APIRouter

from app.ai.llm_client import get_llm_client, get_llm_status

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check():
    """Health check endpoint for container orchestration."""
    # Trigger LLM client initialization to check configuration
    get_llm_client()
    llm_status = get_llm_status()

    if llm_status["is_degraded"]:
        return {
            "status": "degraded",
            "service": "backend-api",
            "issues": [f"LLM: {llm_status['degradation_reason']}"]
        }

    return {"status": "healthy", "service": "backend-api"}
