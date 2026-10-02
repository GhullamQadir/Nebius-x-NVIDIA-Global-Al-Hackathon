from fastapi import APIRouter
from packages.contracts.run import HealthResponse

router = APIRouter(tags=["Health"])


@router.get("/v1/health", response_model=HealthResponse, summary="Service Health Check")
@router.get("/health", response_model=HealthResponse, include_in_schema=False)
async def get_health():
    """
    Returns the system health status, service identity, and current timestamp.
    """
    return HealthResponse(
        status="healthy",
        service="nexora-backend",
        version="0.1.0"
    )
