from fastapi import APIRouter

from app.services import operator_health_service

router = APIRouter(prefix="/operator", tags=["operator"])


@router.get("/health")
async def operator_health_check():
    return operator_health_service.build_operator_health_summary()
