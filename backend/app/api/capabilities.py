from fastapi import APIRouter

from app.services.runtime_capabilities_service import build_runtime_capabilities

router = APIRouter(tags=["capabilities"])


@router.get("/capabilities")
async def get_capabilities():
    return build_runtime_capabilities()
